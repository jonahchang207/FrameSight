<p align="center">
  <img src="assets/logo.svg" alt="FrameSight" width="460">
</p>

<p align="center">
  <b>Real-time screen vision for Windows</b> — high-FPS capture, YOLO11n detection, and a transparent assistive overlay.
</p>

<p align="center">
  📖 <a href="https://jonahchang207.github.io/FrameSight/">Documentation</a> ·
  <a href="SETUP.md">Setup</a> ·
  <a href="TRAIN.md">Train</a> ·
  <a href="https://github.com/jonahchang207/FrameSight">GitHub</a>
</p>

---

FrameSight captures your display at up to **165 Hz**, runs **YOLO11n** on the GPU (CUDA, DirectML, or CPU), and draws a transparent, click-through overlay — built for accessibility research and visual assistance.

## Overlay at a glance

<p align="center">
  <img src="assets/overlay-annotated.svg" alt="Annotated FrameSight overlay" width="900">
</p>

> The image above is a labeled mockup of the overlay elements. To showcase a real run, drop a screenshot at `assets/screenshot.png` and it'll render below.
>
> <!-- ![FrameSight in action](assets/screenshot.png) -->

## Features

- **High-FPS capture** — DXGI Desktop Duplication via `dxcam`, targeting your monitor's refresh (up to 165 Hz). The overlay sets `WDA_EXCLUDEFROMCAPTURE`, so it never captures itself.
- **GPU detection** — YOLO11n with automatic backend selection: CUDA (NVIDIA), DirectML + FP16 (AMD/Intel), or CPU. Forward/velocity model extrapolates boxes to paint time to hide inference latency.
- **Cyan detection boxes** — one per target, with optional label + confidence.
- **Green corner arrows** — dashed arrows from the four screen corners to the box **nearest the screen center** (only one target at a time).
- **200% magnifier** — a circular zoomed inset of the screen center that appears **while you hold the right mouse button**. It runs on its own worker thread so box rendering is never blocked.
- **Per-class toggles** — disable a class entirely (e.g. `detect_head: false`) so it's never inferred or drawn.
- **Live HUD** — overlay / capture / inference FPS and target count.

## Requirements

- **Windows 10 (2004+) / 11** — the capture and overlay are Windows-only.
- **Python 3.10+**
- A GPU is recommended (NVIDIA CUDA, or AMD/Intel via DirectML). CPU works but is slower.

## Install

```powershell
git clone https://github.com/jonahchang207/FrameSight.git
cd FrameSight
.\scripts\setup_windows.ps1   # creates .venv and installs requirements
```

This installs the core dependencies (`ultralytics`, `opencv-python-headless`, `numpy`, `dxcam`, `Pillow`) plus the DirectML ONNX Runtime on Windows. See **[SETUP.md](SETUP.md)** for Python, dataset, and dependency details.

## Run

```powershell
.\scripts\train.ps1   # train weights (or place your own at weights/best.pt)
.\scripts\run.ps1     # launch the live overlay
```

`run.ps1` activates the venv and starts `python -m src.main`. Press **Ctrl+C** in the terminal to quit.

### Controls

| Action | Effect |
|--------|--------|
| **Hold right mouse button** | Show the 200% magnifier at the screen center |
| **Ctrl+C** (in terminal) | Quit FrameSight |

## Configuration

All settings live in **`config/default.yaml`** (copy to `config/local.yaml` to override without touching the default). Highlights:

```yaml
capture:
  target_fps: 165
  region: [320, 180, 1280, 720]   # centered region; null = full monitor

model:
  weights: weights/best.pt
  conf: 0.7            # detection confidence threshold
  detect_head: false  # false = never detect or draw the 'head' class (body only)
  device: auto        # auto | cpu | 0 (CUDA) | dml

overlay:
  colors:
    default: [0, 255, 255]   # cyan boxes (RGB)
  box_thickness: 2
  show_center_lines: true    # green dashed corner arrows to the nearest box
  center_line_width: 2
  proximity_radius_px: 150   # "near center" radius for the corner arrows
  proximity_flash: false     # red screen border when a target nears center
  magnifier: true            # circular zoom inset of the screen center
  magnifier_radius: 80       # on-screen radius of the magnifier circle (px)
  magnifier_zoom: 2.0        # magnification factor (2.0 = 200%)
  magnifier_hold_rmb: true   # only show the magnifier while RMB is held
```

## Documentation

| Guide | Description |
|-------|-------------|
| **[SETUP.md](SETUP.md)** | Install Python, dataset, and dependencies |
| **[TRAIN.md](TRAIN.md)** | Train the model and run the overlay |
| **[AUTODISTILL.md](AUTODISTILL.md)** | Label footage with AutoDistill → train in Colab |
| **[colab/FrameSight_Complete.ipynb](colab/FrameSight_Complete.ipynb)** | Full Colab notebook (upload → train → download → overlay) |

Full feature overview and pipeline details: **[jonahchang207.github.io/FrameSight](https://jonahchang207.github.io/FrameSight/)**

## Ethics

FrameSight is for **research and assistive technology** only. Many applications restrict third-party overlays — verify terms of service and use offline or permitted environments for development.
