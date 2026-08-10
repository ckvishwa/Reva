"""Single entry point orchestration uses to bring storage up.

`initialize_database` proves the required Phase 0 property:
new database -> migrations apply -> schema version known -> restart ->
migrations remain idempotently applied.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from reva_core.storage.connection import open_connection
from reva_core.storage.migrations import apply_migrations


def initialize_database(db_path: Path) -> tuple[sqlite3.Connection, int]:
    conn = open_connection(db_path)
    schema_version = apply_migrations(conn)
    return conn, schema_version
