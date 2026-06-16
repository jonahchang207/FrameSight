"""Create the best detector for the current GPU (CUDA, DirectML, or CPU)."""

from __future__ import annotations

import sys
from pathlib import Path

from src.device_utils import AcceleratorInfo, resolve_inference
from src.inference.detector import YoloDetector
from src.inference.onnx_detector import OnnxDetector

_BOOTSTRAPPED = False


def bootstrap_directml() -> None:
    """Install patches so Ultralytics ONNX uses DirectML (AMD/Intel on Windows)."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _patch_ultralytics_requirements()
    _patch_onnxruntime_for_dml()
    _BOOTSTRAPPED = True


def _patch_ultralytics_requirements() -> None:
    """Treat onnxruntime-directml as satisfying Ultralytics' onnxruntime check."""
    try:
        from ultralytics.utils import checks
    except ImportError:
        return
    if getattr(checks, "_framesight_req_patch", False):
        return

    original = checks.check_requirements
    onnx_aliases = ("onnxruntime", "onnxruntime-gpu", "onnxruntime-directml")

    def _is_onnxruntime_req(req: object) -> bool:
        if isinstance(req, str):
            return req == "onnxruntime" or req.startswith("onnxruntime")
        if isinstance(req, (list, tuple)):
            return any(_is_onnxruntime_req(x) for x in req)
        return False

    from ultralytics.utils import ROOT

    def _wrapped(requirements=ROOT.parent / "requirements.txt", exclude=(), install=True, cmds=""):
        if isinstance(requirements, (list, tuple)):
            requirements = [
                onnx_aliases if _is_onnxruntime_req(r) else r for r in requirements
            ]
        elif isinstance(requirements, str) and _is_onnxruntime_req(requirements):
            requirements = [onnx_aliases]
        return original(requirements, exclude=exclude, install=install, cmds=cmds)

    checks.check_requirements = _wrapped  # type: ignore[method-assign, assignment]
    checks._framesight_req_patch = True

    # Submodules import check_requirements by value; update those references too.
    for mod in list(sys.modules.values()):
        if mod is not None and getattr(mod, "check_requirements", None) is original:
            mod.check_requirements = _wrapped  # type: ignore[attr-defined]


def _patch_onnxruntime_for_dml() -> None:
    """Prefer DirectML when Ultralytics loads an ONNX model (Windows AMD/Intel)."""
    import onnxruntime as ort

    if getattr(ort, "_framesight_dml_patch", False):
        return

    original = ort.InferenceSession
    # Expose the unpatched constructor so OnnxDetector can request exact providers
    # (and a genuine CPU fallback) without this DML-forcing wrapper intercepting it.
    ort._framesight_orig_session = original

    def _session(path, sess_options=None, providers=None, provider_options=None, **kwargs):
        available = ort.get_available_providers()
        if "DmlExecutionProvider" in available:
            use_cpu_only = providers == ["CPUExecutionProvider"]
            if providers is None or use_cpu_only:
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif providers is None:
            providers = ["CPUExecutionProvider"]
        return original(
            path,
            sess_options=sess_options,
            providers=providers,
            provider_options=provider_options,
            **kwargs,
        )

    ort.InferenceSession = _session  # type: ignore[method-assign, assignment]
    ort._framesight_dml_patch = True

    try:
        from ultralytics.nn.backends import onnx as onnx_backend

        _orig_load = onnx_backend.ONNXBackend.load_model

        def _load_model(self, weight):  # type: ignore[no-untyped-def]
            _orig_load(self, weight)
            if self.format == "onnx" and hasattr(self, "session"):
                active = self.session.get_providers()
                if active and active[0] == "DmlExecutionProvider":
                    from ultralytics.utils import LOGGER

                    LOGGER.info(
                        f"FrameSight: ONNX Runtime {ort.__version__} using DirectML (AMD/Intel GPU)"
                    )

        onnx_backend.ONNXBackend.load_model = _load_model  # type: ignore[method-assign]
    except ImportError:
        pass


def _imgsz_hw(imgsz: int | tuple[int, int] | list[int]) -> tuple[int, int]:
    """Normalize an imgsz spec to ``(height, width)``. An int means square."""
    if isinstance(imgsz, (list, tuple)):
        return int(imgsz[0]), int(imgsz[1])
    return int(imgsz), int(imgsz)


def _imgsz_tag(h: int, w: int) -> str:
    """Filename tag: ``480`` for a square net, ``288x512`` for a rectangular one."""
    return str(h) if h == w else f"{h}x{w}"


def _onnx_path_for_weights(weights: Path, imgsz: int | tuple[int, int] | list[int]) -> Path:
    """ONNX export path includes imgsz — static ONNX graphs are fixed to one input size."""
    h, w = _imgsz_hw(imgsz)
    return weights.parent / f"{weights.stem}_{_imgsz_tag(h, w)}.onnx"


def _onnx_input_hw(onnx_path: Path) -> tuple[int, int] | None:
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )
        shape = sess.get_inputs()[0].shape
        if len(shape) >= 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
            return int(shape[2]), int(shape[3])
    except Exception:
        return None
    return None


