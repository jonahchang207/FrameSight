# FrameSight

**Real-time screen vision for Windows** — high-FPS capture, YOLO11n detection, and a transparent assistive overlay.

📖 **[Documentation](https://jonahchang207.github.io/FrameSight/)** · [Setup](SETUP.md) · [Train](TRAIN.md) · [GitHub](https://github.com/jonahchang207/FrameSight)

FrameSight captures your display at up to **165 Hz**, runs **YOLO11n** on the GPU, and draws a transparent, click-through overlay — built for accessibility research and visual assistance.

## Quick start

```powershell
cd FrameSight
.\scripts\setup_windows.ps1
.\scripts\train.ps1
.\scripts\run.ps1
```

## Documentation

Full docs, feature overview, and pipeline details live on GitHub Pages:

**[jonahchang207.github.io/FrameSight](https://jonahchang207.github.io/FrameSight/)**

| Guide | Description |
|-------|-------------|
| **[SETUP.md](SETUP.md)** | Install Python, dataset, and dependencies |
| **[TRAIN.md](TRAIN.md)** | Train the model and run the overlay |

## Ethics

FrameSight is for **research and assistive technology** only. Many applications restrict third-party overlays — verify terms of service and use offline or permitted environments for development.
