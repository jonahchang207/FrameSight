# FrameSight AutoDistill pipeline (Windows)
# Usage:
#   1. Copy Valorant clips (.mp4) into data\videos\
#   2. .\scripts\autodistill.ps1
#   3. Upload data\autodistill\framesight_dataset.zip to Google Colab

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "Create venv first: .\scripts\setup_windows.ps1" -ForegroundColor Yellow
    $Python = "python"
}

$Req = Join-Path $Root "requirements-autodistill.txt"
Write-Host "Installing AutoDistill dependencies (one-time, may take several minutes)..." -ForegroundColor Cyan
& $Python -m pip install -r $Req

New-Item -ItemType Directory -Force -Path "data\videos" | Out-Null

& $Python scripts\autodistill_pipeline.py --zip --publish @args

Write-Host ""
Write-Host "Next: open colab\train_framesight.ipynb in Google Colab (GPU runtime)" -ForegroundColor Green
Write-Host "Upload: data\autodistill\framesight_dataset.zip" -ForegroundColor Green
