"""Windows DXGI desktop capture via dxcam (faster than mss on Windows)."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

if sys.platform != "win32":
    raise ImportError("win_capture requires Windows")

import dxcam

from src.capture.screen_capture import CaptureFrame


class WinScreenCapture:
    """High-FPS capture using Desktop Duplication API."""

    def __init__(
        self,
        monitor_index: int = 0,
        region: Optional[list[int]] = None,
        target_fps: int = 165,
    ) -> None:
        # dxcam output_idx is 0-based; config uses 1-based monitor_index
        self._output_idx = max(0, monitor_index - 1)
        self._region = tuple(region) if region else None
        self._frame_id = 0
        self._target_fps = target_fps
        # Background capture for high refresh (optional; falls back to grab())
        self._use_video_mode = target_fps > 0
        self._start_camera()

    def _start_camera(self) -> None:
        self._camera = dxcam.create(output_idx=self._output_idx, output_color="BGR")
        if self._use_video_mode:
            self._camera.start(target_fps=min(self._target_fps, 240), video_mode=True)

    def reinit(self) -> None:
        """Recreate the dxcam device after a capture failure (display change,
        device loss, resolution switch). Best-effort; raises if it can't recover."""
        try:
            if self._use_video_mode:
                self._camera.stop()
        except Exception:
            pass
        try:
            del self._camera
        except Exception:
            pass
        self._start_camera()

    def grab(self) -> CaptureFrame:
        if self._region:
            left, top, width, height = self._region
            region = (left, top, left + width, top + height)
            frame = self._get_latest()
            if frame is not None:
                frame = frame[top : top + height, left : left + width]
            else:
                frame = self._camera.grab(region=region)
        else:
            frame = self._get_latest()
            if frame is None:
                frame = self._camera.grab()

        if frame is None:
            # Duplicate frame or startup — return small black buffer once
            frame = np.zeros((1, 1, 3), dtype=np.uint8)

        self._frame_id += 1
        return CaptureFrame(
            bgr=frame.copy(),
            timestamp=time.perf_counter(),
            frame_id=self._frame_id,
        )

    def _get_latest(self):
        if not self._use_video_mode:
            return None
        try:
            return self._camera.get_latest_frame()
        except Exception:
            return None

    def close(self) -> None:
        try:
            if self._use_video_mode:
                self._camera.stop()
        except Exception:
            pass
