# AutoDistill pipeline — Valorant footage → labeled dataset → Colab train

Turn 1920×1080 gameplay clips into a YOLO dataset (`body`, `head`) without hand-labeling every frame.

---

## Overview

| Step | Where | Output |
|------|--------|--------|
| 1. Drop videos | `data/videos/` | `.mp4`, `.mkv`, … |
| 2. Extract + label | PC (`autodistill_pipeline.py`) | `data/autodistill/dataset/` |
| 3. Train | Google Colab GPU | `best.pt` → `weights/best.pt` |
| 4. Run overlay | Windows | `python -m src.main` |

---

## 1. Install labeling dependencies (PC)

Use a venv with GPU recommended (OWL models are slow on CPU).

```powershell
cd C:\path\to\FrameSight
.\.venv\Scripts\Activate.ps1
pip install -r requirements-autodistill.txt
```

Or run the wrapper (installs deps + runs pipeline):

```powershell
.\scripts\autodistill.ps1
```

---

## 2. Add videos

Copy one or more clips into:

```
FrameSight/
  data/
    videos/
      match1.mp4
      match2.mp4
```

**Tips for Valorant**

- 1920×1080 footage works best (pipeline can resize to that size).
- **Every frame** is extracted by default (`every_frame: true`). A 10 min @ 60 fps clip ≈ 36,000 images — ensure you have disk space.
- To sample instead, set `every_frame: false` and `extract_fps: 3` in `config/autodistill.yaml`.
- Clear player visibility improves OWL labels; review a few frames before Colab training.

---

## 3. Run the pipeline

```powershell
python scripts/autodistill_pipeline.py --zip --publish
```

| Flag | Meaning |
|------|---------|
| `--zip` | Create `data/autodistill/framesight_dataset.zip` for Colab upload |
| `--publish` | Copy dataset to `fn.v1i.yolov8/` for local `train.ps1` |
| `--skip-extract` | Re-label existing frames only |
| `--skip-label` | Only extract frames, no AutoDistill |

Edit prompts and FPS in `config/autodistill.yaml`:

```yaml
video:
  every_frame: true   # false + extract_fps to sample (e.g. 3 fps)
  extract_fps: 30
  frame_size: [1920, 1080]

labeling:
  base_model: owlv2
  ontology:
    "valorant player": body
    "person": body
    "human head": head
```

AutoDistill is **approximate** — spot-check labels in `data/autodistill/dataset/train/images` and adjust `ontology` if heads/players are missed.

---

## 4. Train in Google Colab

1. Run the pipeline with `--zip`.
2. Open **[`colab/FrameSight_Complete.ipynb`](colab/FrameSight_Complete.ipynb)** in [Google Colab](https://colab.research.google.com/) (full step-by-step notebook), or the shorter [`colab/train_framesight.ipynb`](colab/train_framesight.ipynb).
3. **Runtime → Change runtime type → GPU** (T4 or better).
4. Upload `data/autodistill/framesight_dataset.zip` when prompted.
5. Run all cells → download `best.pt`.
6. On Windows, copy to `weights/best.pt` and run `.\scripts\run.ps1`.

**Google Drive alternative:** upload the zip to Drive, mount in Colab, and point `DATASET_ZIP` at the Drive path.

---

## 5. Train locally (optional)

If you used `--publish`:

```powershell
.\scripts\train.ps1
```

---

## Output layout

```
data/autodistill/
  frames/              # extracted JPGs
  dataset/
    train/images
    train/labels
    valid/images
    valid/labels
    data.yaml
  framesight_dataset.zip   # for Colab
```

Classes match FrameSight: `body`, `head`.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `No videos in data/videos` | Add `.mp4` files to that folder |
| `owlv2 not installed` | Use `base_model: owlvit` in config (recommended) |
| `transformers 5.x dev` / `ParallelStyle` error | Run `.\scripts\fix_autodistill_env.ps1` — OWLv2 broke your env |
| `ModuleNotFoundError: sklearn` | `pip install scikit-learn` |
| CUDA OOM during labeling | Lower `extract_fps` or label in smaller batches |
| Empty / wrong labels | Tune `ontology` captions in `config/autodistill.yaml` |
| Colab can't find `data.yaml` | Re-run pipeline with `--zip` |

---

## Research / ToS note

Use only on footage you may process and for projects that allow automated labeling and model training. Competitive titles may restrict third-party tools — follow each game's terms of service.
