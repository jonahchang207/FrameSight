"""High-resolution timing helpers (Windows multimedia timer).

Windows' default scheduler granularity is ~15.6 ms, so ``time.sleep(1/165)``
(~6 ms) actually sleeps ~15 ms — silently capping any sleep-paced loop near
64 Hz regardless of the configured target FPS. Raising the timer resolution
with ``timeBeginPeriod(1)`` makes sub-frame sleeps accurate.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager


@contextmanager
def high_resolution_timer(period_ms: int = 1):
    """Raise the OS timer resolution so ``time.sleep`` is accurate to ~1 ms.

    The effect is process-global, so setting it once (e.g. around the main
    loop) also benefits the capture and overlay threads. No-op off Windows.
    """
    if sys.platform != "win32":
        yield
        return

    import ctypes

    winmm = ctypes.windll.winmm
    period = max(1, int(period_ms))
    winmm.timeBeginPeriod(period)
    try:
        yield
    finally:
        winmm.timeEndPeriod(period)


def precise_sleep(seconds: float) -> None:
    """Frame-accurate sleep: coarse ``time.sleep`` then a short spin for the tail.

    Requires :func:`high_resolution_timer` to be active for the coarse part to
    be tight. Spinning only the final ~1 ms keeps CPU cost negligible while
    avoiding the oversleep that wrecks high-refresh pacing.
    """
    if seconds <= 0:
        return
    end = time.perf_counter() + seconds
    coarse = seconds - 0.0011
    if coarse > 0:
        time.sleep(coarse)
    while time.perf_counter() < end:
        pass
