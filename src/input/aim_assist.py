"""
Proximity-gated mouse assist for accessibility (console-style magnetic aim).

Only nudges the cursor when it is already near the target box. Does not snap from
across the screen. Pull point defaults to top-center of the chosen detection.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import List, Optional, Sequence, Tuple

from src.inference.detector import Detection
from src.input.cursor_pos import get_cursor_pos
from src.input.mouse_move import move_relative

logger = logging.getLogger(__name__)


def _aim_point(det: Detection, mode: str) -> Tuple[float, float]:
    cx = (det.x1 + det.x2) / 2.0
    if mode == "center":
        cy = (det.y1 + det.y2) / 2.0
    else:
        cy = float(det.y1)
    return cx, cy


def _distance_to_box(
    mx: float,
    my: float,
    det: Detection,
    origin_left: float,
    origin_top: float,
    scale_x: float,
    scale_y: float,
) -> float:
    """Screen-space distance from cursor to the nearest point on the box."""
    sx1 = det.x1 * scale_x + origin_left
    sy1 = det.y1 * scale_y + origin_top
    sx2 = det.x2 * scale_x + origin_left
    sy2 = det.y2 * scale_y + origin_top
    cx = min(max(mx, sx1), sx2)
    cy = min(max(my, sy1), sy2)
    return math.hypot(mx - cx, my - cy)


def _to_screen(
    x: float,
    y: float,
    origin_left: float,
    origin_top: float,
    scale_x: float,
    scale_y: float,
) -> Tuple[float, float]:
    return x * scale_x + origin_left, y * scale_y + origin_top


def _pick_centered_target(
    detections: Sequence[Detection],
    region_w: int,
    region_h: int,
    target_labels: Optional[Sequence[str]],
    max_center_distance_px: float,
    aim_mode: str,
    scale_x: float,
    scale_y: float,
) -> Optional[Detection]:
    cx = region_w / 2.0
    cy = region_h / 2.0
    best: Optional[Detection] = None
    best_dist = float("inf")

    for det in detections:
        if target_labels and det.label not in target_labels:
            continue
        ax, ay = _aim_point(det, aim_mode)
        dist = math.hypot((ax - cx) * scale_x, (ay - cy) * scale_y)
        if dist > max_center_distance_px:
            continue
        if dist < best_dist:
            best_dist = dist
            best = det

    return best


class AimAssist:
    """
    Subtle cursor pull toward the top-center (or center) of the most screen-centered
    detection. Uses HumanCursor when available. Assist runs only when the cursor is
    already near the detection box (not only the aim pixel).
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        origin_left: float = 0.0,
        origin_top: float = 0.0,
        region_w: int,
        region_h: int,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        proximity_px: float = 120.0,
        strength: float = 0.22,
        max_center_distance_px: float = 400.0,
        assist_hz: float = 18.0,
        move_duration_min: float = 0.04,
        move_duration_max: float = 0.14,
        target_labels: Optional[Sequence[str]] = None,
        aim_point: str = "top_center",
        steady: bool = False,
        debug: bool = False,
        move_method: str = "humancursor",
        game_mode: bool = False,
    ) -> None:
        self.enabled = enabled
        self._origin_left = origin_left
        self._origin_top = origin_top
        self._region_w = region_w
        self._region_h = region_h
        self._scale_x = max(1e-6, scale_x)
        self._scale_y = max(1e-6, scale_y)
        self.proximity_px = max(1.0, proximity_px)
        self.strength = max(0.01, min(1.0, strength))
        self.max_center_distance_px = max(1.0, max_center_distance_px)
        self._min_interval = 1.0 / max(1.0, assist_hz)
        self._move_duration_min = move_duration_min
        self._move_duration_max = move_duration_max
        self._target_labels = tuple(target_labels) if target_labels else None
        self._aim_mode = "center" if aim_point == "center" else "top_center"
        self._steady = steady
        self._debug = debug
        self._game_mode = game_mode
        if game_mode:
            self._move_method = "game"
        elif move_method in ("game", "relative", "sendinput"):
            self._move_method = "game"
        elif move_method == "humancursor":
            self._move_method = "humancursor"
        else:
            self._move_method = "humancursor"

        self._cursor = None
        self._busy = False
        self._lock = threading.Lock()
        self._last_assist_at = 0.0
        self._last_debug_at = 0.0
        self._debug_reason = ""

    def _ensure_cursor(self):
        if self._cursor is None:
            from humancursor import SystemCursor

            self._cursor = SystemCursor()

    def _debug_log(self, reason: str) -> None:
        if not self._debug:
            return
        now = time.perf_counter()
        if reason != self._debug_reason or now - self._last_debug_at >= 1.0:
            self._debug_reason = reason
            self._last_debug_at = now
            print(f"  [aim_assist] {reason}")

    def tick(self, detections: List[Detection]) -> None:
        if not self.enabled:
            return
        if not detections:
            self._debug_log("no detections")
            return

        now = time.perf_counter()
        if now - self._last_assist_at < self._min_interval:
            return

        with self._lock:
            if self._busy:
                return

        target = _pick_centered_target(
            detections,
            self._region_w,
            self._region_h,
            self._target_labels,
            self.max_center_distance_px,
            self._aim_mode,
            self._scale_x,
            self._scale_y,
        )
        if target is None:
            labels = sorted({d.label for d in detections})
            self._debug_log(
                f"no qualifying target (labels seen: {labels}; "
                f"filter={list(self._target_labels) if self._target_labels else 'all'})"
            )
            return

        ax, ay = _aim_point(target, self._aim_mode)
        screen_x, screen_y = _to_screen(
            ax, ay, self._origin_left, self._origin_top, self._scale_x, self._scale_y
        )

        if self._game_mode:
            # FPS titles lock the OS cursor; aim from capture center (crosshair).
            mx = self._origin_left + (self._region_w / 2.0) * self._scale_x
            my = self._origin_top + (self._region_h / 2.0) * self._scale_y
        else:
            mx, my = get_cursor_pos()
            mx, my = float(mx), float(my)
        box_dist = _distance_to_box(
            mx,
            my,
            target,
            self._origin_left,
            self._origin_top,
            self._scale_x,
            self._scale_y,
        )
        gap_x = screen_x - mx
        gap_y = screen_y - my
        aim_dist = math.hypot(gap_x, gap_y)

        if not self._game_mode and box_dist > self.proximity_px:
            self._debug_log(
                f"cursor too far from box ({box_dist:.0f}px > {self.proximity_px:.0f}px); "
                f"aim gap {aim_dist:.0f}px"
            )
            return
        if self._game_mode and aim_dist > self.proximity_px:
            self._debug_log(
                f"crosshair too far from aim ({aim_dist:.0f}px > {self.proximity_px:.0f}px)"
            )
            return
        if aim_dist < 1.0:
            self._debug_log("already on aim point")
            return

        dest_x = mx + gap_x * self.strength
        dest_y = my + gap_y * self.strength
        move_dist = math.hypot(dest_x - mx, dest_y - my)
        duration = self._duration_for_distance(move_dist)
        rel_dx = int(round(dest_x - mx))
        rel_dy = int(round(dest_y - my))
        if rel_dx == 0 and rel_dy == 0:
            return

        self._last_assist_at = now
        if self._debug:
            print(
                f"  [aim_assist] nudge d=({rel_dx},{rel_dy}) "
                f"box_dist={box_dist:.0f} aim_dist={aim_dist:.0f} "
                f"method={self._move_method}"
            )

        if self._move_method == "game":
            self._run_move_game(rel_dx, rel_dy)
            return

        with self._lock:
            if self._busy:
                return
            self._busy = True

        threading.Thread(
            target=self._run_move,
            args=([int(round(dest_x)), int(round(dest_y))], duration, rel_dx, rel_dy),
            daemon=True,
        ).start()

    def _run_move_game(self, rel_dx: int, rel_dy: int) -> None:
        try:
            move_relative(rel_dx, rel_dy)
        except Exception as exc:
            logger.warning("aim_assist game move failed: %s", exc)
            if self._debug:
                print(f"  [aim_assist] game move failed: {exc}")

    def _duration_for_distance(self, pixels: float) -> float:
        span = max(self.proximity_px * self.strength, 1.0)
        t = self._move_duration_min + (pixels / span) * (
            self._move_duration_max - self._move_duration_min
        )
        return max(self._move_duration_min, min(self._move_duration_max, t))

    def _run_move(
        self,
        point: list[int],
        duration: float,
        rel_dx: int,
        rel_dy: int,
    ) -> None:
        try:
            self._ensure_cursor()
            self._cursor.move_to(
                point,
                duration=duration,
                steady=self._steady,
            )
        except Exception as exc:
            logger.warning("aim_assist move failed: %s", exc)
            if self._debug:
                print(f"  [aim_assist] move failed: {exc}")
        finally:
            with self._lock:
                self._busy = False


