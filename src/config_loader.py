"""Load YAML config with optional local overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> Dict[str, Any]:
    paths = [ROOT / "config" / "default.yaml", ROOT / "config" / "local.yaml"]
    merged: Dict[str, Any] = {}
    for p in paths:
        if p.exists():
            with p.open() as f:
                data = yaml.safe_load(f) or {}
            merged = _deep_merge(merged, data)
    return merged


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
