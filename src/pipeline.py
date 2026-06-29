"""Async capture → inference → overlay pipeline targeting high refresh rates."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from src.capture.screen_capture import CaptureFrame, ScreenCapture
from src.inference.box_smoother import BoxSmoother
from src.inference.detector import Detection, YoloDetector
from src.inference.forward_model import ForwardPredictor
from src.overlay.overlay_window import OverlayApp
from src.timing import precise_sleep


@dataclass
class PipelineStats:
    capture_fps: float = 0.0
    inference_fps: float = 0.0
    inference_ms: float = 0.0   # EMA of detector latency per frame
    frames_captured: int = 0
    frames_inferred: int = 0


class FrameSightPipeline:
    """
    Three-stage pipeline:
      1. Capture thread — grabs screen as fast as possible (target: 165 Hz)
      2. Inference thread — always processes the newest frame (drops stale)
      3. Main thread — drives overlay + stats
    """

    def __init__(
        self,
        capture: ScreenCapture,
        detector: YoloDetector,
        overlay: Optional[OverlayApp],
        target_capture_fps: int = 165,
        max_queue: int = 2,
        smoother: Optional[BoxSmoother] = None,
        predictor: Optional[ForwardPredictor] = None,
    ) -> None:
        self._capture = capture
        self._detector = detector
        self._overlay = overlay
        self._smoother = smoother
        self._predictor = predictor
        self._target_capture_fps = target_capture_fps
        self._frame_queue: queue.Queue[CaptureFrame] = queue.Queue(maxsize=max_queue)
        self._latest_detections: List[Detection] = []
        self._det_lock = threading.Lock()
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._stats = PipelineStats()
        self._stop = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._infer_thread: Optional[threading.Thread] = None

    @property
    def stats(self) -> PipelineStats:
        return self._stats

    def start(self) -> None:
        self._stop.clear()
        # Let the overlay pull freshly-extrapolated boxes at its own paint time
        # (see overlay_detections) instead of being fed stale, main-loop-rate
        # detections. This is what actually makes the forward model hide latency.
        if self._overlay is not None and hasattr(self._overlay, "set_detection_provider"):
            self._overlay.set_detection_provider(self.overlay_detections)
        if self._overlay is not None and hasattr(self._overlay, "set_stats_provider"):
            self._overlay.set_stats_provider(lambda: self._stats)
        # Feed the latest captured frame to the overlay so it can draw a
        # magnified inset of the screen center.
        if self._overlay is not None and hasattr(self._overlay, "set_frame_provider"):
            self._overlay.set_frame_provider(self.latest_frame)
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._infer_thread = threading.Thread(target=self._infer_loop, daemon=True)
        self._capture_thread.start()
        self._infer_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for t in (self._capture_thread, self._infer_thread):
            if t and t.is_alive():
                t.join(timeout=2.0)

    def _capture_loop(self) -> None:
        interval = 1.0 / self._target_capture_fps
        cap_count = 0
        t0 = time.perf_counter()

        while not self._stop.is_set():
            loop_start = time.perf_counter()
            try:
                frame = self._capture.grab()
            except Exception as exc:  # noqa: BLE001 — device loss/display change
                print(f"\nCapture error ({type(exc).__name__}: {exc}) — recovering...")
                if hasattr(self._capture, "reinit"):
                    try:
                        self._capture.reinit()
                    except Exception:
                        pass
                # Back off briefly so a persistent failure doesn't spin the CPU.
                self._stop.wait(0.5)
                continue
            cap_count += 1
            with self._frame_lock:
                self._latest_frame = frame.bgr

            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                pass

            elapsed = time.perf_counter() - t0
            if elapsed >= 1.0:
                self._stats.capture_fps = cap_count / elapsed
                self._stats.frames_captured += cap_count
                cap_count = 0
                t0 = time.perf_counter()

            precise_sleep(interval - (time.perf_counter() - loop_start))

    def _infer_loop(self) -> None:
        inf_count = 0
        t0 = time.perf_counter()

        while not self._stop.is_set():
            try:
                frame = self._frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            # Drain queue — only infer the newest frame
            while True:
                try:
                    frame = self._frame_queue.get_nowait()
                except queue.Empty:
                    break

            try:
                t_pred = time.perf_counter()
                detections = self._detector.predict(frame.bgr)
                dt_ms = (time.perf_counter() - t_pred) * 1000.0
                # EMA so the HUD shows a steady latency, not per-frame jitter.
                self._stats.inference_ms = 0.2 * dt_ms + 0.8 * self._stats.inference_ms
                if self._smoother is not None:
                    detections = self._smoother.update(detections)
                with self._det_lock:
                    self._latest_detections = detections
                    if self._predictor is not None:
                        self._predictor.update(detections, time.perf_counter())
            except Exception as exc:  # noqa: BLE001
                # Never let a bad frame kill the inference thread — keep last boxes.
                if not getattr(self, "_infer_err_logged", False):
                    print(f"\nInference error (continuing): {type(exc).__name__}: {exc}")
                    self._infer_err_logged = True
                continue

            inf_count += 1
            elapsed = time.perf_counter() - t0
            if elapsed >= 1.0:
                self._stats.inference_fps = inf_count / elapsed
                self._stats.frames_inferred += inf_count
                inf_count = 0
                t0 = time.perf_counter()

    def latest_frame(self):
        """Most recent captured BGR frame (capture-region pixels), or None."""
        with self._frame_lock:
            return self._latest_frame

    def overlay_detections(self) -> List[Detection]:
        """Boxes extrapolated to *now* — called by the overlay at paint time.

        Evaluating the forward model at the moment of the draw (rather than in
        the main loop) is what lets the boxes track the target at the overlay's
        full refresh rate instead of the slower inference/main-loop rate.
        """
        now = time.perf_counter()
        with self._det_lock:
            if self._predictor is not None:
                return self._predictor.predict(now)
            return list(self._latest_detections)

    def tick_overlay(self) -> List[Detection]:
        dets = self.overlay_detections()
        # Overlays that support set_detection_provider pull their own frames;
        # only push for ones that don't (keeps older overlays working).
        if self._overlay and not hasattr(self._overlay, "set_detection_provider"):
            self._overlay.update_detections(dets)
        return dets
