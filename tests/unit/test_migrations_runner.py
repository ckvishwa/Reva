import sqlite3

import pytest

import reva_core.storage.migrations as migrations_module
from reva_core.shared.errors import StorageError


def test_apply_migrations_wraps_sql_errors_as_storage_error(monkeypatch):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row

    broken = migrations_module.Migration(version=1, name="broken", sql="THIS IS NOT SQL;")
    monkeypatch.setattr(migrations_module, "MIGRATIONS", [broken])

    with pytest.raises(StorageError):
        migrations_module.apply_migrations(conn)

    conn.close()


def test_apply_migrations_is_a_noop_when_nothing_pending(monkeypatch):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row

    ok = migrations_module.Migration(version=1, name="ok", sql="CREATE TABLE t (id TEXT);")
    monkeypatch.setattr(migrations_module, "MIGRATIONS", [ok])

    first = migrations_module.apply_migrations(conn)
    second = migrations_module.apply_migrations(conn)
    assert first == second == 1

    conn.close()
