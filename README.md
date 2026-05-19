# ValorantCV

Windows-only live screen capture + YOLO detection overlay. Built for research and assistive technology.

## Requirements

- **Windows 10/11**
- **Python 3.10+**
- **NVIDIA GPU** recommended for training and inference
- Dataset folder `fn.v1i.yolov8/` (not included in git — download separately)

## Quick start

```powershell
cd ValorantCV
.\scripts\setup_windows.ps1
.\scripts\train.ps1
.\scripts\run.ps1
```

| Script | Purpose |
|--------|---------|
| `setup_windows.ps1` | Create venv, install dependencies |
| `train.ps1` | Train YOLO11n → saves `weights/best.pt` |
| `run.ps1` | Live screen overlay with detection boxes |

## Dataset

Place the Roboflow YOLOv8 export at **`fn.v1i.yolov8/`** in the project root:

```
fn.v1i.yolov8/
  data.yaml
  train/images/  train/labels/
  valid/images/  valid/labels/
```

- **Classes:** `enemy`, `enemy_head`
- **Source:** [Roboflow Universe — fn-ib9mp](https://universe.roboflow.com/itsanoriot/fn-ib9mp/dataset/1)

The dataset is gitignored (~10k images). Clone the repo, then add the folder locally.

## Configuration

Edit `config/default.yaml`:

- `capture.target_fps` — capture target (default 165)
- `model.device` — `"0"` for GPU, `"cpu"` otherwise
- `model.conf` — detection confidence threshold
- `overlay.colors` — per-class box colors

## Architecture

| Layer | Tech |
|-------|------|
| Capture | dxcam (DXGI) |
| Inference | Ultralytics YOLO11n |
| Overlay | Win32 transparent click-through window |

## Project layout

```
ValorantCV/
  config/default.yaml
  scripts/
    setup_windows.ps1
    train.ps1
    train_local.py
    run.ps1
  src/
    main.py
    capture/
    inference/
    overlay/
  fn.v1i.yolov8/     # your dataset (local only)
  weights/best.pt    # after training
  runs/              # training outputs (gitignored)
```

## Ethics

Use only where permitted. Many games restrict third-party overlays in competitive play.