def create_aim_assist(
    cfg: dict,
    *,
    monitor_index: int,
    region,
    region_w: int,
    region_h: int,
    enabled: Optional[bool] = None,
) -> Optional[AimAssist]:
    assist_cfg = cfg.get("aim_assist") or {}
    # ``enabled`` (e.g. from a CLI flag) overrides config when provided.
    is_enabled = assist_cfg.get("enabled", False) if enabled is None else enabled
    if not is_enabled:
        return None

    from src.input.monitor_rect import get_monitor_rect

    mon_left, mon_top, mon_w, mon_h = get_monitor_rect(monitor_index)
    reg_left = int(region[0]) if region and len(region) >= 1 else 0
    reg_top = int(region[1]) if region and len(region) >= 2 else 0

    origin_left = mon_left + reg_left
    origin_top = mon_top + reg_top
    scale_x = mon_w / max(1, region_w) if region is None else 1.0
    scale_y = mon_h / max(1, region_h) if region is None else 1.0

    labels = assist_cfg.get("target_labels")
    if labels is not None and not isinstance(labels, (list, tuple)):
        labels = None
    # Empty list = no filter (assist all detected classes)
    if labels is not None and len(labels) == 0:
        labels = None

    aim_point = str(assist_cfg.get("aim_point", "top_center"))

    return AimAssist(
        enabled=True,
        origin_left=origin_left,
        origin_top=origin_top,
        region_w=region_w,
        region_h=region_h,
        scale_x=scale_x,
        scale_y=scale_y,
        proximity_px=float(assist_cfg.get("proximity_px", 120)),
        strength=float(assist_cfg.get("strength", 0.22)),
        max_center_distance_px=float(assist_cfg.get("max_center_distance_px", 400)),
        assist_hz=float(assist_cfg.get("assist_hz", 18)),
        move_duration_min=float(assist_cfg.get("move_duration_min", 0.04)),
        move_duration_max=float(assist_cfg.get("move_duration_max", 0.14)),
        target_labels=labels,
        aim_point=aim_point,
        steady=bool(assist_cfg.get("steady", False)),
        debug=bool(assist_cfg.get("debug", False)),
        move_method=str(assist_cfg.get("move_method", "humancursor")),
        game_mode=bool(assist_cfg.get("game_mode", False)),
    )
