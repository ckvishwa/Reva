"""Proves: new database -> migrations apply -> schema version known ->
restart -> migrations remain idempotently applied."""

import sqlite3

import pytest

from reva_core.storage.bootstrap import initialize_database

EXPECTED_TABLES = {
    "schema_migrations",
    "application_metadata",
    "devices",
    "conversations",
    "messages",
    "memories",
    "memory_embeddings",
    "reminders",
    "permissions",
    "audit_events",
    "sync_events",
}


def test_initialize_database_creates_expected_schema(tmp_path):
    db_path = tmp_path / "reva.db"
    conn, version = initialize_database(db_path)
    try:
        assert version == 3
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert tables >= EXPECTED_TABLES
    finally:
        conn.close()


def test_initialize_database_enables_wal_mode(tmp_path):
    db_path = tmp_path / "reva.db"
    conn, _ = initialize_database(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_initialize_database_enables_foreign_keys(tmp_path):
    db_path = tmp_path / "reva.db"
    conn, _ = initialize_database(db_path)
    try:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert enabled == 1
    finally:
        conn.close()


def test_foreign_keys_are_enforced_not_just_enabled(tmp_path):
    db_path = tmp_path / "reva.db"
    conn, _ = initialize_database(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, "
                "origin_device_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("msg-1", "missing-conversation", "user", "hi", "device-1", "2026-01-01T00:00:00Z"),
            )
    finally:
        conn.close()


def test_restart_is_idempotent(tmp_path):
    db_path = tmp_path / "reva.db"

    conn1, version1 = initialize_database(db_path)
    conn1.close()

    conn2, version2 = initialize_database(db_path)
    try:
        assert version1 == version2 == 3
        migration_rows = conn2.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()
        assert migration_rows["n"] == 3
    finally:
        conn2.close()


def test_restart_preserves_existing_rows(tmp_path):
    db_path = tmp_path / "reva.db"

    conn1, _ = initialize_database(db_path)
    conn1.execute(
        "INSERT INTO devices (id, display_name, platform, paired_at) VALUES (?, ?, ?, ?)",
        ("device-1", "Test PC", "windows", "2026-01-01T00:00:00Z"),
    )
    conn1.close()

    conn2, _ = initialize_database(db_path)
    try:
        row = conn2.execute(
            "SELECT display_name FROM devices WHERE id = ?", ("device-1",)
        ).fetchone()
        assert row["display_name"] == "Test PC"
    finally:
        conn2.close()
