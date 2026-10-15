"""B4: reversible migrations with snapshot upgrade and rollback (AR-CORE-011)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reva_core.shared.errors import StorageError
from reva_core.storage.bootstrap import SNAPSHOT_DIR_NAME, initialize_database
from reva_core.storage.connection import open_connection
from reva_core.storage.migrations import (
    MIGRATIONS,
    Migration,
    apply_migrations,
    current_version,
    rollback_to,
    snapshot,
)


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")
    return {r["name"] for r in rows if not r["name"].startswith("sqlite_")}


@pytest.fixture
def conn(tmp_path: Path):
    connection = open_connection(tmp_path / "reva.db")
    yield connection
    connection.close()


def test_every_migration_has_a_down_script() -> None:
    assert [m.version for m in MIGRATIONS] == sorted(m.version for m in MIGRATIONS)
    missing = [m.version for m in MIGRATIONS if m.down_sql is None]
    assert missing == []
    assert all(m.down_sql and "DROP" in m.down_sql for m in MIGRATIONS)


def test_down_files_are_not_mistaken_for_migrations() -> None:
    assert len(MIGRATIONS) == len({m.version for m in MIGRATIONS})
    assert not any(m.name.endswith(".down") for m in MIGRATIONS)


def test_up_then_all_the_way_down_leaves_nothing_behind(conn: sqlite3.Connection) -> None:
    top = apply_migrations(conn)
    assert top == MIGRATIONS[-1].version and "action_events" in tables(conn)

    assert rollback_to(conn, 0) == 0

    assert tables(conn) <= {"schema_migrations"}


@pytest.mark.parametrize("target", [m.version for m in MIGRATIONS[:-1]])
def test_rolling_back_to_each_earlier_version_then_forward_again(
    conn: sqlite3.Connection, target: int
) -> None:
    apply_migrations(conn)

    assert rollback_to(conn, target) == target
    assert current_version(conn) == target
    assert apply_migrations(conn) == MIGRATIONS[-1].version
    assert "action_events" in tables(conn)


def test_a_rollback_keeps_what_the_older_schema_still_owns(conn: sqlite3.Connection) -> None:
    apply_migrations(conn)
    before = tables(conn)

    rollback_to(conn, 3)

    assert "action_events" not in tables(conn) and "device_grants" in tables(conn)
    assert tables(conn) < before


def test_the_ledger_triggers_do_not_stop_their_own_rollback(conn: sqlite3.Connection) -> None:
    apply_migrations(conn)
    conn.execute(
        "INSERT INTO action_events (action_id, seq, at, kind, payload) "
        "VALUES ('a', 0, 't', 'proposed', '{}')"
    )

    rollback_to(conn, 3)  # would raise if the append-only triggers were still in place

    assert "action_events" not in tables(conn)


def test_rollback_checks_every_down_script_before_changing_anything(
    conn: sqlite3.Connection,
) -> None:
    migrations = [
        Migration(1, "a", "BEGIN; CREATE TABLE a (x); COMMIT;", "BEGIN; DROP TABLE a; COMMIT;"),
        Migration(2, "b", "BEGIN; CREATE TABLE b (x); COMMIT;", None),
    ]
    apply_migrations(conn, migrations)

    with pytest.raises(StorageError, match="cannot be rolled back"):
        rollback_to(conn, 0, migrations)

    assert {"a", "b"} <= tables(conn) and current_version(conn) == 2


@pytest.mark.parametrize("target", [-1, 99])
def test_rolling_back_to_a_version_that_does_not_exist_is_refused(
    conn: sqlite3.Connection, target: int
) -> None:
    apply_migrations(conn)

    with pytest.raises(StorageError, match="no schema version"):
        rollback_to(conn, target)


def test_a_database_from_a_newer_core_is_refused(conn: sqlite3.Connection) -> None:
    apply_migrations(conn)
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (99, 'future', 'now')"
    )

    with pytest.raises(StorageError, match="newer version"):
        apply_migrations(conn)


# ------------------------------------------------------------------- snapshots


def test_a_snapshot_is_a_consistent_copy_named_by_version(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    apply_migrations(conn)

    copy = snapshot(conn, tmp_path / "snaps")

    assert copy.name.startswith(f"reva-v{MIGRATIONS[-1].version:04d}-")
    other = sqlite3.connect(copy)
    try:
        assert other.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == (
            MIGRATIONS[-1].version
        )
    finally:
        other.close()


def test_only_the_newest_snapshots_are_kept(conn: sqlite3.Connection, tmp_path: Path) -> None:
    apply_migrations(conn)

    names = [snapshot(conn, tmp_path / "snaps", keep=2).name for _ in range(4)]

    assert sorted(p.name for p in (tmp_path / "snaps").iterdir()) == sorted(names[-2:])


def test_upgrading_an_existing_database_takes_a_snapshot_first(tmp_path: Path) -> None:
    db = tmp_path / "reva.db"
    old = open_connection(db)
    apply_migrations(old, MIGRATIONS[:2])
    old.close()

    conn, version = initialize_database(db)
    conn.close()

    assert version == MIGRATIONS[-1].version
    snaps = list((tmp_path / SNAPSHOT_DIR_NAME).glob("reva-v0002-*.db"))
    assert len(snaps) == 1


def test_a_fresh_database_and_an_up_to_date_one_take_no_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "reva.db"

    initialize_database(db)[0].close()
    initialize_database(db)[0].close()

    assert not (tmp_path / SNAPSHOT_DIR_NAME).exists()


def test_a_failed_upgrade_puts_the_database_back_exactly_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "reva.db"
    old = open_connection(db)
    apply_migrations(old, MIGRATIONS[:2])
    old.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (-1, 'marker', 'x')"
    )
    old.close()
    broken = [*MIGRATIONS[:3], Migration(4, "broken", "BEGIN; CREATE TABLE ok (x); NOPE; COMMIT;")]
    import reva_core.storage.bootstrap as bootstrap
    import reva_core.storage.migrations as migrations

    monkeypatch.setattr(migrations, "MIGRATIONS", broken)
    monkeypatch.setattr(
        bootstrap, "apply_migrations", lambda c: migrations.apply_migrations(c, broken)
    )
    monkeypatch.setattr(
        bootstrap, "pending_versions", lambda c: migrations.pending_versions(c, broken)
    )

    with pytest.raises(StorageError, match="migration 4"):
        initialize_database(db)

    check = sqlite3.connect(db)
    try:
        versions = {r[0] for r in check.execute("SELECT version FROM schema_migrations")}
        names = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        check.close()
    assert versions == {1, 2, -1}  # exactly the pre-upgrade state, marker included
    assert "device_grants" not in names and "ok" not in names
