"""Invariants hybrid retrieval must not weaken: no owner-override
parameter on search_memory, no memory-mutation tool, audit metadata
never carries full content or raw vectors, C# never appears as a
consumer of ranking/embedding code (verified by absence of any such
import path — the real enforcement is architectural: reva_core has no
knowledge of desktop/ at all)."""

from __future__ import annotations

import inspect

from reva_core.agent.reva_agent import build_reva_agent
from reva_core.agent.tools.memory import build_search_memory_tool
from reva_core.agent.tools.system import get_current_time
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.audit_repository import AuditRepository
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_CID = "77777777-7777-7777-7777-777777777777"


def test_search_memory_still_exposes_only_query_and_limit(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    search_memory = build_search_memory_tool(conn, device_id, _CID, embedding_provider=None)

    params = set(inspect.signature(search_memory).parameters)

    assert params == {"query", "limit"}
    conn.close()


def test_agent_still_exposes_exactly_two_read_only_tools(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    search_memory = build_search_memory_tool(conn, device_id, _CID)
    agent = build_reva_agent(model="unused-in-this-test", tools=[search_memory, get_current_time])

    tool_names = {tool.__name__ for tool in agent.tools}

    assert tool_names == {"search_memory", "get_current_time"}
    assert tool_names.isdisjoint({"remember", "create_memory", "update_memory", "delete_memory"})
    conn.close()


async def test_query_audit_metadata_never_contains_memory_content(tmp_path):
    from reva_core.shared.contracts.memory import (
        Memory,
        MemoryCategory,
        MemorySourceReference,
        RetentionState,
    )
    from reva_core.shared.ids import new_id
    from reva_core.shared.time import utc_now

    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    now = utc_now()
    secret_content = "a very specific secret memory content string"
    MemoryRepository(conn).insert(
        Memory(
            id=new_id(),
            category=MemoryCategory.NOTE,
            content=secret_content,
            source=MemorySourceReference(origin_device_id=device_id, note="test"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    await search_memory(query="secret memory")

    events = AuditRepository(conn).list_recent(50)
    for event in events:
        assert secret_content not in str(event.metadata)
    conn.close()


def test_reva_core_package_has_no_reference_to_desktop_directory():
    """Architectural check, not a runtime one: reva_core/ must never
    import or reference the C# desktop project — ranking/embedding logic
    living only in Python is enforced by there being no code path for it
    to leak through, not by convention alone."""
    import pathlib

    reva_core_dir = pathlib.Path(__file__).resolve().parents[2] / "reva_core"
    for path in reva_core_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Reva.Desktop" not in text
        assert "desktop\\" not in text and "desktop/" not in text
