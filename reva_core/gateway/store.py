"""Persistence for approved phones: the `devices` row plus its `device_grants` row.

The gateway uses its own SQLite connection (same file, WAL) and its own lock, because the gateway
server runs on a different thread from the Core API and `transaction()` must not interleave.
Only public material is stored. Revoking is one UPDATE, so a request either sees the grant active or
sees it revoked, never half-way.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.connection import open_connection, transaction
from reva_core.storage.repositories.audit_repository import AuditRepository


@dataclass(frozen=True)
class Grant:
    device_id: str
    display_name: str
    platform: str
    public_key: bytes
    kernel_ids: dict[str, str]
    scopes: tuple[str, ...]
    status: str
    approved_at: str
    revoked_at: str | None
    last_seen_at: str | None

    @property
    def active(self) -> bool:
        return self.status == "active"


_SELECT = (
    "SELECT d.id, d.display_name, d.platform, d.last_seen_at, g.public_key, g.kernel_ids, "
    "g.scopes, g.status, g.approved_at, g.revoked_at "
    "FROM device_grants g JOIN devices d ON d.id = g.device_id"
)


def _grant(row: sqlite3.Row) -> Grant:
    return Grant(
        device_id=row["id"],
        display_name=row["display_name"],
        platform=row["platform"],
        public_key=base64.b64decode(row["public_key"]),
        kernel_ids=json.loads(row["kernel_ids"]),
        scopes=tuple(json.loads(row["scopes"])),
        status=row["status"],
        approved_at=row["approved_at"],
        revoked_at=row["revoked_at"],
        last_seen_at=row["last_seen_at"],
    )


class GrantStore:
    def __init__(self, db_path: Path) -> None:
        self._conn = open_connection(db_path)
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add(
        self,
        *,
        display_name: str,
        platform: str,
        public_key: bytes,
        kernel_ids: dict[str, str],
        scopes: tuple[str, ...],
    ) -> str:
        device_id = new_id()
        now = utc_now().isoformat()
        try:
            with self._lock, transaction(self._conn):
                self._conn.execute(
                    "INSERT INTO devices (id, display_name, platform, paired_at) VALUES (?,?,?,?)",
                    (device_id, display_name, platform, now),
                )
                self._conn.execute(
                    "INSERT INTO device_grants (device_id, public_key, kernel_ids, scopes, status, "
                    "approved_at) VALUES (?,?,?,?, 'active', ?)",
                    (
                        device_id,
                        base64.b64encode(public_key).decode("ascii"),
                        json.dumps(kernel_ids, sort_keys=True),
                        json.dumps(list(scopes)),
                        now,
                    ),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to store the device grant: {exc}") from exc
        return device_id

    def remove(self, device_id: str) -> None:
        """Undo `add` when a later step of approval fails (the Kernel refused the peer)."""
        with self._lock, transaction(self._conn):
            self._conn.execute("DELETE FROM device_grants WHERE device_id = ?", (device_id,))
            self._conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    def get(self, device_id: str) -> Grant | None:
        with self._lock:
            row = self._conn.execute(_SELECT + " WHERE g.device_id = ?", (device_id,)).fetchone()
        return _grant(row) if row else None

    def list_all(self) -> list[Grant]:
        with self._lock:
            rows = self._conn.execute(_SELECT + " ORDER BY g.approved_at, g.device_id").fetchall()
        return [_grant(r) for r in rows]

    def active_grants(self) -> list[Grant]:
        return [g for g in self.list_all() if g.active]

    def revoke(self, device_id: str) -> bool:
        """True if an active grant was revoked now."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE device_grants SET status = 'revoked', revoked_at = ? "
                "WHERE device_id = ? AND status = 'active'",
                (utc_now().isoformat(), device_id),
            )
            return cur.rowcount == 1

    def touch(self, device_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE devices SET last_seen_at = ? WHERE id = ?",
                (utc_now().isoformat(), device_id),
            )

    def audit(
        self,
        action: str,
        outcome: AuditOutcome,
        *,
        device_id: str | None = None,
        **metadata: str | int,
    ) -> None:
        """Security log (AR-DATA-009): who asked, what happened. Never keys, codes or signatures."""
        try:
            with self._lock:
                AuditRepository(self._conn).insert(
                    AuditEvent(
                        id=new_id(),
                        category=AuditEventCategory.SYNC,
                        action=action,
                        outcome=outcome,
                        actor_device_id=device_id,
                        metadata=dict(metadata),
                        occurred_at=utc_now(),
                    )
                )
        except (StorageError, sqlite3.Error):
            pass  # a full or locked log must never turn a denial into an acceptance
