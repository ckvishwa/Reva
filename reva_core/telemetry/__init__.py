"""Opt-in, redacted, removable local telemetry (AR-CORE-013, NFR-016).

* **Off by default.** Nothing is written until the owner switches it on in Settings.
* **Local only.** Events are lines in files under `<data>/telemetry/` on this PC. This module has no
  network code at all (a test checks its imports); nothing here ever leaves the machine.
* **Redacted by construction.** An event is a name from a fixed list plus a few typed fields from a
  fixed list (a success flag, a duration, a taxonomy error code). There is no field for text, a
  transcript, an id, an amount, a path or a device. Anything else passed in is dropped, not kept.
* **Removable.** One call deletes every telemetry file and turns the switch off.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reva_core.shared.errors import StorageError

ALLOWED_EVENTS = frozenset(
    {
        "core.start",
        "core.stop",
        "http.error",
        "voice.turn",
        "action.outcome",
        "stt.fallback",
        "cloud.fallback",
        "migration.applied",
    }
)
# field -> checker. A value that fails its checker is dropped.
_ERROR_CODE = re.compile(r"^[A-Z]+\.[A-Z_]{2,32}$")
_STATUS = frozenset({"verified", "failed", "unknown", "denied", "expired", "refused", "ok"})
_FIELDS: dict[str, Any] = {
    "ok": lambda v: isinstance(v, bool),
    "duration_ms": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 3_600_000,
    "code": lambda v: isinstance(v, str) and bool(_ERROR_CODE.match(v)),
    "status": lambda v: isinstance(v, str) and v in _STATUS,
    "count": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1_000_000,
}
SETTINGS_FILE = "telemetry.json"
DIRECTORY = "telemetry"
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 14


class Telemetry:
    def __init__(self, data_dir: Path, clock: Any = None) -> None:
        self._root = Path(data_dir)
        self._dir = self._root / DIRECTORY
        self._lock = threading.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))

    # ---------------------------------------------------------------- the switch

    @property
    def enabled(self) -> bool:
        try:
            raw = json.loads((self._root / SETTINGS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(raw, dict) and raw.get("enabled") is True

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._set_enabled(enabled)

    def _set_enabled(self, enabled: bool) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self._root / (SETTINGS_FILE + ".tmp")
        temporary.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
        os.replace(temporary, self._root / SETTINGS_FILE)

    # ---------------------------------------------------------------- recording

    def record(self, name: str, **fields: object) -> bool:
        """Write one event if telemetry is on. Returns whether it was written. Never raises."""
        if name not in ALLOWED_EVENTS:
            return False
        clean = {k: v for k, v in fields.items() if k in _FIELDS and _FIELDS[k](v)}
        now = self._clock()
        row = {"event": name, "day": now.strftime("%Y-%m-%d"), **clean}  # a day, not a time
        try:
            with self._lock:
                if not self.enabled:
                    return False
                self._dir.mkdir(parents=True, exist_ok=True)
                path = self._dir / f"events-{now.strftime('%Y%m%d')}.jsonl"
                if path.exists() and path.stat().st_size >= MAX_FILE_BYTES:
                    return False  # a day's file is capped; the rest of the day is not recorded
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                self._prune()
        except OSError:
            return False
        return True

    def read(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            for path in sorted(self._dir.glob("events-*.jsonl")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        return rows

    # ---------------------------------------------------------------- removal

    def remove_all(self) -> int:
        """Delete every telemetry file and switch telemetry off. Returns files removed."""
        removed = 0
        with self._lock:
            try:
                self._set_enabled(False)
                for path in list(self._dir.glob("events-*.jsonl")):
                    path.unlink(missing_ok=True)
                    removed += 1
                if self._dir.exists() and not any(self._dir.iterdir()):
                    self._dir.rmdir()
            except OSError as exc:
                raise StorageError("telemetry removal failed; some records may remain") from exc
        return removed

    def _prune(self) -> None:
        files = sorted(self._dir.glob("events-*.jsonl"))
        for old in files[:-MAX_FILES]:
            old.unlink(missing_ok=True)
