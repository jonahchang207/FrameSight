"""Export an annotated copy of a video file (offline, exact boxes).

Unlike the live dashboard (which draws the latest detection on each displayed
frame for smoothness), the exporter runs inference on *every* frame, so every
output frame has boxes computed from that exact frame. Files only — a stream has
no defined end to export.

CLI:
    python -m src.web.export --source in.mp4 --out out.mp4
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import cv2

from src.config_loader import load_config
from src.web.detector_build import build_detector, class_names
from src.web.draw import draw_detections
from src.web.render_settings import RenderSettings
from src.web.video_source import resolve_source


def default_output_path(source: str) -> Path:
    p = Path(source)
    return p.with_name(f"{p.stem}_annotated.mp4")


def export_video(
    source: str,
    out_path: str,
    detector,
    settings_snapshot: Dict[str, Any],
    progress_cb: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> int:
    """Write an annotated video. Returns the number of frames written."""
    cap = cv2.VideoCapture(resolve_source(source))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source: {source}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        fps = fps if fps and 1.0 <= fps <= 240.0 else 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
        if not writer.isOpened():
            raise RuntimeError(f"Could not open writer for: {out_path}")

        written = 0
        try:
            while True:
                if should_stop is not None and should_stop():
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                detections = detector.predict(frame)
                draw_detections(frame, detections, settings_snapshot)
                writer.write(frame)
                written += 1
                if progress_cb is not None:
                    progress_cb(written, total)
        finally:
            writer.release()
        return written
    finally:
        cap.release()


class ExportManager:
    """Runs one export at a time in a background thread, for the dashboard."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._status: Dict[str, Any] = {
            "running": False,
            "done": False,
            "written": 0,
            "total": 0,
            "progress": 0.0,
            "out": None,
            "error": None,
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self, source: str, settings_snapshot: Dict[str, Any], out: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self._status["running"]:
                return dict(self._status)
            out_path = out or str(default_output_path(source))
            self._stop.clear()
            self._status = {
                "running": True,
                "done": False,
                "written": 0,
                "total": 0,
                "progress": 0.0,
                "out": out_path,
                "error": None,
            }
            self._thread = threading.Thread(
                target=self._run, args=(source, out_path, settings_snapshot), daemon=True
            )
            self._thread.start()
            return dict(self._status)

    def cancel(self) -> None:
        self._stop.set()

    def _run(self, source: str, out_path: str, settings_snapshot: Dict[str, Any]) -> None:
        def progress(written: int, total: int) -> None:
            with self._lock:
                self._status["written"] = written
                self._status["total"] = total
                self._status["progress"] = round(written / total, 4) if total else 0.0

        try:
            # A separate detector keeps export off the live inference thread.
            conf = float(settings_snapshot.get("conf", 0.25))
            detector = build_detector(self._cfg, conf=min(conf, 0.10))
            export_video(
                source,
                out_path,
                detector,
                settings_snapshot,
                progress_cb=progress,
                should_stop=self._stop.is_set,
            )
            with self._lock:
                self._status["running"] = False
                self._status["done"] = True
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._status["running"] = False
                self._status["error"] = f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(prog="framesight-export")
    parser.add_argument("--source", required=True, help="Input video file.")
    parser.add_argument("--out", default=None, help="Output path (default: <name>_annotated.mp4).")
    args = parser.parse_args()

    cfg = load_config()
    out = args.out or str(default_output_path(args.source))
    conf = float(cfg.get("model", {}).get("conf", 0.35))
    detector = build_detector(cfg, conf=min(conf, 0.10))

    names = class_names(detector, cfg)
    overlay_cfg = cfg.get("overlay", {})
    colors_cfg = overlay_cfg.get("colors", {})
    class_colors = {
        k: v for k, v in colors_cfg.items() if k != "default" and isinstance(v, (list, tuple))
    }
    settings = RenderSettings(
        class_names=names,
        default_color=colors_cfg.get("default", [0, 255, 128]),
        class_colors=class_colors,
        conf=conf,
        thickness=int(overlay_cfg.get("box_thickness", 2)),
        show_labels=bool(overlay_cfg.get("show_labels", True)),
        show_confidence=bool(overlay_cfg.get("show_confidence", True)),
    )

    print(f"Exporting {args.source} -> {out}")
    n = 0

    def progress(written: int, total: int) -> None:
        nonlocal n
        n = written
        if total and written % 30 == 0:
            print(f"  {written}/{total} ({written / total:.0%})", end="\r")

    export_video(args.source, out, detector, settings.snapshot(), progress_cb=progress)
    print(f"\nDone: {n} frames -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
