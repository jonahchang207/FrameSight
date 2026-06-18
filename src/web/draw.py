"""Draw detections onto a BGR frame using the live render settings."""

from __future__ import annotations

from typing import Any, Dict, Iterable

import cv2
import numpy as np

from src.inference.detector import Detection


def _bgr(rgb: Iterable[int]) -> tuple[int, int, int]:
    r, g, b = (int(c) for c in list(rgb)[:3])
    return b, g, r


def draw_detections(
    frame: np.ndarray,
    detections: Iterable[Detection],
    settings_snapshot: Dict[str, Any],
) -> np.ndarray:
    """Render boxes in place. Honours per-class colour/visibility + conf filter."""
    s = settings_snapshot
    conf_min = float(s.get("conf", 0.0))
    thickness = int(s.get("thickness", 2))
    show_labels = bool(s.get("show_labels", True))
    show_conf = bool(s.get("show_confidence", True))
    classes = s.get("classes", {})
    default_color = s.get("default_color", [0, 255, 128])

    h, w = frame.shape[:2]
    center = (w // 2, h // 2)

    for det in detections:
        if det.confidence < conf_min:
            continue
        style = classes.get(det.label)
        if style is not None and not style.get("enabled", True):
            continue
        color = _bgr(style["color"] if style else default_color)
        corners = (
            (det.x1, det.y1),
            (det.x2, det.y1),
            (det.x2, det.y2),
            (det.x1, det.y2),
        )
        for corner in corners:
            cv2.line(frame, center, corner, color, thickness, cv2.LINE_AA)
        cv2.rectangle(frame, (det.x1, det.y1), (det.x2, det.y2), color, thickness)

        if not show_labels:
            continue
        text = det.label
        if show_conf:
            text = f"{det.label} {det.confidence:.2f}"
        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = max(det.y1, th + 4)
        cv2.rectangle(
            frame,
            (det.x1, ty - th - baseline - 2),
            (det.x1 + tw + 4, ty),
            color,
            -1,
        )
        cv2.putText(
            frame,
            text,
            (det.x1 + 2, ty - baseline),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return frame
