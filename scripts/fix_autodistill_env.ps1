# Repair AutoDistill env after OWLv2 installs broken transformers 5.x dev
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Write-Host "Fixing AutoDistill dependencies..." -ForegroundColor Cyan

& $Python -m pip uninstall -y transformers 2>$null
& $Python -m pip install "transformers>=4.40.0,<5.0.0" "torch>=2.1.0" "torchvision>=0.16.0"
& $Python -m pip install -r requirements-autodistill.txt

Write-Host "Verifying OWL-ViT import..." -ForegroundColor Cyan
& $Python -c @"
from autodistill.detection import CaptionOntology
from autodistill_owl_vit import OWLViT
import transformers
m = OWLViT(ontology=CaptionOntology({'person': 'body'}))
print('OK  transformers', transformers.__version__)
"@

Write-Host "Done. Use base_model: owlvit in config/autodistill.yaml" -ForegroundColor Green
