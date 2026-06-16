# FrameSight Annotator — video / stream dashboard

A localhost web app that runs the FrameSight detector over a **video file or a
stream URL** and shows the annotated overlay in your browser, with live controls
for box colors, visibility, thickness, labels, and a confidence filter.

This is a review/understanding tool for recorded or streamed content. It does
**not** capture your live screen and it does **not** predict box positions
(no forward/velocity model) — boxes are the latest detection drawn on the frame
being shown.

## Install

```powershell
pip install -r requirements.txt
```

This adds `fastapi`, `uvicorn`, and (optional) `yt-dlp` on top of the core deps.

## Run

```powershell
# A local clip
python -m src.web.app --source "C:\path\to\clip.mp4"

# A direct media URL (.mp4 / .m3u8 / .ts ...)
python -m src.web.app --source "https://example.com/stream.m3u8"

# A site page (YouTube/Twitch/etc.) — resolved via yt-dlp if installed
python -m src.web.app --source "https://www.twitch.tv/<channel>"
```

Then open <http://127.0.0.1:8000>.

### Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--source` | (required) | Video file path or stream/video URL |
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Port |
| `--fps` | source FPS | Override playback rate |
| `--no-loop` | off | Stop at end of file instead of looping |

## How it stays smooth at high refresh

A background thread decodes **ahead** into a bounded buffer, so the player can
hold a steady frame rate even when decode or inference hitches. Inference runs
on a separate thread against whatever frame is currently on screen and updates
the latest boxes; the player draws those boxes on every displayed frame. The
video plays smoothly at the source rate; boxes refresh at the inference rate.

## Settings

The model and overlay defaults come from `config/default.yaml`
(`model.*`, `overlay.colors`, `overlay.box_thickness`, ...). Everything in the
dashboard is editable live and applies immediately:

- per-class **color** picker and **show/hide** toggle (classes come from your model)
- box **thickness**
- **confidence** filter (the detector runs at a low floor so the slider can
  reveal lower-confidence boxes without a restart)
- **labels** and **confidence text** toggles

The performance panel shows display FPS, inference FPS, source FPS, and
resolution.
