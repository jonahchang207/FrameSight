# One-time Windows setup: venv + dependencies
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "FrameSight — Windows setup" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found. Install Python 3.10+ from https://www.python.org/ (check Add to PATH)."
}

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host ""
if (Test-Path "fn.v1i.yolov8\data.yaml") {
    Write-Host "Dataset found: fn.v1i.yolov8\" -ForegroundColor Green
} else {
    Write-Host "Dataset missing: copy fn.v1i.yolov8\ into project root" -ForegroundColor Yellow
}

if (Test-Path "weights\best.pt") {
    Write-Host "Weights found: weights\best.pt" -ForegroundColor Green
} else {
    Write-Host "Train:  .\scripts\train.ps1" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Train:   .\scripts\train.ps1" -ForegroundColor Green
Write-Host "Run:     .\scripts\run.ps1" -ForegroundColor Green
