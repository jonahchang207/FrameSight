"""Windows cursor position (screen coordinates)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def get_cursor_pos() -> tuple[int, int]:
    pt = POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        raise OSError("GetCursorPos failed")
    return int(pt.x), int(pt.y)
