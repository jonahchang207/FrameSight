"""Detect GPU vendor and pick the best Ultralytics / ONNX Runtime device."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

Backend = Literal["cuda", "dml", "cpu"]
InferenceBackend = Literal["pytorch", "onnx_dml"]


@dataclass(frozen=True)
class AcceleratorInfo:
    """Resolved accelerator for training and live inference."""

    train_device: str  # ultralytics train(): "0", "cpu", etc.
    inference_backend: InferenceBackend
    inference_device: str  # ultralytics predict() device when using pytorch
    backend: Backend  # primary label for logging
    gpu_names: tuple[str, ...]
    vendors: tuple[str, ...]
    message: str


def _windows_gpu_names() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_VideoController).Name",
            ],
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def gpu_vendors(gpu_names: list[str] | None = None) -> tuple[str, ...]:
    """Return vendor tags seen on this machine: nvidia, amd, intel."""
    names = gpu_names if gpu_names is not None else _windows_gpu_names()
    vendors: set[str] = set()
    for name in names:
        lower = name.lower()
        if re.search(r"nvidia|geforce|rtx|gtx|quadro", lower):
            vendors.add("nvidia")
        if re.search(r"amd|radeon|rx\s*\d|7600", lower):
            vendors.add("amd")
        if re.search(r"intel|arc|iris|uhd", lower):
            vendors.add("intel")
    return tuple(sorted(vendors))


def cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def dml_available() -> bool:
    """True when ONNX Runtime DirectML provider is installed (AMD/Intel on Windows)."""
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    return "DmlExecutionProvider" in ort.get_available_providers()


def detect_accelerator() -> AcceleratorInfo:
    """Pick the best training + inference stack for this machine."""
    names = tuple(_windows_gpu_names())
    vendors = gpu_vendors(list(names))

    if cuda_available() and "nvidia" in vendors:
        return AcceleratorInfo(
            train_device="0",
            inference_backend="pytorch",
            inference_device="0",
            backend="cuda",
            gpu_names=names,
            vendors=vendors,
            message="NVIDIA CUDA",
        )

    if sys.platform == "win32" and dml_available() and set(vendors) & {"amd", "intel"}:
        vendor = "AMD" if "amd" in vendors else "Intel"
        return AcceleratorInfo(
            train_device="cpu",
            inference_backend="onnx_dml",
            inference_device="cpu",
            backend="dml",
            gpu_names=names,
            vendors=vendors,
            message=f"{vendor} GPU via ONNX DirectML (train on CPU; overlay uses GPU)",
        )

    if cuda_available():
        return AcceleratorInfo(
            train_device="0",
            inference_backend="pytorch",
            inference_device="0",
            backend="cuda",
            gpu_names=names,
            vendors=vendors,
            message="CUDA",
        )

    return AcceleratorInfo(
        train_device="cpu",
        inference_backend="pytorch",
        inference_device="cpu",
        backend="cpu",
        gpu_names=names,
        vendors=vendors,
        message="CPU",
    )


def resolve_device(requested: str | None = None) -> str:
    """Return an Ultralytics training device string."""
    req = str(requested or "").strip().lower()
    accel = detect_accelerator()

    if req in ("", "auto"):
        return accel.train_device
    if req == "cpu":
        return "cpu"
    if req in ("dml", "directml"):
        return "cpu"  # Ultralytics training does not support DirectML
    if req in ("cuda", "gpu") or req.isdigit() or "," in req:
        if cuda_available():
            return req if req not in ("cuda", "gpu") else "0"
        if accel.backend == "dml":
            return "cpu"
        return "cpu"
    return req


def resolve_inference(requested: str | None = None) -> AcceleratorInfo:
    """Return accelerator info for live overlay inference."""
    req = str(requested or "").strip().lower()
    accel = detect_accelerator()

    if req in ("", "auto"):
        return accel
    if req == "cpu":
        return AcceleratorInfo(
            train_device="cpu",
            inference_backend="pytorch",
            inference_device="cpu",
            backend="cpu",
            gpu_names=accel.gpu_names,
            vendors=accel.vendors,
            message="CPU (forced)",
        )
    if req in ("dml", "directml") and dml_available():
        return AcceleratorInfo(
            train_device="cpu",
            inference_backend="onnx_dml",
            inference_device="cpu",
            backend="dml",
            gpu_names=accel.gpu_names,
            vendors=accel.vendors,
            message="DirectML (forced)",
        )
    if req in ("cuda", "gpu", "0") or req.isdigit():
        if cuda_available():
            dev = "0" if req in ("cuda", "gpu") else req
            return AcceleratorInfo(
                train_device=dev,
                inference_backend="pytorch",
                inference_device=dev,
                backend="cuda",
                gpu_names=accel.gpu_names,
                vendors=accel.vendors,
                message=f"CUDA device {dev} (forced)",
            )
    return accel
