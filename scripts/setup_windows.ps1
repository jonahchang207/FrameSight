# One-time Windows setup: venv + dependencies
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "FrameSight - Windows setup" -ForegroundColor Cyan

function Resolve-PythonExe {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) {
            $exe = $exe.Trim()
            if (Test-Path -LiteralPath $exe) { return $exe }
        }
    }

    # PATH may list several python.exe entries; run --version on each (do not skip WindowsApps).
    $found = @()
    foreach ($name in @("python", "python3")) {
        $cmds = Get-Command $name -All -ErrorAction SilentlyContinue
        foreach ($cmd in $cmds) {
            if ($found -contains $cmd.Source) { continue }
            & $cmd.Source --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $found += $cmd.Source }
        }
    }
    $preferred = $found | Where-Object { $_ -notmatch "\\WindowsApps\\" } | Select-Object -First 1
    if ($preferred) { return $preferred }
    if ($found.Count -gt 0) { return $found[0] }

    return $null
}

$Python = Resolve-PythonExe
if (-not $Python) {
    throw @"
Python 3.10+ was not found.

1. Install from https://www.python.org/downloads/ and check "Add python.exe to PATH".
2. Turn off Store aliases: Settings -> Apps -> Advanced app settings ->
   App execution aliases -> disable python.exe and python3.exe.
3. Re-run: .\scripts\setup_windows.ps1
"@
}

Write-Host "Using: $Python" -ForegroundColor Gray

& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv (exit $LASTEXITCODE)." }

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Virtual environment missing at $VenvPython"
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)." }

& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)." }

$gpuNames = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
$gpuLine = ($gpuNames | Where-Object { $_ }) -join ", "
if ($gpuLine) {
    Write-Host "GPUs: $gpuLine" -ForegroundColor Gray
}
if ($gpuLine -match "AMD|Radeon|Intel|Arc") {
    Write-Host "AMD/Intel GPU: installing ONNX DirectML for overlay inference" -ForegroundColor Cyan
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & $VenvPython -m pip uninstall -y onnxruntime *> $null
    $ErrorActionPreference = $prevEap
    & $VenvPython -m pip install "onnxruntime-directml>=1.17.0"
    if ($LASTEXITCODE -ne 0) { throw "onnxruntime-directml install failed (exit $LASTEXITCODE)." }
}

& $VenvPython -c "from src.device_utils import detect_accelerator; a=detect_accelerator(); print('Accelerator:', a.message)"
if ($LASTEXITCODE -ne 0) { throw "Accelerator check failed (exit $LASTEXITCODE)." }

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
