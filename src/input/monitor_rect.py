"""Monitor geometry in screen coordinates (Windows)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import List, Tuple

Rect = Tuple[int, int, int, int]  # left, top, width, height


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def list_monitor_rects() -> List[Rect]:
    """All monitors in enumeration order (matches dxcam output_idx 0, 1, …)."""
    rects: List[Rect] = []

    def _callback(hmon, _hdc, _lprect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            rects.append((int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)))
        return 1

    cb = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.POINTER(wintypes.RECT),
        ctypes.c_double,
    )
    ctypes.windll.user32.EnumDisplayMonitors(0, 0, cb(_callback), 0)
    return rects


def get_monitor_rect(monitor_index: int) -> Rect:
    """1-based monitor index (same as config ``capture.monitor_index``)."""
    rects = list_monitor_rects()
    if not rects:
        return 0, 0, 0, 0
    idx = max(0, min(len(rects) - 1, monitor_index - 1))
    return rects[idx]
