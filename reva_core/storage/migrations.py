"""Explicit, versioned, reversible SQLite migrations (AR-CORE-011).

No ORM: migrations are plain SQL files applied in order, tracked in a `schema_migrations` table.
Each `NNNN_name.sql` has a matching `NNNN_name.down.sql` that undoes it, so a database can be
rolled back to an earlier version. Applying is idempotent: re-running against an already-migrated
database is a no-op, which is what makes a Core restart safe (see
docs/architecture/runtime-model.md).

A database written by a *newer* Core (a version this code has no migration for) is refused rather
than opened and half understood.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from reva_core.shared.errors import StorageError
from reva_core.shared.time import utc_now

_SQL_DIR = Path(__file__).parent / "migrations_sql"
_DOWN_SUFFIX = ".down"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    down_sql: str | None = None


def _load_migrations(directory: Path = _SQL_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        if path.stem.endswith(_DOWN_SUFFIX):
            continue
        version_str, _, rest = path.stem.partition("_")
        down = path.with_name(f"{path.stem}{_DOWN_SUFFIX}.sql")
        migrations.append(
            Migration(
                version=int(version_str),
                name=rest,
                sql=path.read_text(encoding="utf-8"),
                down_sql=down.read_text(encoding="utf-8") if down.exists() else None,
            )
        )
    return sorted(migrations, key=lambda m: m.version)


MIGRATIONS: list[Migration] = _load_migrations()


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def current_version(conn: sqlite3.Connection) -> int:
    """The highest applied migration, or 0 for a database with none."""
    _ensure_table(conn)
    row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    return int(row["version"]) if row is not None and row["version"] is not None else 0


def pending_versions(
    conn: sqlite3.Connection, migrations: list[Migration] | None = None
) -> list[int]:
    _ensure_table(conn)
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    return [m.version for m in (migrations or MIGRATIONS) if m.version not in applied]


def apply_migrations(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> int:
    """Apply any pending migrations. Returns the resulting schema version."""
    known = migrations if migrations is not None else MIGRATIONS
    _ensure_table(conn)
    applied_versions = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
    }
    newest_known = max((m.version for m in known), default=0)
    if applied_versions and max(applied_versions) > newest_known:
        raise StorageError(
            f"this database is at schema version {max(applied_versions)} but this Core only "
            f"knows up to {newest_known}; refusing to open a database from a newer version"
        )

    for migration in known:
        if migration.version in applied_versions:
            continue
        try:
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, utc_now().isoformat()),
            )
        except sqlite3.Error as exc:
            _abandon_open_transaction(conn)
            raise StorageError(
                f"migration {migration.version} ({migration.name}) failed: {exc}"
            ) from exc

    row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    if row is None or row["version"] is None:
        raise StorageError("no migrations recorded after apply_migrations")
    return int(row["version"])


def rollback_to(
    conn: sqlite3.Connection, target: int, migrations: list[Migration] | None = None
) -> int:
    """Undo migrations newest-first until the database is at `target`. Returns the new version.

    Every step to undo must have a down script, checked before anything is changed. Data held by
    a dropped table is gone (that is what a rollback is); `snapshot` is how it is kept.
    """
    known = {m.version: m for m in (migrations if migrations is not None else MIGRATIONS)}
    _ensure_table(conn)
    applied = sorted(
        (row["version"] for row in conn.execute("SELECT version FROM schema_migrations")),
        reverse=True,
    )
    if target < 0 or (target != 0 and target not in known):
        raise StorageError(f"there is no schema version {target} to roll back to")
    to_undo = [v for v in applied if v > target]
    for version in to_undo:
        step = known.get(version)
        if step is None or step.down_sql is None:
            raise StorageError(f"migration {version} cannot be rolled back (no down script)")
    for version in to_undo:
        step = known[version]
        assert step.down_sql is not None
        try:
            conn.executescript(step.down_sql)
            conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
        except sqlite3.Error as exc:
            _abandon_open_transaction(conn)
            raise StorageError(f"rolling back migration {version} failed: {exc}") from exc
    return current_version(conn)


def snapshot(conn: sqlite3.Connection, directory: Path, *, keep: int = 3) -> Path:
    """A consistent copy of the database (SQLite's online backup), named by its schema version.

    Older snapshots beyond `keep` are removed. Returns the new file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    version = current_version(conn)
    stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"reva-v{version:04d}-{stamp}.db"
    copy = sqlite3.connect(str(target))
    try:
        conn.backup(copy)
    except sqlite3.Error as exc:
        target.unlink(missing_ok=True)
        raise StorageError(f"could not take a database snapshot: {exc}") from exc
    finally:
        copy.close()
    for old in sorted(directory.glob("reva-v*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    return target


def _abandon_open_transaction(conn: sqlite3.Connection) -> None:
    """A script that failed halfway can leave its BEGIN open; the next statement must not join it"""
    if conn.in_transaction:
        conn.execute("ROLLBACK")
