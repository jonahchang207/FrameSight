"""IoU tracking + EMA smoothing to stabilize overlay boxes between inference frames."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import List

from src.inference.detector import Detection


def _center(d: Detection) -> tuple[float, float]:
    return (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0


def _iou(a: Detection, b: Detection) -> float:
    x1 = max(a.x1, b.x1)
    y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2)
    y2 = min(a.y2, b.y2)
    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0, a.x2 - a.x1) * max(0, a.y2 - a.y1)
    area_b = max(0, b.x2 - b.x1) * max(0, b.y2 - b.y1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


@dataclass
class _Track:
    detection: Detection  # smoothed box that gets drawn
    raw: Detection        # last raw detection — matched against, free of EMA lag
    id: int = 0           # stable identity, carried onto the drawn Detection
    misses: int = 0


class BoxSmoother:
    """Match detections across frames and apply EMA on box coordinates."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        alpha: float = 0.4,
        match_iou: float = 0.3,
        match_dist_frac: float = 0.6,
        max_age: int = 3,
    ) -> None:
        self.enabled = enabled
        self.alpha = max(0.0, min(1.0, alpha))
        self.match_iou = match_iou
        self.match_dist_frac = max(0.0, match_dist_frac)
        self.max_age = max(0, max_age)
        self._tracks: List[_Track] = []
        self._next_id = 0

    def update(self, detections: List[Detection]) -> List[Detection]:
        if not self.enabled:
            return detections

        matched_track_idx: set[int] = set()
        matched_det_idx: set[int] = set()
        pairs: list[tuple[float, int, int]] = []

        for ti, track in enumerate(self._tracks):
            for di, det in enumerate(detections):
                if det.class_id != track.raw.class_id:
                    continue
                score = self._match_score(track.raw, det)
                if score is not None:
                    pairs.append((score, ti, di))

        pairs.sort(key=lambda x: x[0], reverse=True)
        for _iou_val, ti, di in pairs:
            if ti in matched_track_idx or di in matched_det_idx:
                continue
            matched_track_idx.add(ti)
            matched_det_idx.add(di)
            raw = detections[di]
            tid = self._tracks[ti].id
            prev = self._tracks[ti].detection
            self._tracks[ti].detection = _smooth_detection(prev, raw, self.alpha, tid)
            self._tracks[ti].raw = raw
            self._tracks[ti].misses = 0

        for ti, track in enumerate(self._tracks):
            if ti not in matched_track_idx:
                track.misses += 1

        for di, det in enumerate(detections):
            if di not in matched_det_idx:
                tid = self._next_id
                self._next_id += 1
                self._tracks.append(
                    _Track(detection=replace(det, track_id=tid), raw=det, id=tid)
                )

        self._tracks = [t for t in self._tracks if t.misses <= self.max_age]
        return [t.detection for t in self._tracks]

    def _match_score(self, track: Detection, det: Detection) -> float | None:
        """IoU score, with a center-distance fallback for fast motion.

        Without the fallback a fast-moving box stops overlapping its previous
        frame, the match fails, and a duplicate track is spawned while the old
        one coasts — the visible "trail". IoU matches outrank distance matches.
        """
        overlap = _iou(track, det)
        if overlap >= self.match_iou:
            return 1.0 + overlap
        if self.match_dist_frac > 0.0:
            tcx, tcy = _center(track)
            dcx, dcy = _center(det)
            dist = math.hypot(dcx - tcx, dcy - tcy)
            tw = track.x2 - track.x1
            th = track.y2 - track.y1
            dw = det.x2 - det.x1
            dh = det.y2 - det.y1
            reach = self.match_dist_frac * max(1.0, (tw + th + dw + dh) / 4.0)
            if dist <= reach:
                return 1.0 - dist / reach
        return None


def _smooth_detection(
    prev: Detection, raw: Detection, alpha: float, track_id: int
) -> Detection:
    a = alpha

    def blend_int(new: int, old: int) -> int:
        return int(round(a * new + (1.0 - a) * old))

    return Detection(
        x1=blend_int(raw.x1, prev.x1),
        y1=blend_int(raw.y1, prev.y1),
        x2=blend_int(raw.x2, prev.x2),
        y2=blend_int(raw.y2, prev.y2),
        confidence=a * raw.confidence + (1.0 - a) * prev.confidence,
        class_id=raw.class_id,
        label=raw.label,
        track_id=track_id,
    )
