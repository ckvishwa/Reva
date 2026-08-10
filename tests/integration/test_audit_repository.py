import pytest

from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.audit_repository import AuditRepository


def test_audit_event_round_trips_through_sqlite(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    try:
        device_id = new_id()
        conn.execute(
            "INSERT INTO devices (id, display_name, platform, paired_at) VALUES (?, ?, ?, ?)",
            (device_id, "Test PC", "windows", utc_now().isoformat()),
        )

        repo = AuditRepository(conn)
        event = AuditEvent(
            id=new_id(),
            category=AuditEventCategory.TOOL,
            action="open_url",
            outcome=AuditOutcome.SUCCESS,
            actor_device_id=device_id,
            metadata={"url": "https://example.com"},
            occurred_at=utc_now(),
        )
        repo.insert(event)

        recent = repo.list_recent()
        assert len(recent) == 1
        assert recent[0] == event
    finally:
        conn.close()


def test_list_recent_orders_newest_first(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    try:
        repo = AuditRepository(conn)
        from datetime import timedelta

        base = utc_now()
        older = AuditEvent(
            id=new_id(),
            category=AuditEventCategory.SYSTEM,
            action="startup",
            outcome=AuditOutcome.SUCCESS,
            occurred_at=base - timedelta(minutes=1),
        )
        newer = AuditEvent(
            id=new_id(),
            category=AuditEventCategory.SYSTEM,
            action="shutdown",
            outcome=AuditOutcome.SUCCESS,
            occurred_at=base,
        )
        repo.insert(older)
        repo.insert(newer)

        recent = repo.list_recent()
        assert recent[0].action == "shutdown"
        assert recent[1].action == "startup"
    finally:
        conn.close()


def test_insert_wraps_sqlite_errors_as_storage_error(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    try:
        repo = AuditRepository(conn)
        event = AuditEvent(
            id=new_id(),
            category=AuditEventCategory.SYSTEM,
            action="startup",
            outcome=AuditOutcome.SUCCESS,
            actor_device_id=new_id(),  # references a device that was never inserted
            occurred_at=utc_now(),
        )
        with pytest.raises(StorageError):
            repo.insert(event)
    finally:
        conn.close()
