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


def test_snapshot_retention_uses_time_instead_of_schema_version(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    apply_migrations(conn)
    directory = tmp_path / "snaps"
    older = [snapshot(conn, directory) for _ in range(3)]
    rollback_to(conn, 2)

    latest = snapshot(conn, directory)

    assert latest.exists()
    assert not older[0].exists()
    assert all(p.exists() for p in older[1:])
    assert len(list(directory.glob("*.db"))) == 3


def test_rollback_saves_data_before_dropping_tables(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    apply_migrations(conn)
    conn.execute(
        "INSERT INTO action_events (action_id, seq, at, kind, payload) "
        "VALUES ('recover-me', 0, 't', 'proposed', '{}')"
    )

    rollback_to(conn, 3)

    copies = list((tmp_path / SNAPSHOT_DIR_NAME).glob("reva-v0004-*.db"))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as saved:
        assert saved.execute("SELECT action_id FROM action_events").fetchone()[0] == "recover-me"
        assert saved.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 4


def test_failed_rollback_leaves_a_usable_pre_rollback_copy(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    migrations = [
        Migration(1, "a", "CREATE TABLE a (x);", "DROP TABLE a;"),
        Migration(2, "b", "CREATE TABLE b (x);", "DROP TABLE b; NOPE;"),
    ]
    apply_migrations(conn, migrations)
    conn.execute("INSERT INTO b VALUES ('recover-me')")

    with pytest.raises(StorageError, match="rolling back migration 2"):
        rollback_to(conn, 0, migrations)

    copies = list((tmp_path / SNAPSHOT_DIR_NAME).glob("reva-v0002-*.db"))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as saved:
        assert saved.execute("SELECT x FROM b").fetchone()[0] == "recover-me"
        assert saved.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2


def test_snapshot_just_taken_survives_a_backwards_clock(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    apply_migrations(conn)
    directory = tmp_path / "snaps"
    for _ in range(3):
        snapshot(conn, directory)
    monkeypatch.setattr(
        "reva_core.storage.migrations.utc_now", lambda: datetime(2000, 1, 1, tzinfo=UTC)
    )

    latest = snapshot(conn, directory, keep=1)

    assert list(directory.glob("*.db")) == [latest]


def test_rollback_does_not_change_data_if_backup_fails(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_migrations(conn)

    def fail(*args, **kwargs):
        raise StorageError("backup unavailable")

    monkeypatch.setattr("reva_core.storage.migrations.snapshot", fail)
    with pytest.raises(StorageError, match="backup unavailable"):
        rollback_to(conn, 3)
    assert current_version(conn) == 4
    assert "action_events" in tables(conn)


def test_in_memory_rollback_requires_a_backup_destination(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        apply_migrations(conn)
        with pytest.raises(StorageError, match="snapshot directory"):
            rollback_to(conn, 3)
        assert current_version(conn) == 4
        assert rollback_to(conn, 3, snapshot_directory=tmp_path / "saved") == 3
        assert len(list((tmp_path / "saved").glob("reva-v0004-*.db"))) == 1
    finally:
        conn.close()


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
    # Simulate snapshots left by a previous newer schema. The recovery copy for v2
    # must survive retention even though its version sorts before those copies.
    directory = tmp_path / SNAPSHOT_DIR_NAME
    directory.mkdir()
    for n in range(3):
        (directory / f"reva-v0004-20200101T00000{n}000000Z.db").write_bytes(b"old snapshot")
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


# ------------------------------------------------- B4-FIX: atomicity, restore and recovery


def _broken_catalog(monkeypatch: pytest.MonkeyPatch) -> list[Migration]:
    """Make the real startup path see a catalog whose migration 4 is broken."""
    import reva_core.storage.bootstrap as bootstrap
    import reva_core.storage.migrations as migrations

    broken = [*MIGRATIONS[:3], Migration(4, "broken", "BEGIN; CREATE TABLE ok (x); NOPE; COMMIT;")]
    monkeypatch.setattr(migrations, "MIGRATIONS", broken)
    monkeypatch.setattr(
        bootstrap, "apply_migrations", lambda c: migrations.apply_migrations(c, broken)
    )
    monkeypatch.setattr(
        bootstrap, "pending_versions", lambda c: migrations.pending_versions(c, broken)
    )
    return broken


def _state(db: Path) -> tuple[set[int], set[str]]:
    check = sqlite3.connect(db)
    try:
        versions = {r[0] for r in check.execute("SELECT version FROM schema_migrations")}
        names = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        check.close()
    return versions, names


def test_upgrade_rollback_reupgrade_then_a_forced_failure_restores_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "reva.db"
    conn, top = initialize_database(db)  # fresh -> latest
    assert top == MIGRATIONS[-1].version
    rollback_to(conn, 2)  # takes its own safety snapshot
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (-1, 'marker', 'x')"
    )
    conn.close()
    before = _state(db)
    _broken_catalog(monkeypatch)

    with pytest.raises(StorageError, match="migration 4"):
        initialize_database(db)  # re-upgrade 3 and 4: 4 is broken

    assert _state(db) == before
    assert before[0] == {1, 2, -1}
    assert "device_grants" not in before[1] and "ok" not in before[1]


def test_a_missing_snapshot_fails_loudly_instead_of_a_bare_file_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reva_core.storage.bootstrap as bootstrap

    db = tmp_path / "reva.db"
    old = open_connection(db)
    apply_migrations(old, MIGRATIONS[:2])
    old.close()
    _broken_catalog(monkeypatch)
    real = bootstrap.snapshot

    def vanishing(conn: sqlite3.Connection, directory: Path, **kw: object) -> Path:
        path = real(conn, directory, **kw)  # type: ignore[arg-type]
        path.unlink()  # the copy disappears before it is needed
        return path

    monkeypatch.setattr(bootstrap, "snapshot", vanishing)

    with pytest.raises(StorageError, match="snapshot is missing") as caught:
        initialize_database(db)

    assert isinstance(caught.value.__cause__, StorageError)  # the original migration error


def test_a_migration_and_its_version_row_commit_together() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    first = Migration(1, "one", "BEGIN; CREATE TABLE one (x); COMMIT;")
    second = Migration(2, "two", "BEGIN; CREATE TABLE two (x); COMMIT;")
    apply_migrations(conn, [first])

    class Failing:
        """A connection whose version INSERT fails, as a crash right after the script would."""

        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner

        def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
            if sql.lstrip().startswith("INSERT INTO schema_migrations"):
                raise sqlite3.OperationalError("disk full")
            return self._inner.execute(sql, *args)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    with pytest.raises(StorageError, match="migration 2"):
        apply_migrations(Failing(conn), [first, second])  # type: ignore[arg-type]

    assert "two" not in tables(conn)  # the script was rolled back with the failed insert
    assert apply_migrations(conn, [first, second]) == 2  # and a retry now works


def test_a_failing_script_leaves_none_of_its_statements_behind() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    bad = Migration(1, "bad", "CREATE TABLE half (x); INSERT INTO nowhere VALUES (1);")

    with pytest.raises(StorageError):
        apply_migrations(conn, [bad])

    assert "half" not in tables(conn) and not conn.in_transaction


def test_triggers_with_their_own_begin_and_end_still_apply(conn: sqlite3.Connection) -> None:
    apply_migrations(conn)
    conn.execute(
        "INSERT INTO action_events (action_id, seq, at, kind, payload) "
        "VALUES ('a', 0, 't', 'proposed', '{}')"
    )

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM action_events")  # the 0004 trigger exists and fires


def test_a_down_script_and_its_version_delete_commit_together(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrations = [
        Migration(1, "one", "CREATE TABLE one (x);", "DROP TABLE one;"),
        Migration(2, "two", "CREATE TABLE two (x);", "DROP TABLE two; DROP TABLE missing_table;"),
    ]
    apply_migrations(conn, migrations)

    with pytest.raises(StorageError, match="rolling back migration 2"):
        rollback_to(conn, 1, migrations, snapshot_directory=tmp_path / "snaps")

    assert "two" in tables(conn) and current_version(conn) == 2  # nothing half-undone


def test_a_failed_copy_never_truncates_the_live_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reva_core.storage.bootstrap as bootstrap

    db = tmp_path / "reva.db"
    db.write_bytes(b"live bytes")
    snap = tmp_path / "snap.db"
    snap.write_bytes(b"snapshot bytes")

    def explode(src: object, dst: object) -> None:
        Path(str(dst)).write_bytes(b"par")  # a partial temp file
        raise OSError("disk full")

    monkeypatch.setattr(bootstrap.shutil, "copyfile", explode)

    with pytest.raises(StorageError, match="restore failed"):
        bootstrap._restore(snap, db, cause=RuntimeError("x"))

    assert db.read_bytes() == b"live bytes"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".restore")] == []


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_restore_fails_loudly_if_a_wal_file_cannot_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    import reva_core.storage.bootstrap as bootstrap

    db = tmp_path / "reva.db"
    db.write_bytes(b"live bytes")
    (tmp_path / f"reva.db{suffix}").write_bytes(b"stale")
    snap = tmp_path / "snap.db"
    snap.write_bytes(b"snapshot bytes")
    real_unlink = Path.unlink

    def locked(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(suffix):
            raise PermissionError("in use")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)

    with pytest.raises(StorageError, match=suffix):
        bootstrap._restore(snap, db, cause=RuntimeError("x"))

    assert db.read_bytes() == b"live bytes"  # not restored over a stale WAL


def test_restore_replaces_the_database_atomically_and_clears_old_wal_files(tmp_path: Path) -> None:
    import reva_core.storage.bootstrap as bootstrap

    db = tmp_path / "reva.db"
    db.write_bytes(b"half migrated")
    for suffix in ("-wal", "-shm"):
        (tmp_path / f"reva.db{suffix}").write_bytes(b"stale")
    snap = tmp_path / "snap.db"
    snap.write_bytes(b"snapshot bytes")

    bootstrap._restore(snap, db, cause=RuntimeError("x"))

    assert db.read_bytes() == b"snapshot bytes"
    assert not (tmp_path / "reva.db-wal").exists() and not (tmp_path / "reva.db-shm").exists()
    assert snap.exists()  # the snapshot is kept; it is still the only good copy


@pytest.mark.parametrize("failure", [RuntimeError("boom"), OSError("io"), KeyboardInterrupt()])
def test_any_failure_during_an_upgrade_restores_not_only_storage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    import reva_core.storage.bootstrap as bootstrap

    db = tmp_path / "reva.db"
    old = open_connection(db)
    apply_migrations(old, MIGRATIONS[:2])
    old.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (-1, 'marker', 'x')"
    )
    old.close()

    def half_then_fail(c: sqlite3.Connection) -> int:
        apply_migrations(c, MIGRATIONS[:3])  # really changes the file first
        raise failure

    monkeypatch.setattr(bootstrap, "apply_migrations", half_then_fail)

    with pytest.raises(type(failure)):
        initialize_database(db)

    versions, names = _state(db)
    assert versions == {1, 2, -1} and "device_grants" not in names


def test_the_connection_is_closed_when_the_snapshot_cannot_be_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reva_core.storage.bootstrap as bootstrap

    db = tmp_path / "reva.db"
    old = open_connection(db)
    apply_migrations(old, MIGRATIONS[:2])
    old.close()
    opened: list[sqlite3.Connection] = []
    real_open = bootstrap.open_connection

    def tracking(path: Path) -> sqlite3.Connection:
        opened.append(real_open(path))
        return opened[-1]

    def refuse(*_a: object, **_k: object) -> Path:
        raise StorageError("could not take a database snapshot: disk full")

    monkeypatch.setattr(bootstrap, "open_connection", tracking)
    monkeypatch.setattr(bootstrap, "snapshot", refuse)

    with pytest.raises(StorageError, match="snapshot"):
        initialize_database(db)

    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")  # closed, not leaked
    assert _state(db)[0] == {1, 2}  # and nothing was migrated
