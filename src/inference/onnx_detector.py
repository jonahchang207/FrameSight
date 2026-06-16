"""Lean ONNX Runtime detector — bypasses Ultralytics' per-call overhead.

Ultralytics ``model.predict()`` wraps every frame in result objects, plotting
hooks, and bookkeeping whose Python cost is large *relative to* a nano model's
actual compute. This path drives the exported YOLO graph directly through
onnxruntime with manual letterbox preprocessing, output decoding, and NMS —
plus optional IOBinding to keep buffers on the GPU. On DirectML that's a
meaningful win on small models.

Implements the same surface as :class:`YoloDetector`: ``predict(bgr)`` and
``names``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np
import onnxruntime as ort

from src.inference.detector import Detection


def _imgsz_pair(imgsz: int | tuple[int, int] | list[int]) -> tuple[int, int]:
    """Normalize an imgsz spec to ``(height, width)``. An int means square."""
    if isinstance(imgsz, (list, tuple)):
        return int(imgsz[0]), int(imgsz[1])
    return int(imgsz), int(imgsz)


def _letterbox(
    img: np.ndarray,
    net_h: int,
    net_w: int,
    color: tuple[int, int, int] = (114, 114, 114),
) -> tuple[np.ndarray, float, float, float]:
    """Resize+pad to a ``net_h`` x ``net_w`` canvas (matches Ultralytics LetterBox, scaleup=True).

    When the net's aspect ratio matches the input (e.g. a 16:9 model fed a 16:9
    capture region), there is no padding at all — every model pixel is real image.
    """
    h, w = img.shape[:2]
    r = min(net_h / h, net_w / w)
    new_w, new_h = round(w * r), round(h * r)
    dw = (net_w - new_w) / 2.0
    dh = (net_h - new_h) / 2.0
    if (w, h) != (new_w, new_h):
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    img = cv2.copyMakeBorder(
        img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color
    )
    return img, r, float(left), float(top)


def _nms(
    x1: np.ndarray, y1: np.ndarray, x2: np.ndarray, y2: np.ndarray,
    scores: np.ndarray, iou_thr: float,
) -> list[int]:
    """Greedy NMS, returns kept indices (scores already filtered by conf)."""
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thr]
    return keep


class OnnxDetector:
    def __init__(
        self,
        onnx_path: str | Path,
        imgsz: int | tuple[int, int] | list[int] = 640,
        conf: float = 0.35,
        iou: float = 0.45,
        max_det: int = 300,
        agnostic_nms: bool = False,
        providers: list[str] | None = None,
        io_binding: bool = False,
    ) -> None:
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = providers or ["CPUExecutionProvider"]
        # Use the unpatched constructor if present: detector_factory monkeypatches
        # ort.InferenceSession to force DML on CPU requests (for Ultralytics), which
        # would hijack our explicit providers and defeat the CPU fallback below.
        self._make_session = getattr(ort, "_framesight_orig_session", ort.InferenceSession)
        self._so = so
        self._onnx_path = str(onnx_path)
        self._on_cpu = False
        try:
            self._sess = self._make_session(
                self._onnx_path, sess_options=so, providers=providers
            )
        except Exception:
            # GPU provider failed to initialize — fall back to CPU so the app runs.
            self._rebuild_on_cpu()
        self._providers = self._sess.get_providers()

        inp = self._sess.get_inputs()[0]
        self._in_name = inp.name
        self._out_name = self._sess.get_outputs()[0].name
        # ONNX is a static graph; trust its input H/W over the requested one. The
        # graph may be square (imgsz=480) or rectangular (e.g. 288x512 for 16:9).
        net_h, net_w = _imgsz_pair(imgsz)
        self._net_h = int(inp.shape[2]) if isinstance(inp.shape[2], int) else net_h
        self._net_w = int(inp.shape[3]) if isinstance(inp.shape[3], int) else net_w
        self._in_dtype = np.float16 if "float16" in inp.type else np.float32

        # IOBinding keeps a single input buffer resident on the GPU and reuses it
        # every frame (update_inplace) instead of re-allocating + re-uploading on
        # each run() call. OFF by default: on some AMD DirectML drivers binding a
        # device OrtValue triggers a GPU device-removal ("device suspended"),
        # which forces the whole session onto CPU — far worse than the copy it
        # saves. Opt in via model.io_binding only if it's stable on your driver.
        # Disabled and torn down on any failure so it never kills the GPU path.
        self._use_binding = bool(io_binding) and "DmlExecutionProvider" in self._providers
        self._io = None
        self._dev_input = None

        self._conf = conf
        self._iou = iou
        self._max_det = max_det
        self._agnostic = agnostic_nms

        meta = self._sess.get_modelmeta().custom_metadata_map
        self._names: Dict[int, str] = {}
        if "names" in meta:
            try:
                parsed = ast.literal_eval(meta["names"])
                self._names = {int(k): str(v) for k, v in parsed.items()}
            except (ValueError, SyntaxError):
                self._names = {}

    def _rebuild_on_cpu(self) -> None:
        """Recreate the session on the CPU EP (used when DirectML init/run fails)."""
        self._sess = self._make_session(
            self._onnx_path, sess_options=self._so, providers=["CPUExecutionProvider"]
        )
        self._on_cpu = True
        self._providers = self._sess.get_providers()

    @property
    def names(self) -> Dict[int, str]:
        return dict(self._names)

    def predict(self, bgr: np.ndarray) -> List[Detection]:
        if bgr is None or bgr.size == 0 or bgr.shape[0] < 2 or bgr.shape[1] < 2:
            return []
        oh, ow = bgr.shape[:2]
        img, r, padx, pady = _letterbox(bgr, self._net_h, self._net_w)
        blob = np.ascontiguousarray(
            img[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32
        )
        blob /= 255.0
        if self._in_dtype != np.float32:
            blob = blob.astype(self._in_dtype)

        out = self._infer(blob)
        if out is None:
            return []
        return self._decode(np.asarray(out, dtype=np.float32), r, padx, pady, ow, oh)

    def _infer(self, blob: np.ndarray) -> np.ndarray | None:
        """Run the session, preferring GPU IOBinding, returning the raw output."""
        if self._use_binding:
            try:
                return self._run_bound(blob)
            except Exception:  # noqa: BLE001
                # IOBinding unsupported on this driver/ORT build (or the device
                # hung). Disable it, drop the buffers, and retry via plain run().
                self._use_binding = False
                self._io = None
                self._dev_input = None

        try:
            return self._sess.run([self._out_name], {self._in_name: blob})[0]
        except Exception as exc:  # noqa: BLE001
            if self._on_cpu:
                return None  # already on CPU and still failing — give up this frame
            # DirectML hung/removed the device. Rebuild once on CPU so the app
            # keeps running instead of killing the inference thread.
            print(
                "\nDirectML inference failed (GPU device hung). Falling back to CPU.\n"
                "  This often means FP16 is unstable on this driver — set "
                "model.half: false in your config for FP32 on the GPU instead.\n"
                f"  ({type(exc).__name__})"
            )
            try:
                self._rebuild_on_cpu()
                return self._sess.run([self._out_name], {self._in_name: blob})[0]
            except Exception:
                return None

    def _run_bound(self, blob: np.ndarray) -> np.ndarray:
        """Run via IOBinding, reusing a GPU-resident input buffer across frames."""
        if self._io is None:
            # First frame: allocate the device buffer and wire the binding once.
            self._dev_input = ort.OrtValue.ortvalue_from_numpy(blob, "dml", 0)
            self._io = self._sess.io_binding()
            self._io.bind_ortvalue_input(self._in_name, self._dev_input)
            self._io.bind_output(self._out_name, "dml")
        else:
            # Reuse the existing GPU allocation — just refill it with this frame.
            self._dev_input.update_inplace(blob)
        self._sess.run_with_iobinding(self._io)
        return self._io.copy_outputs_to_cpu()[0]

    def _decode(
        self, out: np.ndarray, r: float, padx: float, pady: float, ow: int, oh: int,
    ) -> List[Detection]:
        preds = out[0].T  # [anchors, 4 + nc]
        scores_all = preds[:, 4:]
        cls = scores_all.argmax(1)
        conf = scores_all[np.arange(scores_all.shape[0]), cls]
        keep = conf >= self._conf
        if not np.any(keep):
            return []
        boxes = preds[keep, :4]
        cls = cls[keep]
        conf = conf[keep]

        # xywh(center, letterbox px) -> xyxy in original-region px
        cx, cy, bw, bh = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        x1 = (cx - bw / 2.0 - padx) / r
        y1 = (cy - bh / 2.0 - pady) / r
        x2 = (cx + bw / 2.0 - padx) / r
        y2 = (cy + bh / 2.0 - pady) / r
        x1 = np.clip(x1, 0, ow); x2 = np.clip(x2, 0, ow)
        y1 = np.clip(y1, 0, oh); y2 = np.clip(y2, 0, oh)

        # Class-aware NMS via per-class coordinate offset (skipped if agnostic).
        if self._agnostic:
            ox1, oy1, ox2, oy2 = x1, y1, x2, y2
        else:
            shift = cls.astype(np.float32) * (max(ow, oh) + 1.0)
            ox1, oy1, ox2, oy2 = x1 + shift, y1 + shift, x2 + shift, y2 + shift
        kept = _nms(ox1, oy1, ox2, oy2, conf, self._iou)
        if len(kept) > self._max_det:
            kept = kept[: self._max_det]

        out_dets: List[Detection] = []
        for i in kept:
            cid = int(cls[i])
            out_dets.append(
                Detection(
                    x1=int(round(float(x1[i]))),
                    y1=int(round(float(y1[i]))),
                    x2=int(round(float(x2[i]))),
                    y2=int(round(float(y2[i]))),
                    confidence=float(conf[i]),
                    class_id=cid,
                    label=self._names.get(cid, str(cid)),
                )
            )
        return out_dets
