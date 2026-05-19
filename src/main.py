"""
ValorantCV live detector — Windows only.

Usage (from repo root on Windows):
  python -m src.main
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    print("ValorantCV requires Windows 10/11 for capture and overlay.")
    sys.exit(1)

from src.capture.screen_capture import create_capture
from src.config_loader import ROOT, load_config
from src.inference.detector import YoloDetector
from src.overlay.overlay_window import OverlayApp
from src.pipeline import ValorantCVPipeline


def _resolve_weights(cfg: dict) -> Path:
    weights = Path(cfg["model"]["weights"])
    if not weights.is_absolute():
        weights = ROOT / weights
    if weights.exists():
        return weights
    return Path(cfg["model"].get("base_checkpoint", "yolo11n.pt"))


def _region_offset(region) -> tuple[int, int]:
    if region and len(region) >= 2:
        return int(region[0]), int(region[1])
    return 0, 0


def main() -> int:
    cfg = load_config()
    cap_cfg = cfg["capture"]
    model_cfg = cfg["model"]
    overlay_cfg = cfg.get("overlay", {})
    region = cap_cfg.get("region")

    capture = create_capture(
        monitor_index=cap_cfg.get("monitor_index", 1),
        region=region,
        target_fps=cap_cfg.get("target_fps", 165),
    )

    probe = capture.grab()
    h, w = probe.bgr.shape[:2]
    left, top = _region_offset(region)

    weights = _resolve_weights(cfg)
    detector = YoloDetector(
        weights=weights,
        imgsz=model_cfg.get("imgsz", 640),
        conf=model_cfg.get("conf", 0.35),
        iou=model_cfg.get("iou", 0.45),
        device=model_cfg.get("device", "0"),
    )

    overlay = None
    if overlay_cfg.get("enabled", True):
        colors_cfg = overlay_cfg.get("colors", {})
        class_colors = {
            k: tuple(v)
            for k, v in colors_cfg.items()
            if k != "default" and isinstance(v, (list, tuple))
        }
        default = tuple(colors_cfg.get("default", [0, 255, 128]))
        overlay = OverlayApp(
            width=w,
            height=h,
            left=left,
            top=top,
            refresh_hz=cap_cfg.get("target_fps", 165),
            box_thickness=overlay_cfg.get("box_thickness", 2),
            show_labels=overlay_cfg.get("show_labels", True),
            show_confidence=overlay_cfg.get("show_confidence", True),
            default_color=default,
            class_colors=class_colors,
        )
        overlay.show()

    pipeline = ValorantCVPipeline(
        capture=capture,
        detector=detector,
        overlay=overlay,
        target_capture_fps=cap_cfg.get("target_fps", 165),
    )
    pipeline.start()

    stop = False

    def _on_sig(*_args):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)

    print("ValorantCV running (Windows). Ctrl+C to quit.")
    print(f"  Weights: {weights}")
    print(f"  Region: {w}x{h} at ({left}, {top})")

    try:
        while not stop:
            pipeline.tick_overlay()
            stats = pipeline.stats
            if stats.frames_inferred and stats.frames_inferred % 60 == 0:
                print(
                    f"  capture {stats.capture_fps:.1f} fps | "
                    f"inference {stats.inference_fps:.1f} fps",
                    end="\r",
                )
            time.sleep(1.0 / cap_cfg.get("target_fps", 165))
    finally:
        pipeline.stop()
        capture.close()
        if overlay:
            overlay.close()

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
