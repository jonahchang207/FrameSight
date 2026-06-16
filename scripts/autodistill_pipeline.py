#!/usr/bin/env python3
"""
Valorant / gameplay footage → frames → AutoDistill labels → YOLO dataset.

1. Put one or more videos in data/videos/
2. Run:  python scripts/autodistill_pipeline.py
3. Upload data/autodistill/dataset.zip to Google Colab (see colab/train_framesight.ipynb)
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

try:
    import cv2
    import yaml
    from tqdm import tqdm
except ImportError as exc:
    raise SystemExit(
        "Missing labeling dependencies (wrong Python?).\n\n"
        "  .\\.venv\\Scripts\\Activate.ps1\n"
        "  pip install -r requirements-autodistill.txt\n"
        "  python scripts\\autodistill_pipeline.py --skip-extract --zip\n\n"
        "Or one line:\n"
        "  .\\.venv\\Scripts\\python.exe scripts\\autodistill_pipeline.py --skip-extract --zip"
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


def load_autodistill_config(path: Path | None = None) -> dict:
    cfg_path = path or ROOT / "config" / "autodistill.yaml"
    with cfg_path.open() as f:
        return yaml.safe_load(f) or {}


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p


def extract_frames(
    videos_dir: Path,
    frames_dir: Path,
    *,
    every_frame: bool,
    extract_fps: float,
    frame_size: list[int] | None,
    extensions: list[str],
    skip_existing: bool,
) -> int:
    frames_dir.mkdir(parents=True, exist_ok=True)
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    videos = sorted(
        p for p in videos_dir.iterdir() if p.is_file() and p.suffix.lower() in exts
    )
    if not videos:
        raise SystemExit(
            f"No videos in {videos_dir}\n"
            f"Supported: {', '.join(sorted(exts))}"
        )

    total = 0
    for vid_idx, video_path in enumerate(videos):
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            print(f"  skip (unreadable): {video_path.name}")
            continue

        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        reported_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        if every_frame or extract_fps <= 0:
            step = 1
            mode = "every frame"
            expect = reported_total if reported_total > 0 else None
        else:
            step = max(1, int(round(native_fps / extract_fps)))
            mode = f"{extract_fps:g} fps (1 every {step} frames @ {native_fps:.1f} native fps)"
            expect = (reported_total // step) if reported_total > 0 else None

        prefix = f"{video_path.stem}_{vid_idx:03d}"
        frame_i = 0
        saved = 0

        print(
            f"  {video_path.name}: {mode}"
            + (f", ~{expect} frames" if expect else "")
            + (f", {reported_total} frames in file" if reported_total > 0 else "")
        )

        with tqdm(
            total=expect,
            desc=f"Extract {video_path.name}",
            unit="frame",
            leave=True,
        ) as bar:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_i % step == 0:
                    if frame_size and len(frame_size) == 2:
                        frame = cv2.resize(
                            frame,
                            (int(frame_size[0]), int(frame_size[1])),
                            interpolation=cv2.INTER_AREA,
                        )
                    out_name = f"{prefix}_f{frame_i:06d}.jpg"
                    out_path = frames_dir / out_name
                    if not skip_existing or not out_path.exists():
                        cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
                        saved += 1
                        total += 1
                    bar.update(1)
                frame_i += 1
        cap.release()
        print(f"  -> saved {saved} images (read {frame_i} frames from decoder)")

    print(f"Extracted {total} frames -> {frames_dir}")
    return total


def _build_ontology(cfg: dict) -> dict:
    raw = cfg.get("labeling", {}).get("ontology", {})
    if not raw:
        return {
            "valorant player": "enemy",
            "person": "enemy",
            "human head": "enemy_head",
        }
    return {str(k): str(v) for k, v in raw.items()}


def _ensure_labeling_dependencies() -> None:
    """Block known-broken transformers builds (from failed OWLv2 pip git install)."""
    try:
        import transformers
    except ImportError as exc:
        raise SystemExit(
            "transformers not installed. Run:\n"
            "  pip install -r requirements-autodistill.txt\n"
            "  .\\scripts\\fix_autodistill_env.ps1"
        ) from exc

    version = getattr(transformers, "__version__", "")
    if "dev" in version or version.startswith("5."):
        raise SystemExit(
            f"Broken transformers ({version}) — OWLv2 likely installed a dev build.\n"
            "Fix:\n"
            "  .\\scripts\\fix_autodistill_env.ps1\n"
            "Then set labeling.base_model: owlvit in config/autodistill.yaml"
        )


def _load_base_model(cfg: dict):
    from autodistill.detection import CaptionOntology

    _ensure_labeling_dependencies()

    labeling = cfg.get("labeling", {})
    ontology = CaptionOntology(_build_ontology(cfg))
    box_th = float(labeling.get("box_threshold", 0.2))
    text_th = float(labeling.get("text_threshold", 0.2))
    model_name = str(labeling.get("base_model", "owlvit")).lower()

    if model_name == "owlv2":
        try:
            from autodistill_owlv2 import OWLv2
        except ImportError as exc:
            raise SystemExit(
                "owlv2 not installed. Prefer owlvit, or: pip install autodistill-owlv2\n"
                "Warning: owlv2 may break transformers on Windows."
            ) from exc
        print("  Using OWLv2 (ontology only — no box_threshold on this model)")
        return OWLv2(ontology=ontology)

    from autodistill_owl_vit import OWLViT

    try:
        return OWLViT(
            ontology=ontology,
            box_threshold=box_th,
            text_threshold=text_th,
        )
    except TypeError:
        print("  Using OWL-ViT (default thresholds)")
        return OWLViT(ontology=ontology)


def label_frames(frames_dir: Path, dataset_dir: Path, cfg: dict) -> None:
    images = list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png"))
    if not images:
        raise SystemExit(f"No images in {frames_dir} — run frame extraction first.")

    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    labeling_cfg = cfg.get("labeling", {})
    ontology_map = _build_ontology(cfg)
    print(
        f"Labeling {len(images)} images with AutoDistill "
        f"({labeling_cfg.get('base_model', 'owlv2')})..."
    )
    print("  Target classes:")
    print("    enemy      = player BODY (full character / torso)")
    print("    enemy_head = HEAD only")
    for caption, cls_name in ontology_map.items():
        print(f"    prompt: \"{caption}\" -> {cls_name}")

    model = _load_base_model(cfg)
    print(
        "\n  When the progress bar hits 100%, AutoDistill still:\n"
        "    1) Writes all YOLO label files\n"
        "    2) Splits into train/ and valid/ (moves ~100k files)\n"
        "  This can take 30-120+ minutes with NO new progress bar.\n"
        "  Leave it running if disk/CPU activity is visible in Task Manager.\n"
    )
    model.label(
        input_folder=str(frames_dir),
        output_folder=str(dataset_dir),
        extension=".jpg",
    )
    print("\n  AutoDistill labeling + YOLO export finished.")


def _ensure_split_dirs(dataset_dir: Path) -> None:
    for split in ("train", "valid"):
        (dataset_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (dataset_dir / split / "labels").mkdir(parents=True, exist_ok=True)


def split_train_valid(dataset_dir: Path, val_fraction: float, seed: int) -> None:
    """Move a random subset from train → valid if autodistill only created train/."""
    train_img = dataset_dir / "train" / "images"
    train_lbl = dataset_dir / "train" / "labels"
    valid_img = dataset_dir / "valid" / "images"
    valid_lbl = dataset_dir / "valid" / "labels"

    if not train_img.is_dir():
        raise SystemExit(f"Missing {train_img} after labeling")

    _ensure_split_dirs(dataset_dir)
    if any(valid_img.iterdir()):
        print("  valid/ already has images — skip split")
        return
    pairs = []
    for img in train_img.glob("*.*"):
        if img.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        lbl = train_lbl / f"{img.stem}.txt"
        if lbl.exists():
            pairs.append((img, lbl))

    if not pairs:
        raise SystemExit(f"No label files in {train_lbl}")

    rng = random.Random(seed)
    rng.shuffle(pairs)
    n_val = max(1, int(len(pairs) * val_fraction))
    val_set = set(pairs[:n_val])

    for img, lbl in val_set:
        shutil.move(str(img), str(valid_img / img.name))
        shutil.move(str(lbl), str(valid_lbl / lbl.name))

    print(
        f"Split: train={len(pairs) - len(val_set)}  valid={len(val_set)}"
    )


def _print_label_class_counts(dataset_dir: Path, class_names: list[str]) -> None:
    """Summarize how many boxes were written per class (0=enemy body, 1=head)."""
    counts = {name: 0 for name in class_names}
    for split in ("train", "valid"):
        lbl_dir = dataset_dir / split / "labels"
        if not lbl_dir.is_dir():
            continue
        for lbl in lbl_dir.glob("*.txt"):
            for line in lbl.read_text().strip().splitlines():
                parts = line.split()
                if not parts:
                    continue
                cid = int(parts[0])
                if 0 <= cid < len(class_names):
                    counts[class_names[cid]] += 1
    print("  Label counts:")
    for name in class_names:
        print(f"    {name}: {counts[name]}")
    if counts.get("enemy", 0) == 0:
        print("  WARNING: no enemy (body) labels — try lowering box_threshold or edit ontology")
    if counts.get("enemy_head", 0) == 0:
        print("  WARNING: no enemy_head labels — strengthen head prompts in autodistill.yaml")


def write_data_yaml(dataset_dir: Path, class_names: list[str]) -> Path:
    data_yaml = dataset_dir / "data.yaml"
    cfg = {
        "path": str(dataset_dir.resolve()),
        "train": "train/images",
        "val": "valid/images",
        "nc": len(class_names),
        "names": class_names,
    }
    with data_yaml.open("w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
    return data_yaml


def publish_dataset(dataset_dir: Path, publish_dir: Path) -> None:
    if publish_dir.exists():
        shutil.rmtree(publish_dir)
    shutil.copytree(dataset_dir, publish_dir)
    print(f"Published dataset -> {publish_dir}")


def _dataset_ready(dataset_dir: Path) -> bool:
    train_img = dataset_dir / "train" / "images"
    return train_img.is_dir() and any(train_img.glob("*.jpg"))


def finish_dataset(
    dataset_dir: Path,
    class_names: list[str],
    *,
    skip_split: bool,
    val_fraction: float,
    seed: int,
    publish_dir: Path | None,
    do_publish: bool,
    do_zip: bool,
) -> None:
    """Zip / yaml after labeling — or resume if train/ already exists."""
    if not dataset_dir.is_dir():
        raise SystemExit(f"No dataset folder: {dataset_dir}")

    if not _dataset_ready(dataset_dir):
        images_dir = dataset_dir / "images"
        ann_dir = dataset_dir / "annotations"
        if images_dir.is_dir() and ann_dir.is_dir():
            print("Found images/ + annotations/ — running AutoDistill train/valid split...")
            from autodistill.helpers import split_data

            split_data(str(dataset_dir))
        else:
            raise SystemExit(
                f"Dataset not ready under {dataset_dir}\n"
                "Need train/images/ (finished labeling) or images/ + annotations/"
            )

    if not skip_split and not any((dataset_dir / "valid" / "images").glob("*.jpg")):
        print("Re-splitting train -> valid (FrameSight ratio)...")
        split_train_valid(dataset_dir, val_fraction, seed)

    print("\n=== Write data.yaml ===")
    yaml_path = write_data_yaml(dataset_dir, class_names)
    print(f"  {yaml_path}")
    _print_label_class_counts(dataset_dir, class_names)

    if do_publish and publish_dir is not None:
        publish_dataset(dataset_dir, publish_dir)

    if do_zip:
        zip_out = dataset_dir.parent / "framesight_dataset.zip"
        print("\n=== Creating zip for Colab (large — may take several minutes) ===")
        package_zip(dataset_dir, zip_out)


def package_zip(dataset_dir: Path, zip_path: Path) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    base = zip_path.with_suffix("")
    if base.exists():
        shutil.rmtree(base)
    shutil.copytree(dataset_dir, base)
    archive = shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=base.parent, base_dir=base.name)
    shutil.rmtree(base)
    print(f"Colab upload zip: {archive}")
    return Path(archive)


def main() -> int:
    parser = argparse.ArgumentParser(description="FrameSight AutoDistill pipeline")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "autodistill.yaml")
    parser.add_argument("--skip-extract", action="store_true", help="Use existing frames/")
    parser.add_argument("--skip-label", action="store_true", help="Only extract frames")
    parser.add_argument(
        "--finish-only",
        action="store_true",
        help="Skip labeling — zip/split existing dataset (after 100%% bar finished)",
    )
    parser.add_argument("--skip-split", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Copy dataset to fn.v1i.yolov8/")
    parser.add_argument("--zip", action="store_true", help="Create dataset zip for Colab")
    parser.add_argument("--videos-dir", type=Path, default=None)
    args = parser.parse_args()

    cfg = load_autodistill_config(args.config)
    paths = cfg.get("paths", {})
    videos_dir = args.videos_dir or _resolve(paths.get("videos_dir", "data/videos"))
    frames_dir = _resolve(paths.get("frames_dir", "data/autodistill/frames"))
    dataset_dir = _resolve(paths.get("dataset_dir", "data/autodistill/dataset"))
    publish_dir = _resolve(paths.get("publish_dir", "fn.v1i.yolov8"))

    video_cfg = cfg.get("video", {})
    class_names = cfg.get("classes", ["enemy", "enemy_head"])

    videos_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_extract:
        print(f"\n=== 1/4 Extract frames from {videos_dir} ===")
        extract_frames(
            videos_dir,
            frames_dir,
            every_frame=bool(video_cfg.get("every_frame", True)),
            extract_fps=float(video_cfg.get("extract_fps", 30)),
            frame_size=video_cfg.get("frame_size"),
            extensions=video_cfg.get("extensions", list(VIDEO_EXTS)),
            skip_existing=False,
        )
    else:
        print("\n=== 1/4 Skipped frame extraction ===")

    split_cfg = cfg.get("split", {})
    val_fraction = float(split_cfg.get("val_fraction", 0.15))
    seed = int(split_cfg.get("seed", 42))

    if args.finish_only:
        print("\n=== Finish only (zip / data.yaml) ===")
        finish_dataset(
            dataset_dir,
            class_names,
            skip_split=args.skip_split,
            val_fraction=val_fraction,
            seed=seed,
            publish_dir=publish_dir,
            do_publish=args.publish,
            do_zip=args.zip,
        )
        print("\nDone.")
        print(f"  Dataset: {dataset_dir}")
        if args.zip:
            print("  Upload: data/autodistill/framesight_dataset.zip -> Colab")
        return 0

    if args.skip_label:
        print("\n=== Stopped before labeling (--skip-label) ===")
        return 0

    print("\n=== 2/4 AutoDistill labeling ===")
    label_frames(frames_dir, dataset_dir, cfg)

    finish_dataset(
        dataset_dir,
        class_names,
        skip_split=args.skip_split,
        val_fraction=val_fraction,
        seed=seed,
        publish_dir=publish_dir,
        do_publish=args.publish,
        do_zip=args.zip,
    )

    print("\nDone.")
    print(f"  Dataset: {dataset_dir}")
    print("  Colab:   upload zip — open colab/FrameSight_Complete.ipynb")
    print("  Local:   .\\scripts\\train.ps1  (after --publish or copy to fn.v1i.yolov8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
