"""TurnEvent recording (AR-LANG-014): one redacted line per voice turn, kept on this PC.

No audio is ever written here. The transcript is redacted before it reaches disk (emails, URLs and
long digit runs such as card or phone numbers). A turn that failed can be exported as a fixture
file so the failure becomes a regression test. Recording can be turned off in settings.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reva_core.shared.logging import get_logger

logger = get_logger("turn_log")

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 8
MAX_TRANSCRIPT_CHARS = 500

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"(?:\d[ -]?){6,}\d")
OK_OUTCOMES = frozenset({"ok"})


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub("[url]", text)
    text = _DIGIT_RUN.sub("[number]", text)
    return text[:MAX_TRANSCRIPT_CHARS]


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    session_id: str
    device_id: str
    turn_epoch: int
    outcome: str  # ok | stt_empty | stt_unavailable | stt_timeout | model_failed | superseded ...
    route: str | None = None  # router turn kind, "chat" for the model path
    transcript: str = ""
    language: str | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)
    at: str = ""


class TurnRecorder:
    def __init__(self, directory: Path, *, enabled: bool = True) -> None:
        self._directory = Path(directory)
        self._enabled = enabled

    def record(self, record: TurnRecord) -> None:
        if not self._enabled:
            return
        row = asdict(record)
        row["transcript"] = redact(record.transcript)
        row["at"] = record.at or datetime.now(UTC).isoformat()
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            path = self._current_file()
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
            self._prune()
        except OSError:
            logger.warning("turn record could not be written")

    def read(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            files = sorted(self._directory.glob("turns-*.jsonl"))
        except OSError:
            return rows
        for file in files:
            try:
                for line in file.read_text(encoding="utf-8").splitlines():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue
        return rows

    def export_failed_fixtures(self, destination: Path) -> list[Path]:
        """Write each failed turn as `<turn_id>.json` (redacted transcript, outcome, timings)."""
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for row in self.read():
            if row.get("outcome") in OK_OUTCOMES:
                continue
            name = re.sub(r"[^A-Za-z0-9_-]", "", str(row.get("turn_id", "")))[:64] or "turn"
            target = destination / f"{name}.json"
            target.write_text(
                json.dumps(
                    {
                        "transcript": row.get("transcript", ""),
                        "outcome": row.get("outcome"),
                        "route": row.get("route"),
                        "timings_ms": row.get("timings_ms", {}),
                        "expected": None,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            written.append(target)
        return written

    def _current_file(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        index = 0
        while True:
            name = f"turns-{stamp}-{index}.jsonl"
            path = self._directory / name
            if not path.exists() or path.stat().st_size < MAX_FILE_BYTES:
                return path
            index += 1

    def _prune(self) -> None:
        files = sorted(self._directory.glob("turns-*.jsonl"))
        for old in files[:-MAX_FILES]:
            old.unlink(missing_ok=True)
