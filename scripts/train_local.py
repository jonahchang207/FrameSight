#!/usr/bin/env python3
"""Train YOLO on the local fn.v1i.yolov8 dataset (Windows)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config_loader import load_config  # noqa: E402


def _prepare_data_yaml(data_yaml: Path, class_names: list[str]) -> None:
    dataset_dir = data_yaml.parent
    with data_yaml.open() as f:
        cfg = yaml.safe_load(f) or {}
    cfg["path"] = str(dataset_dir.resolve())
    cfg["train"] = "train/images"
    cfg["val"] = "valid/images"
    cfg["nc"] = len(class_names)
    cfg["names"] = class_names
    with data_yaml.open("w") as f:
        yaml.dump(cfg, f, default_flow_style=False)


def main() -> int:
    cfg = load_config()
    data_yaml = Path(cfg["dataset"].get("data_yaml", "fn.v1i.yolov8/data.yaml"))
    if not data_yaml.is_absolute():
        data_yaml = ROOT / data_yaml

    if not data_yaml.exists():
        raise SystemExit(
            f"Dataset not found: {data_yaml}\n"
            "Place fn.v1i.yolov8/ in the project root (see README)."
        )

    train_img = data_yaml.parent / "train" / "images"
    if not train_img.is_dir() or not any(train_img.iterdir()):
        raise SystemExit(f"No training images in {train_img}")

    class_names = cfg.get("training", {}).get("names", ["enemy", "enemy_head"])
    _prepare_data_yaml(data_yaml, class_names)

    train_cfg = cfg.get("training", {})
    from ultralytics import YOLO

    device = cfg["model"].get("device", "0")
    print(f"Training on device={device}  dataset={data_yaml.parent}")

    model = YOLO(cfg["model"].get("base_checkpoint", "yolo11n.pt"))
    results = model.train(
        data=str(data_yaml),
        epochs=train_cfg.get("epochs", 100),
        imgsz=cfg["model"].get("imgsz", 640),
        batch=train_cfg.get("batch", 16),
        patience=train_cfg.get("patience", 20),
        device=device,
        project=str(ROOT / "runs"),
        name="valorantcv",
        exist_ok=True,
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    out = ROOT / "weights" / "best.pt"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, out)
    print(f"\nDone.\n  Weights: {out}\n  Run overlay:  python -m src.main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
