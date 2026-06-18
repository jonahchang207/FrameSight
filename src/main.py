"""
FrameSight live detector — Windows only.

Usage (from repo root on Windows):
  python -m src.main
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

if sys.platform != "win32":
    print("FrameSight requires Windows 10/11 for capture and overlay.")
    sys.exit(1)

from src.capture.screen_capture import create_capture
from src.config_loader import ROOT, load_config
from src.inference.box_smoother import BoxSmoother
from src.inference.detector_factory import create_detector
from src.inference.forward_model import ForwardPredictor
from src.overlay.overlay_window import OverlayApp
from src.pipeline import FrameSightPipeline
from src.timing import high_resolution_timer, precise_sleep


def _tuple_rgb(value) -> tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return int(value[0]), int(value[1]), int(value[2])
    return 0, 255, 128


def _resolve_weights(cfg: dict) -> Path:
    weights = Path(cfg["model"]["weights"])
    if not weights.is_absolute():
        weights = ROOT / weights
    if weights.exists():
        return weights
    return Path(cfg["model"].get("base_checkpoint", "yolo11n.pt"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="framesight")
    parser.parse_args()

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

    weights = _resolve_weights(cfg)
    # detect_head: false skips the 'head' class entirely (never decoded or drawn).
    disabled_classes = set() if model_cfg.get("detect_head", True) else {"head"}
    detector = create_detector(
        weights=weights,
        imgsz=model_cfg.get("imgsz", 640),
        conf=model_cfg.get("conf", 0.35),
        iou=model_cfg.get("iou", 0.45),
        device_requested=model_cfg.get("device", "auto"),
        max_det=int(model_cfg.get("max_det", 300)),
        agnostic_nms=bool(model_cfg.get("agnostic_nms", False)),
        half=bool(model_cfg.get("half", True)),
        io_binding=bool(model_cfg.get("io_binding", False)),
        disabled_classes=disabled_classes,
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
        from src.input.monitor_rect import get_monitor_rect

        mon_left, mon_top, mon_w, mon_h = get_monitor_rect(cap_cfg.get("monitor_index", 1))
        reg_left = int(region[0]) if region and len(region) >= 1 else 0
        reg_top = int(region[1]) if region and len(region) >= 2 else 0
        # Overlay spans the whole monitor so the stats HUD sits in the true
        # screen corner; boxes (in region-local coords) get shifted by the
        # region offset, even though inference only runs on the center region.
        overlay = OverlayApp(
            width=mon_w,
            height=mon_h,
            left=mon_left,
            top=mon_top,
            box_offset_x=reg_left,
            box_offset_y=reg_top,
            refresh_hz=cap_cfg.get("target_fps", 165),
            box_thickness=overlay_cfg.get("box_thickness", 2),
            show_labels=overlay_cfg.get("show_labels", True),
            show_confidence=overlay_cfg.get("show_confidence", True),
            default_color=default,
            class_colors=class_colors,
            click_through=overlay_cfg.get("click_through", True),
            topmost=overlay_cfg.get("topmost", True),
            window_title=str(overlay_cfg.get("window_title", "FrameSight Overlay")),
            show_fps=bool(overlay_cfg.get("show_fps", True)),
            show_center_lines=overlay_cfg.get("show_center_lines", True),
            center_line_width=int(overlay_cfg.get("center_line_width", 1)),
            center_line_target=str(overlay_cfg.get("center_line_target", "box_center")),
            proximity_flash=bool(overlay_cfg.get("proximity_flash", True)),
            proximity_radius_px=int(overlay_cfg.get("proximity_radius_px", 150)),
            proximity_border_width=int(overlay_cfg.get("proximity_border_width", 12)),
            proximity_flash_hz=float(overlay_cfg.get("proximity_flash_hz", 4.0)),
            magnifier=bool(overlay_cfg.get("magnifier", False)),
            magnifier_radius=int(overlay_cfg.get("magnifier_radius", 120)),
            magnifier_zoom=float(overlay_cfg.get("magnifier_zoom", 2.0)),
            magnifier_hold_rmb=bool(overlay_cfg.get("magnifier_hold_rmb", True)),
            distance_colors=bool(overlay_cfg.get("distance_colors", False)),
            color_near=_tuple_rgb(overlay_cfg.get("color_near", [255, 64, 64])),
            color_far=_tuple_rgb(overlay_cfg.get("color_far", [0, 255, 128])),
            distance_max_px=overlay_cfg.get("distance_max_px"),
        )
        overlay.show()

    smooth_cfg = cfg.get("smoothing", {})
    smoother = None
    if smooth_cfg.get("enabled", True):
        smoother = BoxSmoother(
            enabled=True,
            alpha=float(smooth_cfg.get("alpha", 0.4)),
            match_iou=float(smooth_cfg.get("match_iou", 0.3)),
            match_dist_frac=float(smooth_cfg.get("match_dist_frac", 0.6)),
            max_age=int(smooth_cfg.get("max_age", 3)),
        )

    fwd_cfg = cfg.get("forward_model", {})
    predictor = None
    if fwd_cfg.get("enabled", False):
        predictor = ForwardPredictor(
            enabled=True,
            lead_time_ms=float(fwd_cfg.get("lead_time_ms", 40.0)),
            velocity_alpha=float(fwd_cfg.get("velocity_alpha", 0.5)),
            position_alpha=float(fwd_cfg.get("position_alpha", 1.0)),
            match_iou=float(fwd_cfg.get("match_iou", 0.2)),
            match_dist_frac=float(fwd_cfg.get("match_dist_frac", 0.6)),
            max_age=int(fwd_cfg.get("max_age", 6)),
            max_speed_px=float(fwd_cfg.get("max_speed_px", 4000.0)),
            min_speed_px=float(fwd_cfg.get("min_speed_px", 0.0)),
            max_extrapolation_ms=float(fwd_cfg.get("max_extrapolation_ms", 120.0)),
        )

    pipeline = FrameSightPipeline(
        capture=capture,
        detector=detector,
        overlay=overlay,
        target_capture_fps=cap_cfg.get("target_fps", 165),
        smoother=smoother,
        predictor=predictor,
    )
    pipeline.start()

    stop = False

    def _on_sig(*_args):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)

    print("FrameSight running (Windows). Ctrl+C to quit.")
    print(f"  Weights: {weights}")
    if predictor is not None:
        print(
            f"  Forward model: ON (lead {predictor.lead_time * 1000:.0f}ms, "
            f"vel_alpha {predictor.velocity_alpha:.2f})"
        )
    print(f"  Region: {w}x{h}")

    target_fps = cap_cfg.get("target_fps", 165)
    try:
        # Raise the OS timer resolution to ~1ms; without this every sub-frame
        # time.sleep rounds up to ~15ms and the whole pipeline stalls near 64 Hz.
        with high_resolution_timer(1):
            while not stop:
                pipeline.tick_overlay()
                stats = pipeline.stats
                if stats.frames_inferred and stats.frames_inferred % 60 == 0:
                    print(
                        f"  capture {stats.capture_fps:.1f} fps | "
                        f"inference {stats.inference_fps:.1f} fps",
                        end="\r",
                    )
                precise_sleep(1.0 / target_fps)
    finally:
        pipeline.stop()
        capture.close()
        if overlay:
            overlay.close()

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
