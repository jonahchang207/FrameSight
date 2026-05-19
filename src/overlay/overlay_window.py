"""Windows-only overlay entrypoint."""

from __future__ import annotations

import sys

if sys.platform != "win32":
    raise ImportError(
        "FrameSight overlay is Windows-only. Run inference on Windows with requirements.txt."
    )

from src.overlay.win32_overlay import OverlayApp

__all__ = ["OverlayApp"]
