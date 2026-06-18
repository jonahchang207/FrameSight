# Training Guide

Train the YOLO11n detector on your Windows machine, then run the live overlay.

**Prerequisites:** Complete **[SETUP.md](SETUP.md)** first.

---

## Overview

| Step | Command | Result |
|------|---------|--------|
| 1. Train | `.\scripts\train.ps1` | `runs\framesight\weights\best.pt` |
| 2. Weights copied automatically | (same script) | `weights\best.pt` |
| 3. Run overlay | `.\scripts\run.ps1` | Live boxes on screen |

Training uses the local dataset at `fn.v1i.yolov8\` and settings in `config\default.yaml`.

**Build a dataset from gameplay video:** see **[AUTODISTILL.md](AUTODISTILL.md)** (multi-video upload → frame split → OWLv2 labels → Google Colab train).

---

## 1. Start training

Open PowerShell in the project folder:

```powershell
cd C:\path\to\FrameSight
.\.venv\Scripts\Activate.ps1
.\scripts\train.ps1
```

Or without activating the venv (script uses `.venv` directly):

```powershell
.\scripts\train.ps1
```

### What happens

1. Validates `fn.v1i.yolov8\` and `data.yaml`
2. Downloads **yolo11n.pt** base weights (first run only)
3. Trains for **100 epochs** (default), with early stopping (`patience: 20`)
4. Saves runs to `runs\framesight\`
5. Copies the best checkpoint to **`weights\best.pt`**

### How long it takes

Depends on your GPU. On a typical NVIDIA GPU (e.g. RTX 3060+), expect **roughly 1–3 hours** for 100 epochs with batch 16. Fewer epochs = faster but may reduce accuracy.

---

## 2. Monitor training

Ultralytics prints loss and metrics in the terminal. You can also open:

```
runs\framesight\
  weights\best.pt      # best validation weights
  weights\last.pt      # latest epoch
  results.png          # loss/metric curves
  confusion_matrix.png
```

Training stops early if validation metrics stop improving for `patience` epochs.

---

## 3. Adjust training settings

Edit `config\default.yaml`:

```yaml
training:
  epochs: 100      # reduce to 50 for a quicker test run
  batch: 16        # lower to 8 or 4 if CUDA out-of-memory
  patience: 20
  names: ['body', 'head']

model:
  base_checkpoint: yolo11n.pt   # nano = fastest
  imgsz: 640
  device: "0"                   # GPU index; use "cpu" if no GPU
```

After changing config, run `.\scripts\train.ps1` again.

### Out of memory (CUDA OOM)

1. Set `training.batch: 8` or `4`
2. Set `model.imgsz: 416`
3. Close other GPU apps (games, browsers with hardware acceleration)

### Train on CPU only

```yaml
model:
  device: "cpu"
training:
  batch: 4
  epochs: 50
```

Very slow — use only for testing.

---

## 4. Run the live overlay

After `weights\best.pt` exists:

```powershell
.\scripts\run.ps1
```

Or:

```powershell
.\.venv\Scripts\Activate.ps1
python -m src.main
```

- Full-screen capture + detection boxes (red = `body`, yellow = `head`)
- **Ctrl+C** in the terminal to quit

### OBS recording

**Display Capture** on your game monitor shows boxes on screen (no config change).

For **Window Capture**, set `overlay.click_through: false` in config, restart `.\scripts\run.ps1`, then add **Window Capture** → **FrameSight Overlay** (overlay area blocks mouse clicks).

### Overlay settings (`config\default.yaml`)

```yaml
capture:
  target_fps: 165    # capture target; actual FPS depends on GPU

model:
  conf: 0.35         # raise to reduce false positives
  weights: weights/best.pt

overlay:
  enabled: true
  show_labels: true
  show_confidence: true

smoothing:
  enabled: true
  alpha: 0.4       # lower = smoother boxes, slightly more lag
  match_iou: 0.3
  max_age: 3
```

### Jittery or sluggish boxes

Inference runs near ~30 FPS while capture is much faster, so raw boxes can shake frame-to-frame. **Smoothing** (enabled by default) tracks targets and blends positions over time.

| Symptom | Try |
|---------|-----|
| Boxes still jittery | Lower `smoothing.alpha` (e.g. `0.25`) |
| Boxes feel laggy behind motion | Raise `smoothing.alpha` (e.g. `0.55`) |
| Boxes blink on/off | Raise `model.conf` (e.g. `0.45`) or raise `smoothing.max_age` |
| Many enemies, only 1–2 boxes | Lower `model.iou` (e.g. `0.25`) and/or `model.conf` (e.g. `0.45`); try `imgsz: 640` |
| Boxes linger after target leaves | Lower `smoothing.max_age` (e.g. `2`) |
| Compare raw vs smooth | Set `smoothing.enabled: false` |

---

## 5. Re-train or fine-tune

To train again from scratch:

```powershell
# optional: remove old run
Remove-Item -Recurse -Force runs\framesight
.\scripts\train.ps1
```

To continue from your last checkpoint:

```powershell
.\.venv\Scripts\python.exe -c "
from ultralytics import YOLO
m = YOLO('runs/framesight/weights/last.pt')
m.train(data='fn.v1i.yolov8/data.yaml', epochs=50, device=0)
"
```

---

## Troubleshooting training

| Problem | Fix |
|---------|-----|
| `Dataset not found` | Ensure `fn.v1i.yolov8\data.yaml` exists (see SETUP.md) |
| `CUDA not available` | Install NVIDIA drivers; check `nvidia-smi` in terminal |
| Training very slow | Confirm `device: "0"` in config, not `"cpu"` |
| Poor detections | Train longer, lower `conf` at inference, or add more labeled data |
| Overlay shows nothing | Check `weights\best.pt` exists; lower `model.conf` in config |

---

## File checklist

After a successful train + run:

```
FrameSight/
  fn.v1i.yolov8/          ✓ dataset
  weights/best.pt         ✓ trained model
  runs/framesight/        ✓ logs and checkpoints
  .venv/                  ✓ Python environment
```

---

## Ethics

Use only for research or assistive purposes where automation and overlays are allowed. Respect game terms of service and local laws.
