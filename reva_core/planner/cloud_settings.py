"""Persistent opt-in flag. API credentials are never stored in this file."""

from __future__ import annotations

import json
import os
from pathlib import Path


class CloudReasoningSettings:
    disclosure = {
        "text": "Final transcript and capability list (names and argument schemas)",
        "audio": "Never",
        "screens": "Never",
        "memory": "Never",
        "domain_data": "Never",
    }

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "cloud_reasoning.json"

    @property
    def enabled(self) -> bool:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            return value.get("enabled") is True
        except (OSError, ValueError, AttributeError):
            return False

    def set_enabled(self, enabled: bool) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
        os.replace(temporary, self._path)
