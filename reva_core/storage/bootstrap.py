"""Single entry point orchestration uses to bring storage up.

`initialize_database` proves the required Phase 0 property:
new database -> migrations apply -> schema version known -> restart ->
migrations remain idempotently applied.

Upgrading an existing database is made safe (AR-CORE-011): before any pending migration runs, a
snapshot of the database is written next to it; if a migration fails, the database is put back
exactly as it was and the error is raised, so Core never starts on a half-migrated file.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

from reva_core.shared.errors import StorageError
from reva_core.storage.connection import open_connection
from reva_core.storage.migrations import (
    SNAPSHOT_DIR_NAME,
    apply_migrations,
    current_version,
    pending_versions,
    snapshot,
)


def initialize_database(db_path: Path) -> tuple[sqlite3.Connection, int]:
    conn = open_connection(db_path)
    taken: Path | None = None
    try:
        if current_version(conn) > 0 and pending_versions(conn):
            taken = snapshot(conn, Path(db_path).parent / SNAPSHOT_DIR_NAME)
    except BaseException:
        conn.close()  # nothing was changed yet; do not leak the connection
        raise
    try:
        schema_version = apply_migrations(conn)
    except BaseException as failure:
        # Any failure (not only a StorageError) leaves the database as it was before the upgrade.
        conn.close()
        if taken is not None:
            _restore(taken, Path(db_path), cause=failure)
        raise
    return conn, schema_version


def _restore(snapshot_path: Path, db_path: Path, *, cause: BaseException) -> None:
    """Put the pre-upgrade snapshot back as the database, or say loudly that it could not be.

    Order matters: the copy is made next to the database first (so a failed copy never touches the
    live file), stale write-ahead files are removed (a leftover WAL would replay onto the restored
    file), and only then is the copy moved into place in one step.
    """
    if not snapshot_path.is_file():
        raise StorageError(
            "the pre-upgrade snapshot is missing; the database may be half-migrated "
            f"and was not restored ({type(cause).__name__}: {cause})"
        ) from cause
    staged = db_path.with_name(db_path.name + ".restore")
    try:
        shutil.copyfile(snapshot_path, staged)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise StorageError(f"restore failed while copying the snapshot: {exc}") from exc
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        try:
            side.unlink(missing_ok=True)
        except OSError as exc:
            staged.unlink(missing_ok=True)
            raise StorageError(
                f"restore stopped: {side.name} could not be removed ({exc}); "
                "the database was not restored"
            ) from exc
    try:
        os.replace(staged, db_path)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise StorageError(f"restore failed while putting the snapshot in place: {exc}") from exc
