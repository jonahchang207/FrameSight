"""Shared detector construction for the web annotator and the exporter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.config_loader import ROOT
from src.inference.detector_factory import create_detector


def resolve_weights(cfg: Dict[str, Any]) -> Path:
    weights = Path(cfg["model"]["weights"])
    if not weights.is_absolute():
        weights = ROOT / weights
    if weights.exists():
        return weights
    return Path(cfg["model"].get("base_checkpoint", "yolo11n.pt"))


def build_detector(cfg: Dict[str, Any], conf: float):
    """Create a detector from config at the given (display) confidence floor."""
    model_cfg = cfg["model"]
    return create_detector(
        weights=resolve_weights(cfg),
        imgsz=model_cfg.get("imgsz", 640),
        conf=conf,
        iou=float(model_cfg.get("iou", 0.45)),
        device_requested=model_cfg.get("device", "auto"),
        max_det=int(model_cfg.get("max_det", 300)),
        agnostic_nms=bool(model_cfg.get("agnostic_nms", False)),
        half=bool(model_cfg.get("half", True)),
        io_binding=bool(model_cfg.get("io_binding", False)),
    )


def class_names(detector, cfg: Dict[str, Any]) -> Dict[int, str]:
    names = dict(getattr(detector, "names", {}) or {})
    if names:
        return names
    # ONNX models may not expose names until first inference; fall back to the
    # training names in config so the dashboard can list classes immediately.
    training = cfg.get("training", {}).get("names")
    if isinstance(training, list) and training:
        return {i: str(n) for i, n in enumerate(training)}
    return {0: "object"}
