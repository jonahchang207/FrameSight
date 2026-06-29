"""Ultralytics YOLO wrapper tuned for speed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set

import numpy as np
from ultralytics import YOLO


@dataclass(frozen=True)
class Detection:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_id: int
    label: str
    track_id: int = -1  # stable per-target id from the tracker; -1 = untracked


class YoloDetector:
    def __init__(
        self,
        weights: str | Path,
        imgsz: int | tuple[int, int] | list[int] = 640,
        conf: float = 0.35,
        iou: float = 0.45,
        device: str = "",
        max_det: int = 300,
        agnostic_nms: bool = False,
        disabled_classes: Iterable[str] | None = None,
    ) -> None:
        path = Path(weights)
        if not path.exists():
            # Allow training from base checkpoint before custom weights exist
            weights = str(weights)
        task = "detect" if path.suffix.lower() == ".onnx" else None
        self._model = YOLO(str(weights), task=task) if task else YOLO(str(weights))
        self._imgsz = imgsz
        self._conf = conf
        self._iou = iou
        self._device = device or None
        self._max_det = max_det
        self._agnostic_nms = agnostic_nms
        self._disabled_classes: Set[str] = set(disabled_classes or ())
        self._names: dict[int, str] = {}

    @property
    def names(self) -> dict[int, str]:
        return dict(self._names)

    def predict(self, bgr: np.ndarray) -> List[Detection]:
        results = self._model.predict(
            source=bgr,
            imgsz=self._imgsz,
            conf=self._conf,
            iou=self._iou,
            max_det=self._max_det,
            agnostic_nms=self._agnostic_nms,
            device=self._device,
            verbose=False,
            stream=False,
        )
        if not results:
            return []

        result = results[0]
        self._names = result.names or {}
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        cls_ids = boxes.cls.cpu().numpy().astype(int)

        out: List[Detection] = []
        for (x1, y1, x2, y2), c, cid in zip(xyxy, confs, cls_ids):
            label = self._names.get(int(cid), str(int(cid)))
            if label in self._disabled_classes:
                continue
            out.append(
                Detection(
                    x1=int(x1),
                    y1=int(y1),
                    x2=int(x2),
                    y2=int(y2),
                    confidence=float(c),
                    class_id=int(cid),
                    label=label,
                )
            )
        return out
