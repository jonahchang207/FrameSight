"""
Windows-only transparent overlay — topmost, click-through, per-class colors.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import tkinter as tk
from typing import Dict, List, Tuple

if sys.platform != "win32":
    raise ImportError("ValorantCV overlay requires Windows")

from src.inference.detector import Detection

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
LWA_COLORKEY = 0x00000001


def _make_click_through(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd,
        GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
    )
    user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_COLORKEY)


class Win32Overlay:
    def __init__(
        self,
        width: int,
        height: int,
        left: int = 0,
        top: int = 0,
        box_thickness: int = 2,
        show_labels: bool = True,
        show_confidence: bool = True,
        class_colors: Dict[str, Tuple[int, int, int]] | None = None,
    ) -> None:
        self._box_thickness = max(1, box_thickness)
        self._show_labels = show_labels
        self._show_confidence = show_confidence
        self._class_colors = class_colors or {
            "enemy": (255, 64, 64),
            "enemy_head": (255, 200, 0),
        }
        self._default_color = "#00ff80"
        self._detections: List[Detection] = []
        self._lock = threading.Lock()
        self._ready = threading.Event()

        self._thread = threading.Thread(
            target=self._run_ui,
            args=(width, height, left, top),
            daemon=True,
        )

    def _rgb_hex(self, label: str) -> str:
        rgb = self._class_colors.get(label, (0, 255, 128))
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    def _run_ui(self, width: int, height: int, left: int, top: int) -> None:
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="black")
        root.geometry(f"{width}x{height}+{left}+{top}")
        root.attributes("-transparentcolor", "black")

        canvas = tk.Canvas(
            root,
            width=width,
            height=height,
            bg="black",
            highlightthickness=0,
            bd=0,
        )
        canvas.pack()

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        _make_click_through(hwnd)
        root.deiconify()
        self._ready.set()

        def redraw() -> None:
            with self._lock:
                dets = list(self._detections)
            canvas.delete("all")
            for det in dets:
                color = self._rgb_hex(det.label)
                canvas.create_rectangle(
                    det.x1,
                    det.y1,
                    det.x2,
                    det.y2,
                    outline=color,
                    width=self._box_thickness,
                )
                if self._show_labels or self._show_confidence:
                    parts = []
                    if self._show_labels:
                        parts.append(det.label)
                    if self._show_confidence:
                        parts.append(f"{det.confidence:.2f}")
                    canvas.create_text(
                        det.x1 + 2,
                        max(10, det.y1 - 6),
                        text=" ".join(parts),
                        fill=color,
                        anchor="sw",
                        font=("Consolas", 10, "bold"),
                    )
            root.after(1, redraw)

        root.after(1, redraw)

        def on_close() -> None:
            try:
                root.destroy()
            except tk.TclError:
                pass

        self._root = root
        self._on_close = on_close
        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()

    def show(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def update_detections(self, detections: List[Detection]) -> None:
        with self._lock:
            self._detections = detections

    def close(self) -> None:
        if hasattr(self, "_root"):
            try:
                self._root.after(0, self._on_close)
            except Exception:
                pass


class OverlayApp:
    def __init__(
        self,
        width: int,
        height: int,
        left: int = 0,
        top: int = 0,
        refresh_hz: int = 165,  # noqa: ARG002
        box_thickness: int = 2,
        show_labels: bool = True,
        show_confidence: bool = True,
        default_color: Tuple[int, int, int] = (0, 255, 128),
        class_colors: Dict[str, Tuple[int, int, int]] | None = None,
    ) -> None:
        colors = dict(class_colors or {})
        if "default" not in colors:
            colors["_default"] = default_color
        self._overlay = Win32Overlay(
            width=width,
            height=height,
            left=left,
            top=top,
            box_thickness=box_thickness,
            show_labels=show_labels,
            show_confidence=show_confidence,
            class_colors={k: v for k, v in colors.items() if not k.startswith("_")},
        )

    def show(self) -> None:
        self._overlay.show()

    def update_detections(self, detections: List[Detection]) -> None:
        self._overlay.update_detections(detections)

    def close(self) -> None:
        self._overlay.close()
