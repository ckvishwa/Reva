"""The action ledger: append-only rows of what was proposed, approved, granted, done (AR-AGT-010).

Two implementations of one small interface: SQLite (the Core's database; rows can never be
changed or removed, the migration's triggers refuse it) and memory (tests). Arguments are
redacted before they
reach a ledger: only values that are small enumerations stay readable (an app name, a period);
amounts, notes and any free text are replaced by a marker, so the ledger can be shown to the
user (Activity page) without becoming a second copy of their data.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol

from reva_core.policy.registry import Capability
from reva_core.shared.errors import StorageError

MAX_PAYLOAD_CHARS = 4000


@dataclass(frozen=True)
class LedgerRow:
    action_id: str
    seq: int
    at: str
    kind: str
    payload: dict[str, Any]


class ActionLedger(Protocol):
    def append(self, action_id: str, kind: str, at: str, payload: dict[str, Any]) -> LedgerRow: ...

    def rows(self, action_id: str) -> list[LedgerRow]: ...

    def recent(self, limit: int = 50) -> list[LedgerRow]: ...


def redact_args(capability: Capability, args: dict[str, Any]) -> dict[str, Any]:
    """Keep only values the schema limits to a fixed list; everything else is a marker."""
    properties = capability.args_schema.get("properties", {})
    safe: dict[str, Any] = {}
    for name, value in args.items():
        spec = properties.get(name, {})
        if "enum" in spec and value in spec["enum"]:
            safe[name] = value
        else:
            safe[name] = "<redacted>"
    return safe


class MemoryLedger:
    def __init__(self) -> None:
        self._rows: list[LedgerRow] = []

    def append(self, action_id: str, kind: str, at: str, payload: dict[str, Any]) -> LedgerRow:
        seq = sum(1 for r in self._rows if r.action_id == action_id)
        row = LedgerRow(action_id, seq, at, kind, json.loads(json.dumps(payload)))
        self._rows.append(row)
        return row

    def rows(self, action_id: str) -> list[LedgerRow]:
        return [r for r in self._rows if r.action_id == action_id]

    def recent(self, limit: int = 50) -> list[LedgerRow]:
        return list(reversed(self._rows[-limit:]))


class SqliteLedger:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, action_id: str, kind: str, at: str, payload: dict[str, Any]) -> LedgerRow:
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if len(text) > MAX_PAYLOAD_CHARS:
            raise StorageError("an action ledger row is too large")
        try:
            with self._conn:
                seq = self._conn.execute(
                    "SELECT COALESCE(MAX(seq) + 1, 0) FROM action_events WHERE action_id = ?",
                    (action_id,),
                ).fetchone()[0]
                self._conn.execute(
                    "INSERT INTO action_events (action_id, seq, at, kind, payload) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (action_id, seq, at, kind, text),
                )
        except sqlite3.Error as exc:
            raise StorageError("the action ledger could not be written") from exc
        return LedgerRow(action_id, int(seq), at, kind, json.loads(text))

    def rows(self, action_id: str) -> list[LedgerRow]:
        return self._read(
            "SELECT action_id, seq, at, kind, payload FROM action_events "
            "WHERE action_id = ? ORDER BY seq",
            (action_id,),
        )

    def recent(self, limit: int = 50) -> list[LedgerRow]:
        return self._read(
            "SELECT action_id, seq, at, kind, payload FROM action_events ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )

    def _read(self, sql: str, params: tuple[Any, ...]) -> list[LedgerRow]:
        try:
            return [
                LedgerRow(a, int(s), at, k, json.loads(p))
                for a, s, at, k, p in self._conn.execute(sql, params).fetchall()
            ]
        except sqlite3.Error as exc:
            raise StorageError("the action ledger could not be read") from exc
