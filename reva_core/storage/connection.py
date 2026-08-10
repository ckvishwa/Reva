"""SQLite connection creation with REVA's required pragmas.

WAL mode and foreign keys are both connection-scoped in SQLite (foreign
keys are OFF by default per connection; WAL is persisted in the file but
still set explicitly here so behavior does not depend on file history).

`isolation_level=None` puts the connection in autocommit mode so callers
control transaction boundaries explicitly with `BEGIN`/`COMMIT`/`ROLLBACK`
instead of relying on the sqlite3 module's implicit transaction guessing.

`check_same_thread=False`: REVA Core is a single-process, effectively
single-connection app, but FastAPI/Starlette may run request handling
(and, for TestClient, the whole ASGI app) on a worker/portal thread
different from the thread that opened this connection. Python's
sqlite3 module refuses cross-thread use by default as a safety guard;
disabling it is the standard FastAPI+sqlite3 pattern and is safe here
because Python links against a thread-safe (serialized-mode) SQLite by
default and REVA's request pattern is effectively sequential, not
concurrent — WAL mode's own locking, not this flag, is what actually
protects concurrent access if that ever changes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def open_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Explicit transaction boundary: everything inside the `with` block
    commits together or rolls back together. Required whenever more than
    one write must succeed or fail as a unit (e.g. a memory row and its
    audit event) — see docs/architecture/storage-design.md.

    Callers must not nest this — SQLite (and this wrapper) has no
    savepoint support here, so a nested `BEGIN` raises `sqlite3.Error`.
    """
    conn.execute("BEGIN")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
