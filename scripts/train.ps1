# Train YOLO locally on Windows (requires NVIDIA GPU recommended)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run scripts\setup_windows.ps1 first."
}

if (-not (Test-Path "fn.v1i.yolov8\data.yaml")) {
    throw "Dataset missing. Copy fn.v1i.yolov8\ into $Root"
}

Write-Host "Starting training (this may take a while)..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe scripts\train_local.py
