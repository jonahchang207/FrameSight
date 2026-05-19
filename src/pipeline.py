"""Async capture → inference → overlay pipeline targeting high refresh rates."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from src.capture.screen_capture import CaptureFrame, ScreenCapture
from src.inference.detector import Detection, YoloDetector
from src.overlay.overlay_window import OverlayApp


@dataclass
class PipelineStats:
    capture_fps: float = 0.0
    inference_fps: float = 0.0
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
    ) -> None:
        self._capture = capture
        self._detector = detector
        self._overlay = overlay
        self._target_capture_fps = target_capture_fps
        self._frame_queue: queue.Queue[CaptureFrame] = queue.Queue(maxsize=max_queue)
        self._latest_detections: List[Detection] = []
        self._det_lock = threading.Lock()
        self._stats = PipelineStats()
        self._stop = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._infer_thread: Optional[threading.Thread] = None

    @property
    def stats(self) -> PipelineStats:
        return self._stats

    def start(self) -> None:
        self._stop.clear()
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
            frame = self._capture.grab()
            cap_count += 1

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

            sleep_for = interval - (time.perf_counter() - loop_start)
            if sleep_for > 0:
                time.sleep(sleep_for)

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

            detections = self._detector.predict(frame.bgr)
            with self._det_lock:
                self._latest_detections = detections

            inf_count += 1
            elapsed = time.perf_counter() - t0
            if elapsed >= 1.0:
                self._stats.inference_fps = inf_count / elapsed
                self._stats.frames_inferred += inf_count
                inf_count = 0
                t0 = time.perf_counter()

    def tick_overlay(self) -> List[Detection]:
        with self._det_lock:
            dets = list(self._latest_detections)
        if self._overlay:
            self._overlay.update_detections(dets)
        return dets
