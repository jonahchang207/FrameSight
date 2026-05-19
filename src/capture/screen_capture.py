"""Screen capture factory — Windows DXGI only."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class CaptureFrame:
    bgr: object  # numpy ndarray (BGR)
    timestamp: float
    frame_id: int


def create_capture(
    monitor_index: int = 1,
    region: Optional[list[int]] = None,
    target_fps: int = 165,
) -> "ScreenCapture":
    if sys.platform != "win32":
        raise OSError("ValorantCV capture requires Windows 10/11.")
    from src.capture.win_capture import WinScreenCapture

    return WinScreenCapture(
        monitor_index=monitor_index,
        region=region,
        target_fps=target_fps,
    )


# Type alias for annotations
class ScreenCapture:
    """Protocol implemented by WinScreenCapture."""

    def grab(self) -> CaptureFrame:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
