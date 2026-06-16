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
from src.device_utils import detect_accelerator, resolve_device  # noqa: E402


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

    device_requested = cfg["model"].get("device", "auto")
    accel = detect_accelerator()
    device = resolve_device(device_requested)

    if accel.gpu_names:
        print(f"GPUs: {', '.join(accel.gpu_names)}")
    print(f"Accelerator: {accel.message}")

    if device == "cpu" and accel.backend == "dml":
        print(
            "  Training uses CPU (Ultralytics does not support AMD/Intel GPU training).\n"
            "  After training, the overlay will use your GPU via ONNX DirectML."
        )
    elif device == "cpu" and str(device_requested).strip().lower() not in ("", "cpu", "auto"):
        print(
            f"WARNING: GPU {device_requested!r} not available; using cpu.\n"
            "  NVIDIA: install CUDA PyTorch — https://pytorch.org/get-started/locally/"
        )

    batch = train_cfg.get("batch", 16)
    if device == "cpu" and batch > 8:
        print(f"  Reducing batch {batch} -> 8 for CPU training (edit training.batch in config).")
        batch = 8

    print(f"Training on device={device}  dataset={data_yaml.parent}")

    # Train square even when inference uses a rectangular imgsz ([h, w]): YOLO is
    # fully convolutional and runs at any size at inference regardless of the
    # training size, and Ultralytics training expects a single int.
    imgsz_cfg = cfg["model"].get("imgsz", 640)
    train_imgsz = max(imgsz_cfg) if isinstance(imgsz_cfg, (list, tuple)) else imgsz_cfg

    model = YOLO(cfg["model"].get("base_checkpoint", "yolo11n.pt"))
    results = model.train(
        data=str(data_yaml),
        epochs=train_cfg.get("epochs", 100),
        imgsz=train_imgsz,
        batch=batch,
        patience=train_cfg.get("patience", 20),
        device=device,
        project=str(ROOT / "runs"),
        name="framesight",
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
