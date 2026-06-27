"""
Windows-only transparent overlay — topmost, click-through, per-class colors.
"""

from __future__ import annotations

import ctypes
import math
import sys
import threading
import time
import tkinter as tk
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

if sys.platform != "win32":
    raise ImportError("FrameSight overlay requires Windows")

from src.inference.detector import Detection

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
LWA_COLORKEY = 0x00000001
# Exclude the overlay from screen capture (Win10 2004+). The user still sees
# the overlay, but Desktop Duplication / dxcam does NOT — so the captured
# frames fed to the detector and magnifier are clean game pixels instead of
# the overlay's own black canvas (which otherwise causes a black self-capture).
WDA_EXCLUDEFROMCAPTURE = 0x00000011
VK_RBUTTON = 0x02


def _rmb_down() -> bool:
    """True while the right mouse button is held (global, focus-independent)."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)


def _apply_overlay_styles(hwnd: int, *, click_through: bool, topmost: bool) -> None:
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_NOACTIVATE
    if click_through:
        style |= WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    if topmost:
        style |= WS_EX_TOPMOST
    else:
        style &= ~WS_EX_TOPMOST
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_COLORKEY)
    # Keep the overlay out of the capture so it can't feed back into itself.
    try:
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    except Exception:  # noqa: BLE001 — older Windows: best-effort, ignore
        pass


# Visually distinct colors cycled per-detection index each frame.
_DET_PALETTE = [
    "#ff4444", "#44ff44", "#4488ff", "#ffdd00",
    "#ff44ff", "#00ffdd", "#ff8800", "#88ff00",
    "#ff0088", "#00aaff", "#aaff00", "#ff00aa",
]


def _target_point(det: Detection, target: str) -> Tuple[float, float]:
    tx = (det.x1 + det.x2) / 2
    if target == "top_center":
        ty = float(det.y1)
    else:
        ty = (det.y1 + det.y2) / 2
    return tx, ty


def _lerp_rgb(
    near: Tuple[int, int, int],
    far: Tuple[int, int, int],
    t: float,
) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(n + (f - n) * t) for n, f in zip(near, far))


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


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
        click_through: bool = True,
        topmost: bool = True,
        window_title: str = "FrameSight Overlay",
        refresh_hz: int = 165,
        show_fps: bool = True,
        show_center_lines: bool = True,
        center_line_width: int = 1,
        center_line_target: str = "box_center",
        proximity_flash: bool = True,
        proximity_radius_px: int = 150,
        proximity_border_width: int = 12,
        proximity_flash_hz: float = 4.0,
        magnifier: bool = False,
        magnifier_radius: int = 80,
        magnifier_zoom: float = 1.5,
        magnifier_hold_rmb: bool = True,
        distance_colors: bool = False,
        color_near: Tuple[int, int, int] = (255, 64, 64),
        color_far: Tuple[int, int, int] = (0, 255, 128),
        distance_max_px: Optional[float] = None,
        box_offset_x: int = 0,
        box_offset_y: int = 0,
    ) -> None:
        self._frame_ms = 1000.0 / max(1, refresh_hz)
        self._box_offset_x = int(box_offset_x)
        self._box_offset_y = int(box_offset_y)
        self._provider: Optional[Callable[[], List[Detection]]] = None
        self._stats_provider: Optional[Callable[[], object]] = None
        self._show_fps = show_fps
        self._render_fps = 0.0
        self._fps_count = 0
        self._fps_t0 = time.perf_counter()
        self._box_thickness = max(1, box_thickness)
        self._show_labels = show_labels
        self._show_confidence = show_confidence
        self._show_center_lines = show_center_lines
        self._center_line_width = max(1, center_line_width)
        self._center_line_target = center_line_target
        self._proximity_flash = proximity_flash
        self._proximity_radius_px = max(1, proximity_radius_px)
        self._proximity_border_width = max(1, proximity_border_width)
        self._proximity_flash_hz = max(0.1, proximity_flash_hz)
        self._width = int(width)
        self._height = int(height)
        self._magnifier = magnifier
        self._magnifier_radius = max(8, magnifier_radius)
        self._magnifier_zoom = max(1.0, magnifier_zoom)
        self._magnifier_hold_rmb = magnifier_hold_rmb
        self._frame_provider: Optional[Callable[[], object]] = None
        self._mag_photo = None  # holds a ref so the PhotoImage isn't GC'd
        # The heavy crop/resize/mask runs on its own thread; the paint thread
        # only blits the latest prepared image (a PIL.Image) so box rendering
        # is never blocked by the magnifier.
        self._mag_image = None
        self._mag_lock = threading.Lock()
        self._mag_stop = threading.Event()
        self._mag_thread: Optional[threading.Thread] = None
        self._distance_colors = distance_colors
        self._color_near = color_near
        self._color_far = color_far
        self._distance_max_px = distance_max_px
        self._class_colors = class_colors or {
            "body": (255, 64, 64),
            "head": (255, 200, 0),
        }
        self._default_rgb = (0, 255, 128)
        # Precompute hex strings once so the fixed-color path is a dict lookup
        # per box instead of an int->hex format call every frame.
        self._default_hex = _rgb_to_hex(self._default_rgb)
        self._class_hex = {k: _rgb_to_hex(v) for k, v in self._class_colors.items()}
        self._detections: List[Detection] = []
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._click_through = click_through
        self._topmost = topmost
        self._window_title = window_title

        self._thread = threading.Thread(
            target=self._run_ui,
            args=(width, height, left, top),
            daemon=True,
        )

    def _class_rgb(self, label: str) -> Tuple[int, int, int]:
        return self._class_colors.get(label, self._default_rgb)

    def _magnifier_worker(self) -> None:
        """Background loop: prepare the zoomed circular inset off the paint thread.

        Does all the cv2 crop/resize and the circular alpha mask, then stashes a
        ready-to-blit PIL image. Runs as fast as fresh frames arrive (paced to the
        refresh budget) so it stays realtime without touching the box pipeline.
        """
        try:
            import cv2
            import numpy as np
            from PIL import Image
        except Exception:  # noqa: BLE001 — Pillow/cv2 missing: disable magnifier
            return

        R = self._magnifier_radius
        diameter = 2 * R
        src_r = max(1, int(round(R / self._magnifier_zoom)))
        # Circular alpha mask is constant — build it once.
        yy, xx = np.ogrid[:diameter, :diameter]
        alpha = np.where((xx - R) ** 2 + (yy - R) ** 2 <= R * R, 255, 0).astype(np.uint8)
        # Frame pixel under the screen center (region offset removed).
        fcx0 = int(self._width / 2 - self._box_offset_x)
        fcy0 = int(self._height / 2 - self._box_offset_y)
        interval = self._frame_ms / 1000.0

        while not self._mag_stop.is_set():
            t0 = time.perf_counter()
            # Only do the heavy crop/resize while the magnifier is actually shown.
            active = not self._magnifier_hold_rmb or _rmb_down()
            provider = self._frame_provider
            frame = provider() if (active and provider is not None) else None
            if frame is not None:
                fh, fw = frame.shape[:2]
                if 0 <= fcx0 < fw and 0 <= fcy0 < fh:
                    x0, x1 = max(0, fcx0 - src_r), min(fw, fcx0 + src_r)
                    y0, y1 = max(0, fcy0 - src_r), min(fh, fcy0 + src_r)
                    crop = frame[y0:y1, x0:x1]
                    if crop.size:
                        mag = cv2.resize(
                            crop, (diameter, diameter), interpolation=cv2.INTER_LINEAR
                        )
                        rgb = np.ascontiguousarray(mag[:, :, ::-1])  # BGR -> RGB
                        img = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
                        with self._mag_lock:
                            self._mag_image = img
            # Pace to the refresh budget; this thread never busy-spins.
            self._mag_stop.wait(max(0.0, interval - (time.perf_counter() - t0)))

    def _draw_magnifier(self, canvas) -> None:
        """Blit the most recently prepared inset (cheap; no image processing)."""
        with self._mag_lock:
            img = self._mag_image
        if img is None:
            return
        from PIL import ImageTk

        # Reuse the Tk image buffer (paste) instead of reallocating each frame.
        if self._mag_photo is None or (
            self._mag_photo.width(),
            self._mag_photo.height(),
        ) != img.size:
            self._mag_photo = ImageTk.PhotoImage(img)
        else:
            self._mag_photo.paste(img)
        R = self._magnifier_radius
        cx, cy = self._width / 2, self._height / 2
        canvas.create_image(cx, cy, image=self._mag_photo)
        canvas.create_oval(cx - R, cy - R, cx + R, cy + R, outline="#00ffff", width=2)

    def _fps_text(self, n_targets: int) -> str:
        cap = inf = 0.0
        if self._stats_provider is not None:
            stats = self._stats_provider()
            cap = float(getattr(stats, "capture_fps", 0.0) or 0.0)
            inf = float(getattr(stats, "inference_fps", 0.0) or 0.0)
        return (
            f"overlay {self._render_fps:5.1f} | capture {cap:5.1f} | "
            f"infer {inf:5.1f} fps | targets {n_targets}"
        )

    def _color_for_detection(
        self,
        det: Detection,
        cx: float,
        cy: float,
        max_dist: float,
    ) -> str:
        if not self._distance_colors:
            return self._class_hex.get(det.label, self._default_hex)

        tx, ty = _target_point(det, self._center_line_target)
        dist = math.hypot(tx - cx, ty - cy)
        t = dist / max_dist if max_dist > 0 else 1.0
        return _rgb_to_hex(_lerp_rgb(self._color_near, self._color_far, t))

    def _run_ui(self, width: int, height: int, left: int, top: int) -> None:
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.title(self._window_title)
        if self._topmost:
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
        _apply_overlay_styles(
            hwnd,
            click_through=self._click_through,
            topmost=self._topmost,
        )
        root.deiconify()
        self._ready.set()

        def redraw() -> None:
            frame_start = time.perf_counter()
            provider = self._provider
            if provider is not None:
                # Extrapolate to *this* paint moment so boxes track at the
                # overlay's full refresh rate, not the slower inference rate.
                dets = provider()
            else:
                with self._lock:
                    dets = list(self._detections)
            # Detections are in capture-region pixels; shift them into full-screen
            # space so a center-region inference can draw on a full-screen overlay
            # (keeps the HUD in the true screen corner).
            ox, oy = self._box_offset_x, self._box_offset_y
            if ox or oy:
                dets = [
                    replace(d, x1=d.x1 + ox, y1=d.y1 + oy, x2=d.x2 + ox, y2=d.y2 + oy)
                    for d in dets
                ]
            canvas.delete("all")
            cx, cy = width / 2, height / 2
            max_dist = self._distance_max_px
            if max_dist is None or max_dist <= 0:
                max_dist = math.hypot(cx, cy)

            # Assign each detection a unique palette color by index.
            det_colors = [
                _DET_PALETTE[i % len(_DET_PALETTE)] for i in range(len(dets))
            ]

            if self._show_center_lines:
                # Dashed lines from screen center to each corner of every box.
                for det, color in zip(dets, det_colors):
                    for corner in (
                        (det.x1, det.y1),
                        (det.x2, det.y1),
                        (det.x2, det.y2),
                        (det.x1, det.y2),
                    ):
                        canvas.create_line(
                            cx, cy,
                            corner[0], corner[1],
                            fill=color,
                            width=self._center_line_width,
                            dash=(6, 12),
                            arrow="last",
                            arrowshape=(8, 10, 3),
                        )

            if self._proximity_flash and dets:
                # Flash a red screen border while a box is near the center.
                nearest = min(
                    math.hypot((d.x1 + d.x2) / 2 - cx, (d.y1 + d.y2) / 2 - cy)
                    for d in dets
                )
                # Blink on/off at the configured rate (on for the first half of
                # each period) so the border pulses rather than sitting solid.
                blink_on = (frame_start * self._proximity_flash_hz) % 1.0 < 0.5
                if nearest <= self._proximity_radius_px and blink_on:
                    bw = self._proximity_border_width
                    canvas.create_rectangle(
                        bw / 2,
                        bw / 2,
                        width - bw / 2,
                        height - bw / 2,
                        outline="#ff0000",
                        width=bw,
                    )

            for det, color in zip(dets, det_colors):
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
            if self._magnifier and (not self._magnifier_hold_rmb or _rmb_down()):
                self._draw_magnifier(canvas)

            # Measure the overlay's own paint rate (refresh once per ~0.5s).
            self._fps_count += 1
            since = frame_start - self._fps_t0
            if since >= 0.5:
                self._render_fps = self._fps_count / since
                self._fps_count = 0
                self._fps_t0 = frame_start

            if self._show_fps:
                canvas.create_text(
                    8,
                    6,
                    text=self._fps_text(len(dets)),
                    fill="#00ff88",
                    anchor="nw",
                    font=("Consolas", 11, "bold"),
                )

            # Pace to the target refresh: draw, then wait out the rest of the
            # frame budget. Painting faster than the monitor just burns CPU.
            elapsed_ms = (time.perf_counter() - frame_start) * 1000.0
            delay = max(1, int(round(self._frame_ms - elapsed_ms)))
            root.after(delay, redraw)

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
        if self._magnifier:
            self._mag_thread = threading.Thread(
                target=self._magnifier_worker, daemon=True
            )
            self._mag_thread.start()

    def update_detections(self, detections: List[Detection]) -> None:
        with self._lock:
            self._detections = detections

    def set_detection_provider(
        self, provider: Optional[Callable[[], List[Detection]]]
    ) -> None:
        """Pull boxes from ``provider`` at paint time instead of using pushed ones."""
        self._provider = provider

    def set_stats_provider(self, provider: Optional[Callable[[], object]]) -> None:
        """Source of live pipeline stats (capture/inference FPS) for the HUD."""
        self._stats_provider = provider

    def set_frame_provider(self, provider: Optional[Callable[[], object]]) -> None:
        """Source of the latest captured BGR frame (for the magnifier)."""
        self._frame_provider = provider

    def close(self) -> None:
        self._mag_stop.set()
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
        refresh_hz: int = 165,
        box_thickness: int = 2,
        show_labels: bool = True,
        show_confidence: bool = True,
        default_color: Tuple[int, int, int] = (0, 255, 128),
        class_colors: Dict[str, Tuple[int, int, int]] | None = None,
        click_through: bool = True,
        topmost: bool = True,
        window_title: str = "FrameSight Overlay",
        show_fps: bool = True,
        show_center_lines: bool = True,
        center_line_width: int = 1,
        center_line_target: str = "box_center",
        proximity_flash: bool = True,
        proximity_radius_px: int = 150,
        proximity_border_width: int = 12,
        proximity_flash_hz: float = 4.0,
        magnifier: bool = False,
        magnifier_radius: int = 80,
        magnifier_zoom: float = 1.5,
        magnifier_hold_rmb: bool = True,
        distance_colors: bool = False,
        color_near: Tuple[int, int, int] = (255, 64, 64),
        color_far: Tuple[int, int, int] = (0, 255, 128),
        distance_max_px: Optional[float] = None,
        box_offset_x: int = 0,
        box_offset_y: int = 0,
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
            click_through=click_through,
            topmost=topmost,
            window_title=window_title,
            refresh_hz=refresh_hz,
            show_fps=show_fps,
            show_center_lines=show_center_lines,
            center_line_width=center_line_width,
            center_line_target=center_line_target,
            proximity_flash=proximity_flash,
            proximity_radius_px=proximity_radius_px,
            proximity_border_width=proximity_border_width,
            proximity_flash_hz=proximity_flash_hz,
            magnifier=magnifier,
            magnifier_radius=magnifier_radius,
            magnifier_zoom=magnifier_zoom,
            magnifier_hold_rmb=magnifier_hold_rmb,
            distance_colors=distance_colors,
            color_near=color_near,
            color_far=color_far,
            distance_max_px=distance_max_px,
            box_offset_x=box_offset_x,
            box_offset_y=box_offset_y,
        )

    def show(self) -> None:
        self._overlay.show()

    def update_detections(self, detections: List[Detection]) -> None:
        self._overlay.update_detections(detections)

    def set_detection_provider(
        self, provider: Optional[Callable[[], List[Detection]]]
    ) -> None:
        self._overlay.set_detection_provider(provider)

    def set_stats_provider(self, provider: Optional[Callable[[], object]]) -> None:
        self._overlay.set_stats_provider(provider)

    def set_frame_provider(self, provider: Optional[Callable[[], object]]) -> None:
        self._overlay.set_frame_provider(provider)

    def close(self) -> None:
        self._overlay.close()
