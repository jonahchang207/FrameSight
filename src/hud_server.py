"""
Local control panel at http://localhost:5000 — no external dependencies.
Mutates Win32Overlay attributes directly; Python's GIL makes scalar writes safe.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_HTML = b"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FrameSight HUD</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0a;color:#ccc;font-family:Consolas,'Courier New',monospace;font-size:13px;padding:18px;min-width:380px}
h1{color:#00ff88;font-size:1.05rem;letter-spacing:3px;margin-bottom:3px}
.sub{color:#333;font-size:0.68rem;margin-bottom:18px}
section{margin-bottom:18px}
h2{color:#00aaff;font-size:0.68rem;letter-spacing:4px;text-transform:uppercase;border-bottom:1px solid #1e1e1e;padding-bottom:5px;margin-bottom:9px}
.row{display:flex;align-items:center;justify-content:space-between;margin-bottom:7px}
.lbl{color:#888;flex:1}
.ctrl{display:flex;align-items:center;gap:8px}
input[type=range]{width:140px;height:3px;accent-color:#00ff88;cursor:pointer}
.vl{min-width:44px;text-align:right;color:#fff}
.tog{position:relative;width:40px;height:22px;cursor:pointer;display:inline-block}
.tog input{display:none}
.tbg{position:absolute;inset:0;background:#1e1e1e;border-radius:22px;border:1px solid #333;transition:background .15s,border-color .15s}
.tkn{position:absolute;top:3px;left:3px;width:14px;height:14px;background:#555;border-radius:50%;transition:transform .15s,background .15s}
.tog input:checked~.tbg{background:#002a16;border-color:#00ff88}
.tog input:checked~.tkn{transform:translateX(18px);background:#00ff88}
.palette{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.pitem{display:flex;flex-direction:column;align-items:center;gap:3px}
.pitem span{font-size:0.6rem;color:#444}
input[type=color]{width:36px;height:28px;border:1px solid #2a2a2a;border-radius:4px;background:#111;cursor:pointer;padding:2px}
input[type=color]:hover{border-color:#00ff88}
#st{margin-top:14px;font-size:0.68rem;color:#333;border-top:1px solid #141414;padding-top:8px}
.ok{color:#00ff88!important}.err{color:#ff4444!important}
</style>
</head>
<body>
<h1>FRAMESIGHT</h1>
<div class="sub">live overlay control &middot; http://localhost:5000</div>

<section>
  <h2>Display</h2>
  <div class="row"><span class="lbl">Box Thickness</span><div class="ctrl"><input type="range" id="box_thickness" min="1" max="8" step="1"><span class="vl" id="box_thickness_v"></span></div></div>
  <div class="row"><span class="lbl">Show Labels</span><label class="tog"><input type="checkbox" id="show_labels"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Show Confidence</span><label class="tog"><input type="checkbox" id="show_confidence"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Show FPS</span><label class="tog"><input type="checkbox" id="show_fps"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Center Lines</span><label class="tog"><input type="checkbox" id="show_center_lines"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Line Width</span><div class="ctrl"><input type="range" id="center_line_width" min="1" max="8" step="1"><span class="vl" id="center_line_width_v"></span></div></div>
</section>

<section>
  <h2>Magnifier</h2>
  <div class="row"><span class="lbl">Enabled</span><label class="tog"><input type="checkbox" id="magnifier"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Radius (px)</span><div class="ctrl"><input type="range" id="magnifier_radius" min="20" max="200" step="4"><span class="vl" id="magnifier_radius_v"></span></div></div>
  <div class="row"><span class="lbl">Zoom</span><div class="ctrl"><input type="range" id="magnifier_zoom" min="1.0" max="5.0" step="0.25"><span class="vl" id="magnifier_zoom_v"></span></div></div>
  <div class="row"><span class="lbl">Hold RMB to show</span><label class="tog"><input type="checkbox" id="magnifier_hold_rmb"><div class="tbg"></div><div class="tkn"></div></label></div>
</section>

<section>
  <h2>Proximity Flash</h2>
  <div class="row"><span class="lbl">Enabled</span><label class="tog"><input type="checkbox" id="proximity_flash"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Trigger Radius (px)</span><div class="ctrl"><input type="range" id="proximity_radius_px" min="50" max="600" step="10"><span class="vl" id="proximity_radius_px_v"></span></div></div>
  <div class="row"><span class="lbl">Border Width</span><div class="ctrl"><input type="range" id="proximity_border_width" min="2" max="40" step="2"><span class="vl" id="proximity_border_width_v"></span></div></div>
  <div class="row"><span class="lbl">Flash Rate (Hz)</span><div class="ctrl"><input type="range" id="proximity_flash_hz" min="0.5" max="20" step="0.5"><span class="vl" id="proximity_flash_hz_v"></span></div></div>
</section>

<section>
  <h2>Detection Colors</h2>
  <div class="palette" id="palette"></div>
</section>

<div id="st">Connecting...</div>

<script>
const SLIDERS=[
  ['box_thickness',     v=>Math.round(v)+'px'],
  ['center_line_width', v=>Math.round(v)+'px'],
  ['magnifier_radius',  v=>Math.round(v)+'px'],
  ['magnifier_zoom',    v=>parseFloat(v).toFixed(2)+'\xd7'],
  ['proximity_radius_px',    v=>Math.round(v)+'px'],
  ['proximity_border_width', v=>Math.round(v)+'px'],
  ['proximity_flash_hz',     v=>parseFloat(v).toFixed(1)+' Hz'],
];
const CHECKS=['show_labels','show_confidence','show_fps','show_center_lines','magnifier','magnifier_hold_rmb','proximity_flash'];
const FLOATS=new Set(['magnifier_zoom','proximity_flash_hz']);

let timer=null,palette=[];
function post(p){
  clearTimeout(timer);
  timer=setTimeout(()=>
    fetch('/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})
      .then(r=>r.json()).then(()=>st('● saved',true))
      .catch(()=>st('✗ error',false))
  ,60);
}
function st(msg,ok){const e=document.getElementById('st');e.textContent=msg;e.className=ok?'ok':'err';}

function buildPalette(colors){
  palette=[...colors];
  const div=document.getElementById('palette');
  div.innerHTML='';
  colors.forEach((c,i)=>{
    const w=document.createElement('div');w.className='pitem';
    const inp=document.createElement('input');inp.type='color';inp.value=c;inp.title='Detection '+(i+1);
    inp.addEventListener('input',()=>{palette[i]=inp.value;post({det_palette:palette});});
    const lbl=document.createElement('span');lbl.textContent=i+1;
    w.appendChild(inp);w.appendChild(lbl);div.appendChild(w);
  });
}

fetch('/config').then(r=>r.json()).then(cfg=>{
  SLIDERS.forEach(([id,fmt])=>{
    const el=document.getElementById(id);if(!el)return;
    el.value=cfg[id];
    const vl=document.getElementById(id+'_v');if(vl)vl.textContent=fmt(cfg[id]);
    el.addEventListener('input',()=>{
      if(vl)vl.textContent=fmt(el.value);
      post({[id]:FLOATS.has(id)?parseFloat(el.value):parseInt(el.value)});
    });
  });
  CHECKS.forEach(id=>{
    const el=document.getElementById(id);if(!el)return;
    el.checked=cfg[id];
    el.addEventListener('change',()=>post({[id]:el.checked}));
  });
  buildPalette(cfg.det_palette||[]);
  st('● connected',true);
}).catch(()=>st('✗ cannot connect — is FrameSight running?',false));
</script>
</body>
</html>"""


