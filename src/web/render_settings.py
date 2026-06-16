"""Thread-safe, live-editable rendering settings shared by the dashboard.

The inference/player threads read a snapshot every frame; the HTTP API mutates
it. Everything here is plain JSON-serialisable data so the same snapshot feeds
both the renderer and the ``/api/settings`` endpoint.
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Dict, Iterable, Tuple


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clean_color(value: Any, fallback: Iterable[int]) -> list[int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [int(_clamp(int(value[i]), 0, 255)) for i in range(3)]
    return [int(c) for c in fallback]


class RenderSettings:
    """Holds per-class colours/visibility plus global draw options."""

    def __init__(
        self,
        class_names: Dict[int, str],
        default_color: Iterable[int] = (0, 255, 128),
        class_colors: Dict[str, Iterable[int]] | None = None,
        conf: float = 0.35,
        thickness: int = 2,
        show_labels: bool = True,
        show_confidence: bool = True,
    ) -> None:
        self._lock = threading.Lock()
        class_colors = class_colors or {}
        default_color = list(default_color)

        classes: Dict[str, Dict[str, Any]] = {}
        # Preserve class order by id so the dashboard lists them deterministically.
        for cid in sorted(class_names):
            name = class_names[cid]
            color = _clean_color(class_colors.get(name), default_color)
            classes[name] = {"color": color, "enabled": True}

        self._data: Dict[str, Any] = {
            "conf": float(_clamp(conf, 0.0, 1.0)),
            "thickness": int(_clamp(thickness, 1, 12)),
            "show_labels": bool(show_labels),
            "show_confidence": bool(show_confidence),
            "default_color": _clean_color(default_color, (0, 255, 128)),
            "classes": classes,
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def update_from_dict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a partial update (only known keys), clamped to valid ranges."""
        if not isinstance(payload, dict):
            return self.snapshot()
        with self._lock:
            if "conf" in payload:
                self._data["conf"] = float(_clamp(float(payload["conf"]), 0.0, 1.0))
            if "thickness" in payload:
                self._data["thickness"] = int(_clamp(int(payload["thickness"]), 1, 12))
            if "show_labels" in payload:
                self._data["show_labels"] = bool(payload["show_labels"])
            if "show_confidence" in payload:
                self._data["show_confidence"] = bool(payload["show_confidence"])
            if "default_color" in payload:
                self._data["default_color"] = _clean_color(
                    payload["default_color"], self._data["default_color"]
                )
            classes = payload.get("classes")
            if isinstance(classes, dict):
                for name, style in classes.items():
                    if name not in self._data["classes"] or not isinstance(style, dict):
                        continue
                    target = self._data["classes"][name]
                    if "color" in style:
                        target["color"] = _clean_color(style["color"], target["color"])
                    if "enabled" in style:
                        target["enabled"] = bool(style["enabled"])
            return copy.deepcopy(self._data)

    def class_style(self, label: str) -> Tuple[list[int], bool]:
        """Colour + visibility for a label, falling back to the default colour."""
        with self._lock:
            cls = self._data["classes"].get(label)
            if cls is None:
                return list(self._data["default_color"]), True
            return list(cls["color"]), bool(cls["enabled"])
