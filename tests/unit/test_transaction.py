import sqlite3

import pytest

from reva_core.storage.connection import transaction


def _conn():
    conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
    return conn


def test_transaction_commits_on_success():
    conn = _conn()
    with transaction(conn):
        conn.execute("INSERT INTO t (value) VALUES ('a')")
    rows = conn.execute("SELECT value FROM t").fetchall()
    assert [r["value"] for r in rows] == ["a"]
    conn.close()


def test_transaction_rolls_back_on_exception():
    conn = _conn()
    with pytest.raises(ValueError), transaction(conn):
        conn.execute("INSERT INTO t (value) VALUES ('a')")
        raise ValueError("boom")
    rows = conn.execute("SELECT value FROM t").fetchall()
    assert rows == []
    conn.close()


def test_transaction_rolls_back_partial_multi_statement_write():
    conn = _conn()
    with pytest.raises(ValueError), transaction(conn):
        conn.execute("INSERT INTO t (value) VALUES ('a')")
        conn.execute("INSERT INTO t (value) VALUES ('b')")
        raise ValueError("boom after two inserts")
    rows = conn.execute("SELECT value FROM t").fetchall()
    assert rows == []
    conn.close()
