# FrameSight

**Real-time screen vision for Windows** — high-FPS capture, YOLO detection, and a transparent assistive overlay.

🌐 **[framesight.github.io: https://jonahchang207.github.io/FrameSight/ ]([https://jonahchang.github.io/FrameSight/](https://jonahchang207.github.io/FrameSight/))** · [Setup](SETUP.md) · [Train](TRAIN.md)

## Quick start

```powershell
cd FrameSight
.\scripts\setup_windows.ps1
.\scripts\train.ps1
.\scripts\run.ps1
```

## Documentation

| Guide | Description |
|-------|-------------|
| **[SETUP.md](SETUP.md)** | Install Python, dataset, dependencies |
| **[TRAIN.md](TRAIN.md)** | Train the model and run the overlay |

## GitHub Pages

Enable in repo settings: **Pages → Build from branch → `main` → `/docs`**.

## Publish to GitHub

```bash
gh auth login
gh repo create FrameSight --public --source=. --remote=origin --push
```

Update `docs/js/config.js` with your GitHub username/repo URL.

## Ethics

For research and assistive technology only. Respect application terms of service.
