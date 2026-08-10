"""Explicit, versioned SQLite migrations.

No ORM: migrations are plain SQL files applied in order, tracked in a
`schema_migrations` table. Applying is idempotent — re-running against an
already-migrated database is a no-op, which is what makes Core restart
safe (see docs/architecture/runtime-model.md).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from reva_core.shared.errors import StorageError
from reva_core.shared.time import utc_now

_SQL_DIR = Path(__file__).parent / "migrations_sql"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def _load_migrations() -> list[Migration]:
    migrations = []
    for path in sorted(_SQL_DIR.glob("*.sql")):
        version_str, _, rest = path.stem.partition("_")
        migrations.append(
            Migration(version=int(version_str), name=rest, sql=path.read_text(encoding="utf-8"))
        )
    return sorted(migrations, key=lambda m: m.version)


MIGRATIONS: list[Migration] = _load_migrations()


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply any pending migrations. Returns the resulting schema version."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied_versions = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
    }

    for migration in MIGRATIONS:
        if migration.version in applied_versions:
            continue
        try:
            conn.executescript(migration.sql)
            conn.execute(
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
