"""Orchestrates decode -> inference -> annotated MJPEG, with no prediction.

Three roles:
  * the buffered video source decodes ahead (smoothing playback),
  * a player thread paces frames at the source FPS, taps the current frame to
    the inference thread, draws the *latest* detections, and publishes a JPEG,
  * an inference thread runs the detector as fast as it can on whatever frame is
    currently on screen and updates the latest detections.

Boxes are never extrapolated to a future time — the latest completed detection
is drawn on the frame being shown. Inference lag shows up as boxes refreshing a
little behind fast motion, not as the wobble a forward predictor introduces.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Generator, List, Optional

import cv2
import numpy as np

from src.inference.detector import Detection
from src.web.draw import draw_detections
from src.web.render_settings import RenderSettings
from src.web.video_source import ENDED, BufferedVideoSource


class _Rate:
    """Rolling frames-per-second counter."""

    def __init__(self) -> None:
        self._count = 0
        self._t0 = time.perf_counter()
        self.value = 0.0

    def tick(self) -> None:
        self._count += 1
        elapsed = time.perf_counter() - self._t0
        if elapsed >= 0.5:
            self.value = self._count / elapsed
            self._count = 0
            self._t0 = time.perf_counter()

    def reset(self) -> None:
        self._count = 0
        self._t0 = time.perf_counter()
        self.value = 0.0


class Annotator:
    def __init__(
        self,
        detector,
        source: BufferedVideoSource,
        settings: RenderSettings,
        jpeg_quality: int = 80,
    ) -> None:
        self._detector = detector
        self._source = source
        self._settings = settings
        self._jpeg_quality = int(jpeg_quality)

        self._stop = threading.Event()
        self._player: Optional[threading.Thread] = None
        self._infer: Optional[threading.Thread] = None

        self._infer_input: Optional[np.ndarray] = None
        self._infer_lock = threading.Lock()

        self._detections: List[Detection] = []
        self._det_lock = threading.Lock()

        self._last_raw: Optional[np.ndarray] = None  # for redraw while paused

        self._jpeg: Optional[bytes] = None
        self._jpeg_seq = 0
        self._frame_cond = threading.Condition()

        self._display_rate = _Rate()
        self._infer_rate = _Rate()
        self._pos = 0
        self._ended = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._source.start()
        self._stop.clear()
        self._infer = threading.Thread(target=self._infer_loop, daemon=True)
        self._player = threading.Thread(target=self._player_loop, daemon=True)
        self._infer.start()
        self._player.start()

    def stop(self) -> None:
        self._stop.set()
        self._source.stop()
        with self._frame_cond:
            self._frame_cond.notify_all()
        for t in (self._player, self._infer):
            if t and t.is_alive():
                t.join(timeout=1.5)

    # -- playback controls -------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        self._source.set_paused(paused)
        if not paused:
            self._display_rate.reset()

    def seek_fraction(self, fraction: float) -> None:
        self._source.seek_fraction(fraction)

    # -- worker loops ------------------------------------------------------
    def _player_loop(self) -> None:
        interval = 1.0 / max(1.0, self._source.fps)
        next_t = time.perf_counter()
        while not self._stop.is_set():
            if self._source.paused:
                # Pull a frame only if one arrives (e.g. after a scrub), then
                # keep re-drawing the held frame so live setting changes show.
                item = self._source.read(timeout=0.05)
                if item is ENDED:
                    self._ended = True
                    break
                if item is not None:
                    self._pos, self._last_raw = item[0], item[1]
                self._render_and_publish(self._last_raw)
                time.sleep(1.0 / 30.0)
                next_t = time.perf_counter()
                continue

            item = self._source.read(timeout=0.5)
            if item is ENDED:
                self._ended = True
                break
            if item is None:
                continue  # nothing buffered yet
            self._pos, frame = item[0], item[1]
            self._last_raw = frame

            with self._infer_lock:
                self._infer_input = frame
            self._render_and_publish(frame)
            self._display_rate.tick()

            next_t += interval
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.perf_counter()  # fell behind; resync

    def _render_and_publish(self, frame: Optional[np.ndarray]) -> None:
        if frame is None:
            return
        out = frame.copy()
        with self._det_lock:
            detections = list(self._detections)
        draw_detections(out, detections, self._settings.snapshot())
        ok, buf = cv2.imencode(
            ".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        )
        if ok:
            self._publish(buf.tobytes())

    def _infer_loop(self) -> None:
        while not self._stop.is_set():
            with self._infer_lock:
                frame = self._infer_input
                self._infer_input = None
            if frame is None:
                time.sleep(0.002)
                continue
            try:
                detections = self._detector.predict(frame)
            except Exception as exc:  # noqa: BLE001
                print(f"Inference error (continuing): {type(exc).__name__}: {exc}")
                time.sleep(0.01)
                continue
            with self._det_lock:
                self._detections = detections
            self._infer_rate.tick()

    def _publish(self, jpeg: bytes) -> None:
        with self._frame_cond:
            self._jpeg = jpeg
            self._jpeg_seq += 1
            self._frame_cond.notify_all()

    # -- consumers ---------------------------------------------------------
    def mjpeg(self) -> Generator[bytes, None, None]:
        """Yield an MJPEG multipart stream of the latest annotated frames."""
        last_seq = -1
        boundary = b"--frame\r\n"
        while not self._stop.is_set():
            with self._frame_cond:
                if self._jpeg_seq == last_seq:
                    self._frame_cond.wait(timeout=1.0)
                if self._jpeg is None or self._jpeg_seq == last_seq:
                    continue
                last_seq = self._jpeg_seq
                jpeg = self._jpeg
            yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

    def stats(self) -> Dict[str, Any]:
        fc = self._source.frame_count
        return {
            "display_fps": round(self._display_rate.value, 1),
            "inference_fps": round(self._infer_rate.value, 1),
            "source_fps": round(self._source.fps, 1),
            "resolution": [self._source.width, self._source.height],
            "paused": self._source.paused,
            "seekable": self._source.seekable,
            "position": self._pos,
            "frame_count": fc,
            "progress": round(self._pos / fc, 4) if fc else 0.0,
            "ended": self._ended,
        }
