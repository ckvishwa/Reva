"""Single entry point orchestration uses to bring storage up.

`initialize_database` proves the required Phase 0 property:
new database -> migrations apply -> schema version known -> restart ->
migrations remain idempotently applied.

Upgrading an existing database is made safe (AR-CORE-011): before any pending migration runs, a
snapshot of the database is written next to it; if a migration fails, the database is put back
exactly as it was and the error is raised, so Core never starts on a half-migrated file.
"""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
from pathlib import Path

from reva_core.shared.errors import StorageError
from reva_core.storage.connection import open_connection
from reva_core.storage.migrations import (
    apply_migrations,
    current_version,
    pending_versions,
    snapshot,
)

SNAPSHOT_DIR_NAME = "snapshots"


def initialize_database(db_path: Path) -> tuple[sqlite3.Connection, int]:
    conn = open_connection(db_path)
    existing = current_version(conn)
    taken: Path | None = None
    if existing > 0 and pending_versions(conn):
        taken = snapshot(conn, Path(db_path).parent / SNAPSHOT_DIR_NAME)
    try:
        schema_version = apply_migrations(conn)
    except StorageError:
        conn.close()
        if taken is not None:
            _restore(taken, Path(db_path))
        raise
    return conn, schema_version


def _restore(snapshot_path: Path, db_path: Path) -> None:
    """Put the snapshot back as the database (and drop the write-ahead files of the failed run)."""
    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
    shutil.copyfile(snapshot_path, db_path)
