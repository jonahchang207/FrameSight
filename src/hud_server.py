"""
Local control panel at http://localhost:5000 — no external dependencies.
Mutates Win32Overlay attributes directly; Python's GIL makes scalar writes safe.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.config_loader import ROOT
from src.overlay.win32_overlay import _hex_to_rgb, _rgb_to_hex

# Persisted HUD state — a flat dump of _snapshot(), re-applied on next launch.
_STATE_PATH = ROOT / "config" / "hud_state.json"
# Named presets the user can save/load on demand: {name: snapshot}.
_PRESETS_PATH = ROOT / "config" / "hud_presets.json"


def _read_presets() -> dict:
    try:
        d = json.loads(_PRESETS_PATH.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_presets(d: dict) -> None:
    _PRESETS_PATH.write_text(json.dumps(d, indent=2))

_HTML = """<!DOCTYPE html>
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
select{background:#111;color:#ccc;border:1px solid #2a2a2a;border-radius:4px;font-family:inherit;font-size:12px;padding:3px 6px;cursor:pointer}
select:hover{border-color:#00ff88}
#st{margin-top:14px;font-size:0.68rem;color:#333;border-top:1px solid #141414;padding-top:8px}
.ok{color:#00ff88!important}.err{color:#ff4444!important}
button{background:#002a16;color:#00ff88;border:1px solid #00ff88;border-radius:4px;font-family:inherit;font-size:12px;letter-spacing:2px;padding:7px 16px;cursor:pointer;width:100%;transition:background .12s,color .12s}
button:hover{background:#00ff88;color:#000}
</style>
</head>
<body>
<h1>FRAMESIGHT</h1>
<div class="sub">live overlay control &middot; http://localhost:5000</div>

<section>
  <h2>Boxes</h2>
  <div class="row"><span class="lbl">Box Style</span><div class="ctrl"><select id="box_style"><option value="solid">Solid</option><option value="corners">Corners</option><option value="dashed">Dashed</option></select></div></div>
  <div class="row"><span class="lbl">Box Thickness</span><div class="ctrl"><input type="range" id="box_thickness" min="1" max="8" step="1"><span class="vl" id="box_thickness_v"></span></div></div>
  <div class="row"><span class="lbl">Corner Length</span><div class="ctrl"><input type="range" id="box_corner_len" min="4" max="120" step="2"><span class="vl" id="box_corner_len_v"></span></div></div>
  <div class="row"><span class="lbl">Fill Box</span><label class="tog"><input type="checkbox" id="box_fill"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Default Box Color</span><div class="ctrl"><input type="color" id="default_color"></div></div>
  <div class="row"><span class="lbl">Show Labels</span><label class="tog"><input type="checkbox" id="show_labels"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Show Confidence</span><label class="tog"><input type="checkbox" id="show_confidence"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Label Size</span><div class="ctrl"><input type="range" id="label_font_size" min="6" max="32" step="1"><span class="vl" id="label_font_size_v"></span></div></div>
</section>

<section>
  <h2>Lines &amp; Crosshair</h2>
  <div class="row"><span class="lbl">Center Lines</span><label class="tog"><input type="checkbox" id="show_center_lines"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Line Path</span><div class="ctrl"><select id="center_line_style"><option value="corners">To corners</option><option value="target">To target</option></select></div></div>
  <div class="row"><span class="lbl">Line Width</span><div class="ctrl"><input type="range" id="center_line_width" min="1" max="8" step="1"><span class="vl" id="center_line_width_v"></span></div></div>
  <div class="row"><span class="lbl">Line Target</span><div class="ctrl"><select id="center_line_target"><option value="box_center">Box center</option><option value="top_center">Top center</option></select></div></div>
  <div class="row"><span class="lbl">Dashed Lines</span><label class="tog"><input type="checkbox" id="center_line_dashed"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Arrow Heads</span><label class="tog"><input type="checkbox" id="center_line_arrow"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Crosshair</span><label class="tog"><input type="checkbox" id="crosshair"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Crosshair Size</span><div class="ctrl"><input type="range" id="crosshair_size" min="0" max="80" step="1"><span class="vl" id="crosshair_size_v"></span></div></div>
  <div class="row"><span class="lbl">Crosshair Gap</span><div class="ctrl"><input type="range" id="crosshair_gap" min="0" max="60" step="1"><span class="vl" id="crosshair_gap_v"></span></div></div>
  <div class="row"><span class="lbl">Crosshair Color</span><div class="ctrl"><input type="color" id="crosshair_color"></div></div>
  <div class="row"><span class="lbl">Motion Trails</span><label class="tog"><input type="checkbox" id="trails"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Trail Length</span><div class="ctrl"><input type="range" id="trail_len" min="2" max="120" step="1"><span class="vl" id="trail_len_v"></span></div></div>
</section>

<section>
  <h2>HUD Colors</h2>
  <div class="row"><span class="lbl">Show FPS</span><label class="tog"><input type="checkbox" id="show_fps"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">FPS Text Color</span><div class="ctrl"><input type="color" id="fps_color"></div></div>
  <div class="row"><span class="lbl">Proximity Color</span><div class="ctrl"><input type="color" id="proximity_color"></div></div>
  <div class="row"><span class="lbl">Magnifier Ring Color</span><div class="ctrl"><input type="color" id="magnifier_color"></div></div>
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
  <h2>Distance Colors</h2>
  <div class="row"><span class="lbl">Enabled</span><label class="tog"><input type="checkbox" id="distance_colors"><div class="tbg"></div><div class="tkn"></div></label></div>
  <div class="row"><span class="lbl">Near Color</span><div class="ctrl"><input type="color" id="color_near"></div></div>
  <div class="row"><span class="lbl">Far Color</span><div class="ctrl"><input type="color" id="color_far"></div></div>
  <div class="row"><span class="lbl">Max Distance (px)</span><div class="ctrl"><input type="range" id="distance_max_px" min="0" max="2000" step="20"><span class="vl" id="distance_max_px_v"></span></div></div>
</section>

<section>
  <h2>Detection Colors</h2>
  <div class="palette" id="palette"></div>
</section>

<section>
  <h2>Presets</h2>
  <button id="save">SAVE AS DEFAULT</button>
  <div class="sub" style="margin-top:6px;margin-bottom:10px">Persists every setting above to config/hud_state.json &mdash; restored on next launch.</div>
  <div class="row"><span class="lbl">Named Preset</span><div class="ctrl"><select id="preset_list"><option value="">— none —</option></select></div></div>
  <div class="row"><span class="lbl">&nbsp;</span><div class="ctrl"><button id="preset_load" style="width:auto;padding:5px 12px">LOAD</button><button id="preset_del" style="width:auto;padding:5px 12px">DELETE</button></div></div>
  <div class="row"><span class="lbl">Save Current As</span><div class="ctrl"><input type="text" id="preset_name" placeholder="name" maxlength="40" style="background:#111;color:#ccc;border:1px solid #2a2a2a;border-radius:4px;font-family:inherit;font-size:12px;padding:4px 6px;width:120px"></div></div>
  <div class="row"><span class="lbl">&nbsp;</span><div class="ctrl"><button id="preset_save" style="width:auto;padding:5px 12px">SAVE PRESET</button></div></div>
</section>

<div id="st">Connecting...</div>

<script>
const SLIDERS=[
  ['box_thickness',     v=>Math.round(v)+'px'],
  ['box_corner_len',    v=>Math.round(v)+'px'],
  ['label_font_size',   v=>Math.round(v)+'pt'],
  ['center_line_width', v=>Math.round(v)+'px'],
  ['crosshair_size',    v=>Math.round(v)+'px'],
  ['crosshair_gap',     v=>Math.round(v)+'px'],
  ['trail_len',         v=>Math.round(v)+' pts'],
  ['magnifier_radius',  v=>Math.round(v)+'px'],
  ['magnifier_zoom',    v=>parseFloat(v).toFixed(2)+'\xd7'],
  ['proximity_radius_px',    v=>Math.round(v)+'px'],
  ['proximity_border_width', v=>Math.round(v)+'px'],
  ['proximity_flash_hz',     v=>parseFloat(v).toFixed(1)+' Hz'],
  ['distance_max_px',        v=>parseInt(v)>0?Math.round(v)+'px':'auto'],
];
const CHECKS=['show_labels','show_confidence','show_fps','show_center_lines','magnifier','magnifier_hold_rmb','proximity_flash','distance_colors','box_fill','center_line_dashed','center_line_arrow','crosshair','trails'];
const SELECTS=['center_line_target','box_style','center_line_style'];
const COLORS=['default_color','color_near','color_far','crosshair_color','proximity_color','magnifier_color','fps_color'];
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
  SELECTS.forEach(id=>{
    const el=document.getElementById(id);if(!el)return;
    el.value=cfg[id];
    el.addEventListener('change',()=>post({[id]:el.value}));
  });
  COLORS.forEach(id=>{
    const el=document.getElementById(id);if(!el)return;
    el.value=cfg[id];
    el.addEventListener('input',()=>post({[id]:el.value}));
  });
  buildPalette(cfg.det_palette||[]);
  st('● connected',true);
}).catch(()=>st('✗ cannot connect — is FrameSight running?',false));

document.getElementById('save').addEventListener('click',()=>
  fetch('/save',{method:'POST'}).then(r=>r.json())
    .then(()=>st('● saved as default',true)).catch(()=>st('✗ save failed',false)));

const psel=document.getElementById('preset_list');
function loadPresetNames(sel){
  fetch('/presets').then(r=>r.json()).then(d=>{
    psel.innerHTML='<option value="">— none —</option>';
    d.names.forEach(n=>{const o=document.createElement('option');o.textContent=n;psel.appendChild(o);});
    if(sel)psel.value=sel;
  });
}
loadPresetNames();
function preset(op,name){
  return fetch('/preset',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({op,name})}).then(r=>r.json());
}
document.getElementById('preset_save').addEventListener('click',()=>{
  const n=document.getElementById('preset_name').value.trim();
  if(!n){st('✗ enter a name',false);return;}
  preset('save',n).then(()=>{loadPresetNames(n);st('● preset saved',true);}).catch(()=>st('✗ save failed',false));
});
document.getElementById('preset_load').addEventListener('click',()=>{
  if(!psel.value){st('✗ pick a preset',false);return;}
  preset('load',psel.value).then(()=>{st('● loaded — refreshing',true);setTimeout(()=>location.reload(),250);}).catch(()=>st('✗ load failed',false));
});
document.getElementById('preset_del').addEventListener('click',()=>{
  if(!psel.value){st('✗ pick a preset',false);return;}
  preset('delete',psel.value).then(()=>{loadPresetNames();st('● preset deleted',true);}).catch(()=>st('✗ delete failed',false));
});
</script>
</body>
</html>""".encode("utf-8")


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
        "center_line_target":   o._center_line_target,
        "default_color":        o._default_hex,
        "distance_colors":      o._distance_colors,
        "color_near":           _rgb_to_hex(o._color_near),
        "color_far":            _rgb_to_hex(o._color_far),
        "distance_max_px":      int(o._distance_max_px or 0),
        "box_style":            o._box_style,
        "box_corner_len":       o._box_corner_len,
        "box_fill":             o._box_fill,
        "center_line_style":    o._center_line_style,
        "center_line_dashed":   o._center_line_dashed,
        "center_line_arrow":    o._center_line_arrow,
        "crosshair":            o._crosshair,
        "crosshair_size":       o._crosshair_size,
        "crosshair_gap":        o._crosshair_gap,
        "crosshair_color":      o._crosshair_hex,
        "proximity_color":      o._proximity_hex,
        "magnifier_color":      o._magnifier_hex,
        "fps_color":            o._fps_hex,
        "label_font_size":      o._label_font_size,
        "trails":               o._trails,
        "trail_len":            o._trail_len,
    }


def _apply(o, data: dict) -> None:
    _INT = {
        "box_thickness":          (1,  20),
        "center_line_width":      (1,  20),
        "magnifier_radius":       (8,  400),
        "proximity_radius_px":    (1,  2000),
        "proximity_border_width": (1,  80),
        "box_corner_len":         (4,  200),
        "crosshair_size":         (0,  200),
        "crosshair_gap":          (0,  200),
        "label_font_size":        (6,  48),
        "trail_len":              (2,  200),
    }
    _FLOAT = {
        "magnifier_zoom":    (1.0, 10.0),
        "proximity_flash_hz": (0.1, 60.0),
    }
    _BOOL = [
        "show_labels", "show_confidence", "show_fps", "show_center_lines",
        "magnifier", "magnifier_hold_rmb", "proximity_flash", "distance_colors",
        "box_fill", "center_line_dashed", "center_line_arrow", "crosshair", "trails",
    ]
    # HUD color pickers that map straight to a "_<name>_hex" overlay attribute.
    _HEX = {
        "crosshair_color":  "_crosshair_hex",
        "proximity_color":  "_proximity_hex",
        "magnifier_color":  "_magnifier_hex",
        "fps_color":        "_fps_hex",
    }
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
    if data.get("center_line_target") in ("box_center", "top_center"):
        o._center_line_target = data["center_line_target"]
    if data.get("box_style") in ("solid", "corners", "dashed"):
        o._box_style = data["box_style"]
    if data.get("center_line_style") in ("corners", "target"):
        o._center_line_style = data["center_line_style"]
    for key, attr in _HEX.items():
        if key in data:
            v = str(data[key])
            if len(v) == 7 and v[0] == "#":  # reject anything that isn't #rrggbb
                setattr(o, attr, v)
    if "default_color" in data:
        o._default_rgb = _hex_to_rgb(str(data["default_color"]))
        o._default_hex = _rgb_to_hex(o._default_rgb)
    if "color_near" in data:
        o._color_near = _hex_to_rgb(str(data["color_near"]))
    if "color_far" in data:
        o._color_far = _hex_to_rgb(str(data["color_far"]))
    if "distance_max_px" in data:
        v = int(data["distance_max_px"])
        o._distance_max_px = v if v > 0 else None


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
            elif self.path == "/presets":
                self._send(200, json.dumps({"names": sorted(_read_presets())}).encode(), "application/json")
            else:
                self._send(404, b'{"error":"not found"}', "application/json")

        def do_POST(self):
            if self.path == "/save":
                try:
                    _STATE_PATH.write_text(json.dumps(_snapshot(overlay), indent=2))
                    self._send(200, b'{"ok":true}', "application/json")
                except Exception:
                    self._send(500, b'{"error":"write failed"}', "application/json")
                return
            if self.path == "/preset":
                n = int(self.headers.get("Content-Length", 0))
                try:
                    data = json.loads(self.rfile.read(n))
                except Exception:
                    self._send(400, b'{"error":"bad json"}', "application/json")
                    return
                op = data.get("op")
                name = str(data.get("name", "")).strip()[:40]
                presets = _read_presets()
                if op == "save" and name:
                    presets[name] = _snapshot(overlay)
                    _write_presets(presets)
                elif op == "load" and name in presets:
                    _apply(overlay, presets[name])
                elif op == "delete" and name in presets:
                    del presets[name]
                    _write_presets(presets)
                self._send(200, json.dumps({"names": sorted(presets)}).encode(), "application/json")
                return
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


def load_saved(overlay_app) -> None:
    """Re-apply HUD settings saved by a previous session (if any).

    Call this after building the overlay but BEFORE show(), so persisted state
    (e.g. magnifier on) is in place when the paint/worker threads start.
    """
    inner = getattr(overlay_app, "_overlay", overlay_app)
    if not _STATE_PATH.exists():
        return
    try:
        _apply(inner, json.loads(_STATE_PATH.read_text()))
    except Exception:  # corrupt/partial file — ignore, fall back to defaults
        pass


def start(overlay_app, port: int = 5000) -> None:
    """Launch the HUD web panel as a background daemon thread.

    overlay_app — the OverlayApp instance created in main.py
    """
    inner = overlay_app._overlay  # OverlayApp wraps Win32Overlay
    server = _make_server(inner, port)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="hud-server")
    t.start()
    print(f"  HUD panel:  http://localhost:{port}")
