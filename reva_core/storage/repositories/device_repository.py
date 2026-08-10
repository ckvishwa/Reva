"""Persistence for `devices` — Phase 1A needs exactly one thing from it:
a stable primary-device ID that survives restart, so every message,
memory, and audit event has a real, valid `origin_device_id` to point
at. Real device pairing/registration is PLANNED (Phase 4-5)."""

from __future__ import annotations

import sqlite3

from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.connection import transaction

_PRIMARY_DEVICE_METADATA_KEY = "primary_device_id"


class DeviceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_or_create_primary_device(self) -> str:
        row = self._conn.execute(
            "SELECT value FROM application_metadata WHERE key = ?",
            (_PRIMARY_DEVICE_METADATA_KEY,),
        ).fetchone()
        if row is not None:
            return str(row["value"])

        device_id = new_id()
        try:
            with transaction(self._conn):
                self._conn.execute(
                    "INSERT INTO devices (id, display_name, platform, paired_at) "
                    "VALUES (?, ?, ?, ?)",
                    (device_id, "Local Windows Device", "windows", utc_now().isoformat()),
                )
                self._conn.execute(
                    "INSERT INTO application_metadata (key, value) VALUES (?, ?)",
                    (_PRIMARY_DEVICE_METADATA_KEY, device_id),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to create primary device: {exc}") from exc
        return device_id
