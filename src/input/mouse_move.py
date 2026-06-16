"""Low-level mouse moves (Windows).

Games with raw input ignore SetCursorPos / HumanCursor (absolute). Use
``move_relative`` (mouse_event) for in-game aim assist.
"""

from __future__ import annotations

import ctypes

MOUSEEVENTF_MOVE = 1


def move_relative(dx: int, dy: int) -> None:
    """
    Relative pixel move via mouse_event — works with many FPS raw-input games.

    Unlike SetCursorPos, this injects movement deltas into the input stream.
    """
    ctypes.windll.user32.mouse_event(
        MOUSEEVENTF_MOVE, ctypes.c_long(int(dx)), ctypes.c_long(int(dy)), 0, 0
    )


def move_absolute(x: int, y: int) -> None:
    """Absolute move — works on desktop; most games ignore this."""
    if not ctypes.windll.user32.SetCursorPos(int(x), int(y)):
        raise OSError("SetCursorPos failed")
