<#
.SYNOPSIS
    Train FrameSight specifically on the AMD Radeon RX 7600 XT (ROCm).

.DESCRIPTION
    Pins the discrete 7600 XT via HIP_VISIBLE_DEVICES (so training never lands on
    the integrated Radeon or the CPU), verifies a ROCm PyTorch build is present,
    then runs the normal training pipeline (scripts\train_local.py).

    The overlay is unaffected — it keeps using ONNX DirectML.

.PARAMETER Install
    Replace the CPU-only PyTorch with the ROCm (gfx1102 / Python 3.12) wheels
    before training. Run this once: .\scripts\train_gpu.ps1 -Install

.EXAMPLE
    .\scripts\train_gpu.ps1 -Install   # first time: install ROCm torch, then train
    .\scripts\train_gpu.ps1            # every time after: just train on the GPU
#>
[CmdletBinding()]
param(
    [switch]$Install
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "venv not found. Run scripts\setup_windows.ps1 first."
}

if (-not (Test-Path "fn.v1i.yolov8\data.yaml")) {
    throw "Dataset missing. Copy fn.v1i.yolov8\ into $Root"
}

# --- Optional: install the ROCm (gfx1102) PyTorch wheels ---------------------
if ($Install) {
    Write-Host "Installing ROCm PyTorch for gfx1102 (RX 7600 XT)..." -ForegroundColor Cyan
    $base = "https://github.com/scottt/rocm-TheRock/releases/download/v6.5.0rc-pytorch-gfx110x"
    & $Py -m pip uninstall -y torch torchvision torchaudio
    & $Py -m pip install `
        "$base/torch-2.7.0a0+git3f903c3-cp312-cp312-win_amd64.whl" `
        "$base/torchvision-0.22.0+9eb57cd-cp312-cp312-win_amd64.whl"
    if ($LASTEXITCODE -ne 0) { throw "ROCm wheel install failed." }
    # These ROCm wheels are built against NumPy 1.x; opencv declares numpy>=2 but
    # imports fine under 1.26 at runtime. Pin <2 so torch's numpy interop works.
    & $Py -m pip install "numpy<2"
    if ($LASTEXITCODE -ne 0) { throw "numpy<2 install failed." }
    Write-Host "ROCm PyTorch installed.`n" -ForegroundColor Green
}

# --- Find the discrete 7600 XT and confirm ROCm sees it ----------------------
Write-Host "Detecting AMD GPUs visible to ROCm..." -ForegroundColor Cyan
$lines = & $Py scripts\pick_amd_gpu.py
$lines | ForEach-Object { Write-Host "  $_" }

if ($lines -contains "NO_TORCH") {
    throw "PyTorch is not installed. Run:  .\scripts\train_gpu.ps1 -Install"
}
if ($lines -contains "NO_ROCM") {
    throw @"
ROCm PyTorch not detected (current torch is CPU-only or NVIDIA CUDA).
Install the AMD GPU build first:  .\scripts\train_gpu.ps1 -Install
"@
}

$pickLine = $lines | Where-Object { $_ -like "PICK=*" } | Select-Object -First 1
$pick = [int]($pickLine -replace "PICK=", "")
if ($pick -lt 0) {
    Write-Host "WARNING: No device named '7600' found; defaulting to GPU index 0." -ForegroundColor Yellow
    $pick = 0
}

# Pin the discrete card. After this, the training process sees it as device 0.
$env:HIP_VISIBLE_DEVICES = "$pick"
Write-Host "`nPinned RX 7600 XT (global index $pick) via HIP_VISIBLE_DEVICES=$pick" -ForegroundColor Green

# --- Train -------------------------------------------------------------------
Write-Host "Starting GPU training (Ctrl+C to stop)...`n" -ForegroundColor Cyan
& $Py scripts\train_local.py
exit $LASTEXITCODE
