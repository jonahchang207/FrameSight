"""Constant-velocity forward model — extrapolates boxes to render time to hide latency.

Detection always trails reality: inference runs far slower than the overlay/capture
loop, and EMA smoothing adds more lag. This model tracks each target's velocity from
its (already smoothed) center motion and predicts where the box *will be* at the moment
the overlay draws it, compensating inference + render + smoothing latency.

Two entry points, called from different threads:
  * ``update(detections, now)``  — inference thread, when fresh detections arrive.
  * ``predict(now)``             — overlay thread, at the high-frequency tick.
The pipeline guards both with its detection lock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from src.inference.detector import Detection


def _iou_xyxy(
    ax1: float, ay1: float, ax2: float, ay2: float,
    bx1: float, by1: float, bx2: float, by2: float,
) -> float:
    x1 = max(ax1, bx1)
    y1 = max(ay1, by1)
    x2 = min(ax2, bx2)
    y2 = min(ay2, by2)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


@dataclass
class _Track:
    cx: float          # last measured center x (px)
    cy: float          # last measured center y (px)
    w: float
    h: float
    vx: float          # velocity (px/s)
    vy: float
    confidence: float
    class_id: int
    label: str
    last_t: float      # timestamp of last update (perf_counter seconds)
    id: int = 0        # stable identity, carried onto the predicted Detection
    misses: int = 0

    def extrapolate(self, dt: float) -> tuple[float, float]:
        return self.cx + self.vx * dt, self.cy + self.vy * dt


def _to_center(det: Detection) -> tuple[float, float, float, float]:
    cx = (det.x1 + det.x2) / 2.0
    cy = (det.y1 + det.y2) / 2.0
    w = float(det.x2 - det.x1)
    h = float(det.y2 - det.y1)
    return cx, cy, w, h


class ForwardPredictor:
    """Per-target constant-velocity predictor.

    Designed to sit *after* :class:`BoxSmoother`: it consumes already-stabilized
    boxes (so velocity is estimated from clean centers) and extrapolates them.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        lead_time_ms: float = 40.0,
        velocity_alpha: float = 0.5,
        position_alpha: float = 1.0,
        match_iou: float = 0.2,
        match_dist_frac: float = 0.6,
        max_age: int = 6,
        max_speed_px: float = 4000.0,
        min_speed_px: float = 0.0,
        max_extrapolation_ms: float = 120.0,
    ) -> None:
        self.enabled = enabled
        self.lead_time = max(0.0, lead_time_ms) / 1000.0
        self.velocity_alpha = max(0.0, min(1.0, velocity_alpha))
        self.position_alpha = max(0.0, min(1.0, position_alpha))
        self.match_iou = match_iou
        self.match_dist_frac = max(0.0, match_dist_frac)
        self.max_age = max(0, max_age)
        self.max_speed_px = max(0.0, max_speed_px)
        self.min_speed_px = max(0.0, min_speed_px)
        self.max_extrapolation = max(0.0, max_extrapolation_ms) / 1000.0
        self._tracks: List[_Track] = []
        self._next_id = 0

    def update(self, detections: List[Detection], now: float) -> None:
        """Fold a fresh batch of detections in and refresh velocity estimates."""
        if not self.enabled:
            return

        dets = [(_to_center(d), d) for d in detections]

        # Match each existing track (extrapolated to ``now``) against new detections.
        pairs: list[tuple[float, int, int]] = []
        for ti, track in enumerate(self._tracks):
            dt = self._clamp_dt(now - track.last_t)
            px, py = track.extrapolate(dt)
            tx1, ty1 = px - track.w / 2.0, py - track.h / 2.0
            tx2, ty2 = px + track.w / 2.0, py + track.h / 2.0
            for di, ((cx, cy, w, h), det) in enumerate(dets):
                if det.class_id != track.class_id:
                    continue
                score = self._match_score(
                    tx1, ty1, tx2, ty2, px, py, track.w, track.h, cx, cy, w, h
                )
                if score is not None:
                    pairs.append((score, ti, di))

        pairs.sort(key=lambda p: p[0], reverse=True)
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for _ov, ti, di in pairs:
            if ti in matched_tracks or di in matched_dets:
                continue
            matched_tracks.add(ti)
            matched_dets.add(di)
            (cx, cy, w, h), det = dets[di]
            self._refresh_track(self._tracks[ti], cx, cy, w, h, det, now)

        for ti, track in enumerate(self._tracks):
            if ti not in matched_tracks:
                track.misses += 1

        for di, ((cx, cy, w, h), det) in enumerate(dets):
            if di in matched_dets:
                continue
            tid = self._next_id
            self._next_id += 1
            self._tracks.append(
                _Track(
                    cx=cx, cy=cy, w=w, h=h, vx=0.0, vy=0.0,
                    confidence=det.confidence, class_id=det.class_id,
                    label=det.label, last_t=now, id=tid,
                )
            )

        self._tracks = [t for t in self._tracks if t.misses <= self.max_age]

    def predict(self, now: float) -> List[Detection]:
        """Return boxes extrapolated to ``now`` + lead time."""
        if not self.enabled:
            return []

        out: List[Detection] = []
        for track in self._tracks:
            dt = self._clamp_dt((now - track.last_t) + self.lead_time)
            cx, cy = track.extrapolate(dt)
            x1 = int(round(cx - track.w / 2.0))
            y1 = int(round(cy - track.h / 2.0))
            x2 = int(round(cx + track.w / 2.0))
            y2 = int(round(cy + track.h / 2.0))
            out.append(
                Detection(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    confidence=track.confidence,
                    class_id=track.class_id,
                    label=track.label,
                    track_id=track.id,
                )
            )
        return out

    def _match_score(
        self,
        tx1: float, ty1: float, tx2: float, ty2: float,
        pcx: float, pcy: float, tw: float, th: float,
        cx: float, cy: float, w: float, h: float,
    ) -> float | None:
        """Association score: IoU when boxes overlap, else a center-distance fallback.

        Pure IoU matching breaks on fast motion (boxes separate frame-to-frame),
        which spawns duplicate tracks and leaves the old one coasting as a trail.
        The distance fallback keeps a fast-moving target on its own track.
        IoU matches always outrank distance matches (scores 1..2 vs 0..1).
        """
        overlap = _iou_xyxy(
            tx1, ty1, tx2, ty2,
            cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0,
        )
        if overlap >= self.match_iou:
            return 1.0 + overlap
        if self.match_dist_frac > 0.0:
            dist = math.hypot(cx - pcx, cy - pcy)
            reach = self.match_dist_frac * max(1.0, (tw + th + w + h) / 4.0)
            if dist <= reach:
                return 1.0 - dist / reach
        return None

    def _refresh_track(
        self, track: _Track, cx: float, cy: float, w: float, h: float,
        det: Detection, now: float,
    ) -> None:
        dt = now - track.last_t
        if dt > 1e-4:
            meas_vx = (cx - track.cx) / dt
            meas_vy = (cy - track.cy) / dt
            a = self.velocity_alpha
            track.vx = a * meas_vx + (1.0 - a) * track.vx
            track.vy = a * meas_vy + (1.0 - a) * track.vy
            self._clamp_speed(track)
            # Deadzone: treat sub-threshold motion as still, so inference jitter
            # on a near-stationary target doesn't get extrapolated into wobble.
            if self.min_speed_px > 0.0 and math.hypot(track.vx, track.vy) < self.min_speed_px:
                track.vx = 0.0
                track.vy = 0.0

        pa = self.position_alpha
        track.cx = pa * cx + (1.0 - pa) * track.cx
        track.cy = pa * cy + (1.0 - pa) * track.cy
        track.w = pa * w + (1.0 - pa) * track.w
        track.h = pa * h + (1.0 - pa) * track.h
        track.confidence = det.confidence
        track.label = det.label
        track.last_t = now
        track.misses = 0

    def _clamp_speed(self, track: _Track) -> None:
        if self.max_speed_px <= 0.0:
            return
        speed = math.hypot(track.vx, track.vy)
        if speed > self.max_speed_px:
            scale = self.max_speed_px / speed
            track.vx *= scale
            track.vy *= scale

    def _clamp_dt(self, dt: float) -> float:
        if dt < 0.0:
            return 0.0
        if dt > self.max_extrapolation:
            return self.max_extrapolation
        return dt