def _resolve_onnx_path(weights: Path, imgsz: int | tuple[int, int] | list[int]) -> Path | None:
    """Return an existing ONNX file that matches imgsz, if weights are up to date."""
    target_hw = _imgsz_hw(imgsz)
    candidates = [
        _onnx_path_for_weights(weights, imgsz),
        weights.with_suffix(".onnx"),  # legacy: best.onnx
    ]
    pt_mtime = weights.stat().st_mtime
    for path in candidates:
        if not path.exists() or path.stat().st_mtime < pt_mtime:
            continue
        if _onnx_input_hw(path) == target_hw:
            return path
    return None


def ensure_onnx_export(weights: Path, imgsz: int | tuple[int, int] | list[int]) -> Path:
    """Export .pt to .onnx for DirectML (re-exports when imgsz changes)."""
    bootstrap_directml()
    existing = _resolve_onnx_path(weights, imgsz)
    if existing is not None:
        return existing

    onnx_path = _onnx_path_for_weights(weights, imgsz)
    from ultralytics import YOLO

    h, w = _imgsz_hw(imgsz)
    # Ultralytics export takes a [h, w] list for a rectangular graph, or an int
    # for square. Feeding a 16:9 [h, w] eliminates letterbox padding entirely.
    export_imgsz = h if h == w else [h, w]
    print(f"Exporting ONNX for imgsz={export_imgsz} -> {onnx_path.name}")
    YOLO(str(weights)).export(format="onnx", imgsz=export_imgsz, simplify=True)
    default_export = weights.with_suffix(".onnx")
    if default_export.exists() and default_export != onnx_path:
        if onnx_path.exists():
            onnx_path.unlink()
        default_export.replace(onnx_path)
    if not onnx_path.exists():
        raise FileNotFoundError(f"ONNX export failed: expected {onnx_path}")
    return onnx_path


def ensure_fp16_onnx(fp32_path: Path) -> Path:
    """Convert an FP32 ONNX graph to FP16 (compute in half, IO stays float32).

    RDNA3/recent GPUs run FP16 ~1.5-2x faster on DirectML. ``keep_io_types``
    leaves the model's input/output float32, so preprocessing is unchanged and
    only the internal compute is halved. Re-converts when the FP32 file changes.
    """
    fp16_path = fp32_path.with_name(f"{fp32_path.stem}_fp16.onnx")
    if fp16_path.exists() and fp16_path.stat().st_mtime >= fp32_path.stat().st_mtime:
        return fp16_path

    import onnx
    from onnxruntime.transformers.float16 import convert_float_to_float16

    print(f"Converting ONNX to FP16 -> {fp16_path.name}")
    model = onnx.load(str(fp32_path))
    onnx.save(convert_float_to_float16(model, keep_io_types=True), str(fp16_path))
    return fp16_path


def create_detector(
    weights: Path,
    imgsz: int | tuple[int, int] | list[int],
    conf: float,
    iou: float,
    device_requested: str | None = None,
    max_det: int = 300,
    agnostic_nms: bool = False,
    half: bool = True,
    io_binding: bool = False,
):
    """Build a detector using CUDA, DirectML (lean ONNX Runtime), or CPU."""
    accel: AcceleratorInfo = resolve_inference(device_requested)

    if accel.inference_backend == "onnx_dml":
        bootstrap_directml()
        pt_path = weights
        if weights.suffix.lower() != ".pt":
            pt_candidate = weights.with_suffix(".pt")
            if pt_candidate.exists():
                pt_path = pt_candidate
        if pt_path.suffix.lower() == ".pt" and pt_path.exists():
            onnx_path = ensure_onnx_export(pt_path, imgsz)
        elif weights.suffix.lower() == ".onnx" and weights.exists():
            onnx_path = weights
        else:
            raise FileNotFoundError(
                f"No .pt weights to export for DirectML: {weights}\n"
                r"Train first (.\scripts\train.ps1) or place weights/best.pt"
            )
        precision = "FP32"
        if half:
            try:
                onnx_path = ensure_fp16_onnx(onnx_path)
                precision = "FP16"
            except Exception as exc:  # noqa: BLE001
                print(f"FP16 conversion failed ({exc}); using FP32 ONNX")
        print(f"Inference: {accel.message} ({onnx_path.name}) [lean ORT, {precision}]")
        return OnnxDetector(
            onnx_path=onnx_path,
            imgsz=imgsz,
            conf=conf,
            iou=iou,
            max_det=max_det,
            agnostic_nms=agnostic_nms,
            providers=["DmlExecutionProvider", "CPUExecutionProvider"],
            io_binding=io_binding,
        )

    print(f"Inference: {accel.message}")
    return YoloDetector(
        weights=weights,
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        device=accel.inference_device,
        max_det=max_det,
        agnostic_nms=agnostic_nms,
    )


# Patch before any Ultralytics ONNX load when DirectML is installed (Windows AMD/Intel).
if sys.platform == "win32":
    try:
        from src.device_utils import dml_available

        if dml_available():
            bootstrap_directml()
    except ImportError:
        pass
