$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
# onnxruntime-directml satisfies import; skip Ultralytics pip overwrite of that package
$env:ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS = "1"
.\.venv\Scripts\Activate.ps1
python -m src.main
