"""FastAPI localhost dashboard for the video/stream annotator.

Run:
    python -m src.web.app --source path/to/clip.mp4
    python -m src.web.app --source https://www.twitch.tv/<channel>

Opens http://127.0.0.1:8000 with the annotated overlay plus live controls for
per-class colours, visibility, box thickness, labels, and a confidence filter.
The input is always decoded media (a file or stream URL) — not a live capture
of your screen — and there is no forward/velocity prediction.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from src.config_loader import ROOT, load_config
from src.inference.detector_factory import create_detector
from src.web.annotator import Annotator
from src.web.render_settings import RenderSettings
from src.web.video_source import BufferedVideoSource


def _resolve_weights(cfg: Dict[str, Any]) -> Path:
    weights = Path(cfg["model"]["weights"])
    if not weights.is_absolute():
        weights = ROOT / weights
    if weights.exists():
        return weights
    return Path(cfg["model"].get("base_checkpoint", "yolo11n.pt"))


def _class_names(detector, cfg: Dict[str, Any]) -> Dict[int, str]:
    names = dict(getattr(detector, "names", {}) or {})
    if names:
        return names
    # ONNX models may not expose names until first inference; fall back to the
    # training names in config so the dashboard can list classes immediately.
    training = cfg.get("training", {}).get("names")
    if isinstance(training, list) and training:
        return {i: str(n) for i, n in enumerate(training)}
    return {0: "object"}


def build_app(source: str, loop: bool, fps_override: float | None):
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

    cfg = load_config()
    model_cfg = cfg["model"]
    overlay_cfg = cfg.get("overlay", {})

    weights = _resolve_weights(cfg)
    # Infer at a low confidence floor so the dashboard's confidence slider can
    # reveal lower-confidence boxes live without rebuilding the detector.
    display_conf = float(model_cfg.get("conf", 0.35))
    infer_conf = min(display_conf, 0.10)
    detector = create_detector(
        weights=weights,
        imgsz=model_cfg.get("imgsz", 640),
        conf=infer_conf,
        iou=float(model_cfg.get("iou", 0.45)),
        device_requested=model_cfg.get("device", "auto"),
        max_det=int(model_cfg.get("max_det", 300)),
        agnostic_nms=bool(model_cfg.get("agnostic_nms", False)),
        half=bool(model_cfg.get("half", True)),
        io_binding=bool(model_cfg.get("io_binding", False)),
    )

    names = _class_names(detector, cfg)
    colors_cfg = overlay_cfg.get("colors", {})
    class_colors = {
        k: v for k, v in colors_cfg.items() if k != "default" and isinstance(v, (list, tuple))
    }
    settings = RenderSettings(
        class_names=names,
        default_color=colors_cfg.get("default", [0, 255, 128]),
        class_colors=class_colors,
        conf=display_conf,
        thickness=int(overlay_cfg.get("box_thickness", 2)),
        show_labels=bool(overlay_cfg.get("show_labels", True)),
        show_confidence=bool(overlay_cfg.get("show_confidence", True)),
    )

    video = BufferedVideoSource(source, loop=loop, fps_override=fps_override)
    annotator = Annotator(detector, video, settings)

    app = FastAPI(title="FrameSight Annotator")

    @app.on_event("startup")
    def _startup() -> None:
        annotator.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        annotator.stop()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX_HTML

    @app.get("/stream.mjpg")
    def stream() -> StreamingResponse:
        return StreamingResponse(
            annotator.mjpeg(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/api/settings")
    def get_settings() -> JSONResponse:
        return JSONResponse(settings.snapshot())

    @app.post("/api/settings")
    async def post_settings(request: Request) -> JSONResponse:
        payload = await request.json()
        return JSONResponse(settings.update_from_dict(payload))

    @app.get("/api/stats")
    def get_stats() -> JSONResponse:
        return JSONResponse(annotator.stats())

    return app


def main() -> int:
    parser = argparse.ArgumentParser(prog="framesight-web")
    parser.add_argument(
        "--source",
        required=True,
        help="Video file path or stream/video URL to annotate (not a live screen capture).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fps", type=float, default=None, help="Override playback FPS.")
    parser.add_argument(
        "--no-loop", action="store_true", help="Stop at end of file instead of looping."
    )
    args = parser.parse_args()

    import uvicorn

    app = build_app(source=args.source, loop=not args.no_loop, fps_override=args.fps)
    print(f"FrameSight annotator: http://{args.host}:{args.port}  (source: {args.source})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


_INDEX_HTML = """<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>FrameSight Annotator</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, Segoe UI, sans-serif; background: #0e1116; color: #e6edf3; }
  header { padding: 14px 20px; border-bottom: 1px solid #232a33; display: flex; align-items: baseline; gap: 14px; }
  header h1 { font-size: 17px; margin: 0; font-weight: 600; }
  header .sub { color: #8b949e; font-size: 13px; }
  .wrap { display: grid; grid-template-columns: 1fr 320px; gap: 18px; padding: 18px; align-items: start; }
  .video { background: #000; border: 1px solid #232a33; border-radius: 8px; overflow: hidden; }
  .video img { display: block; width: 100%; height: auto; }
  .panel { background: #161b22; border: 1px solid #232a33; border-radius: 8px; padding: 16px; }
  .panel h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #8b949e; margin: 0 0 12px; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 10px 0; }
  .row label { font-size: 14px; }
  .cls { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
  .cls input[type=color] { width: 34px; height: 26px; padding: 0; border: none; background: none; }
  .cls .name { flex: 1; font-size: 14px; }
  input[type=range] { width: 150px; }
  .stats { font-variant-numeric: tabular-nums; font-size: 13px; color: #9da7b3; line-height: 1.7; }
  .stats b { color: #e6edf3; font-weight: 600; }
  .divider { height: 1px; background: #232a33; margin: 14px 0; }
</style>
</head>
<body>
<header>
  <h1>FrameSight Annotator</h1>
  <span class=\"sub\">video / stream overlay &middot; localhost</span>
</header>
<div class=\"wrap\">
  <div class=\"video\"><img id=\"view\" src=\"/stream.mjpg\" alt=\"annotated stream\" /></div>
  <div>
    <div class=\"panel\">
      <h2>Classes</h2>
      <div id=\"classes\"></div>
    </div>
    <div class=\"panel\" style=\"margin-top:14px\">
      <h2>Overlay</h2>
      <div class=\"row\"><label>Confidence</label><input id=\"conf\" type=\"range\" min=\"0\" max=\"1\" step=\"0.01\" /></div>
      <div class=\"row\"><label>Thickness</label><input id=\"thickness\" type=\"range\" min=\"1\" max=\"12\" step=\"1\" /></div>
      <div class=\"row\"><label>Show labels</label><input id=\"show_labels\" type=\"checkbox\" /></div>
      <div class=\"row\"><label>Show confidence</label><input id=\"show_confidence\" type=\"checkbox\" /></div>
      <div class=\"divider\"></div>
      <h2>Performance</h2>
      <div class=\"stats\" id=\"stats\">connecting&hellip;</div>
    </div>
  </div>
</div>
<script>
const $ = (id) => document.getElementById(id);
let state = null;

function hex(rgb){ return '#' + rgb.map(c => c.toString(16).padStart(2,'0')).join(''); }
function rgb(hex){ return [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)); }

async function load(){
  state = await (await fetch('/api/settings')).json();
  const box = $('classes'); box.innerHTML = '';
  for(const [name, st] of Object.entries(state.classes)){
    const row = document.createElement('div'); row.className = 'cls';
    const color = document.createElement('input'); color.type = 'color'; color.value = hex(st.color);
    color.oninput = () => post({classes: {[name]: {color: rgb(color.value)}}});
    const label = document.createElement('span'); label.className = 'name'; label.textContent = name;
    const on = document.createElement('input'); on.type = 'checkbox'; on.checked = st.enabled;
    on.onchange = () => post({classes: {[name]: {enabled: on.checked}}});
    row.append(color, label, on); box.append(row);
  }
  $('conf').value = state.conf;
  $('thickness').value = state.thickness;
  $('show_labels').checked = state.show_labels;
  $('show_confidence').checked = state.show_confidence;
}

async function post(patch){
  state = await (await fetch('/api/settings', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(patch)
  })).json();
}

$('conf').oninput = (e) => post({conf: parseFloat(e.target.value)});
$('thickness').oninput = (e) => post({thickness: parseInt(e.target.value)});
$('show_labels').onchange = (e) => post({show_labels: e.target.checked});
$('show_confidence').onchange = (e) => post({show_confidence: e.target.checked});

async function poll(){
  try {
    const s = await (await fetch('/api/stats')).json();
    $('stats').innerHTML =
      `Display <b>${s.display_fps}</b> fps &middot; Inference <b>${s.inference_fps}</b> fps<br>` +
      `Source <b>${s.source_fps}</b> fps &middot; ${s.resolution[0]}&times;${s.resolution[1]}` +
      (s.ended ? '<br><b>source ended</b>' : '');
  } catch(e) {}
}
load();
setInterval(poll, 1000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