def _snapshot(o) -> dict:
    return {
        "box_thickness":        o._box_thickness,
        "show_labels":          o._show_labels,
        "show_confidence":      o._show_confidence,
        "show_center_lines":    o._show_center_lines,
        "center_line_width":    o._center_line_width,
        "show_fps":             o._show_fps,
        "magnifier":            o._magnifier,
        "magnifier_radius":     o._magnifier_radius,
        "magnifier_zoom":       o._magnifier_zoom,
        "magnifier_hold_rmb":   o._magnifier_hold_rmb,
        "proximity_flash":      o._proximity_flash,
        "proximity_radius_px":  o._proximity_radius_px,
        "proximity_border_width": o._proximity_border_width,
        "proximity_flash_hz":   o._proximity_flash_hz,
        "det_palette":          list(o._det_palette),
    }


def _apply(o, data: dict) -> None:
    _INT = {
        "box_thickness":          (1,  20),
        "center_line_width":      (1,  20),
        "magnifier_radius":       (8,  400),
        "proximity_radius_px":    (1,  2000),
        "proximity_border_width": (1,  80),
    }
    _FLOAT = {
        "magnifier_zoom":    (1.0, 10.0),
        "proximity_flash_hz": (0.1, 60.0),
    }
    _BOOL = [
        "show_labels", "show_confidence", "show_fps", "show_center_lines",
        "magnifier", "magnifier_hold_rmb", "proximity_flash",
    ]
    for key, (lo, hi) in _INT.items():
        if key in data:
            setattr(o, f"_{key}", max(lo, min(hi, int(data[key]))))
    for key, (lo, hi) in _FLOAT.items():
        if key in data:
            setattr(o, f"_{key}", max(lo, min(hi, float(data[key]))))
    for key in _BOOL:
        if key in data:
            setattr(o, f"_{key}", bool(data[key]))
    if "det_palette" in data:
        p = data["det_palette"]
        if isinstance(p, list) and len(p) >= 1:
            o._det_palette = [str(c) for c in p]


def _make_server(overlay, port: int) -> HTTPServer:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def _send(self, code: int, body: bytes, ct: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, _HTML, "text/html; charset=utf-8")
            elif self.path == "/config":
                self._send(200, json.dumps(_snapshot(overlay)).encode(), "application/json")
            else:
                self._send(404, b'{"error":"not found"}', "application/json")

        def do_POST(self):
            if self.path != "/config":
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            n = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(n))
            except Exception:
                self._send(400, b'{"error":"bad json"}', "application/json")
                return
            _apply(overlay, data)
            self._send(200, b'{"ok":true}', "application/json")

    return HTTPServer(("127.0.0.1", port), _Handler)


def start(overlay_app, port: int = 5000) -> None:
    """Launch the HUD web panel as a background daemon thread.

    overlay_app — the OverlayApp instance created in main.py
    """
    inner = overlay_app._overlay  # OverlayApp wraps Win32Overlay
    server = _make_server(inner, port)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="hud-server")
    t.start()
    print(f"  HUD panel:  http://localhost:{port}")
