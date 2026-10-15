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

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from reva_core.shared.errors import StorageError
from reva_core.shared.time import utc_now

_SQL_DIR = Path(__file__).parent / "migrations_sql"
_DOWN_SUFFIX = ".down"
SNAPSHOT_DIR_NAME = "snapshots"


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
            # The script and its version row commit together or not at all.
            _run_atomically(
                conn,
                migration.sql,
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, utc_now().isoformat()),
            )
        except sqlite3.Error as exc:
            raise StorageError(
                f"migration {migration.version} ({migration.name}) failed: {exc}"
            ) from exc

    row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    if row is None or row["version"] is None:
        raise StorageError("no migrations recorded after apply_migrations")
    return int(row["version"])


def rollback_to(
    conn: sqlite3.Connection,
    target: int,
    migrations: list[Migration] | None = None,
    *,
    snapshot_directory: Path | None = None,
) -> int:
    """Undo migrations newest-first until the database is at `target`. Returns the new version.

    Every down script is checked first, then a safety snapshot is saved before any is run.
    File databases save beside the database; in-memory databases require snapshot_directory.
    If backup fails, no down script runs. A failed rollback's pre-rollback data stays in the copy.
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
    if to_undo:
        if snapshot_directory is None:
            database = next(
                row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"
            )
            if not database:
                raise StorageError("in-memory rollback requires a snapshot directory")
            snapshot_directory = Path(database).parent / SNAPSHOT_DIR_NAME
        snapshot(conn, snapshot_directory)
    for version in to_undo:
        step = known[version]
        assert step.down_sql is not None
        try:
            _run_atomically(
                conn,
                step.down_sql,
                "DELETE FROM schema_migrations WHERE version = ?",
                (version,),
            )
        except sqlite3.Error as exc:
            raise StorageError(f"rolling back migration {version} failed: {exc}") from exc
    return current_version(conn)


def snapshot(conn: sqlite3.Connection, directory: Path, *, keep: int = 3) -> Path:
    """A consistent copy of the database (SQLite's online backup), named by its schema version.

    Older snapshots beyond `keep` are removed. Returns the new file.
    """
    if keep < 1:
        raise ValueError("keep must be at least one")
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
    # Schema versions go backwards after rollback. Retain by timestamp, and always protect
    # the copy just taken, even if the system clock moved backwards.
    older = sorted(
        (p for p in directory.glob("reva-v*.db") if p != target),
        key=lambda p: p.stem.partition("-")[2].partition("-")[2],
    )
    for old in older[: max(0, len(older) - (keep - 1))]:
        old.unlink(missing_ok=True)
    return target


_TRANSACTION_CONTROL = re.compile(
    r"(?:--[^\n]*\n\s*)*"
    r"(?:BEGIN(?:\s+(?:DEFERRED|IMMEDIATE|EXCLUSIVE))?(?:\s+TRANSACTION)?|COMMIT|END(?:\s+TRANSACTION)?)"
    r"\s*;",
    re.IGNORECASE,
)


def _statements(script: str) -> list[str]:
    """Split a migration script into complete statements, dropping its own BEGIN and COMMIT.

    `sqlite3.complete_statement` knows that a trigger's inner `;` does not end the statement, so a
    `CREATE TRIGGER ... BEGIN ... END;` stays in one piece.
    """
    statements: list[str] = []
    start = 0
    for index, char in enumerate(script):
        if char == ";" and sqlite3.complete_statement(script[start : index + 1]):
            text = script[start : index + 1].strip()
            start = index + 1
            if not _TRANSACTION_CONTROL.fullmatch(text):
                statements.append(text)
    leftover = script[start:].strip()
    if leftover and any(not part.lstrip().startswith("--") for part in leftover.splitlines()):
        statements.append(leftover)
    return statements


def _run_atomically(
    conn: sqlite3.Connection, script: str, then_sql: str, then_params: tuple[object, ...]
) -> None:
    """Run every statement of `script`, then `then_sql`, inside ONE transaction.

    `executescript` commits before it runs and the scripts commit themselves, which left a window
    where a crash kept the new tables but not their version row. Here the script's own
    BEGIN/COMMIT are dropped and SQLite (whose DDL is transactional) commits all or nothing.
    """
    statements = _statements(script)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in statements:
            conn.execute(statement)
        conn.execute(then_sql, then_params)
        conn.execute("COMMIT")
    except BaseException:
        _abandon_open_transaction(conn)
        raise


def _abandon_open_transaction(conn: sqlite3.Connection) -> None:
    """A script that failed halfway can leave its BEGIN open; the next statement must not join it"""
    if conn.in_transaction:
        conn.execute("ROLLBACK")
