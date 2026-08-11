"""`reva_core/agent/` behavior — the REVA-owned tool boundary ADK's
RevaAgent calls into.

Deliberately does not unit-test Google ADK internals (Runner, session
service, function-declaration generation). These tests exercise
REVA's own boundary: what `search_memory`/`get_current_time` do with
real repository/audit objects against a real temp SQLite database, and
the static invariant that this package never touches SQLite directly
or exposes a memory-mutating tool (ADR-006).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from reva_core.agent.reva_agent import build_reva_agent
from reva_core.agent.tools.memory import build_search_memory_tool
from reva_core.agent.tools.system import get_current_time
from reva_core.shared.contracts.memory import MemoryCategory
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.audit_repository import AuditRepository
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_CID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def store(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    yield conn, device_id
    conn.close()


def _make_memory(conn, device_id, content: str) -> None:
    from reva_core.shared.contracts.memory import Memory, MemorySourceReference, RetentionState
    from reva_core.shared.ids import new_id

    now = utc_now()
    MemoryRepository(conn).insert(
        Memory(
            id=new_id(),
            category=MemoryCategory.NOTE,
            content=content,
            source=MemorySourceReference(origin_device_id=device_id, note="test_fixture"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )


async def test_search_memory_returns_matching_content(store):
    conn, device_id = store
    _make_memory(conn, device_id, "My test color is cobalt.")
    _make_memory(conn, device_id, "unrelated memory")
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    result = await search_memory(query="cobalt")

    assert result["status"] == "success"
    assert result["results"] == ["My test color is cobalt."]


async def test_search_memory_case_insensitive_and_trims_query(store):
    conn, device_id = store
    _make_memory(conn, device_id, "REVA uses Push-To-Talk")
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    result = await search_memory(query="  PUSH-to-talk  ")

    assert result["status"] == "success"
    assert len(result["results"]) == 1


async def test_search_memory_limit_is_bounded_to_max(store):
    conn, device_id = store
    for i in range(15):
        _make_memory(conn, device_id, f"bounded memory {i}")
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    result = await search_memory(query="bounded memory", limit=10_000)

    assert result["status"] == "success"
    assert len(result["results"]) <= 10


async def test_search_memory_zero_results_returns_empty_success(store):
    conn, device_id = store
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    result = await search_memory(query="nonexistent-term-xyz")

    assert result == {"status": "success", "results": []}


@pytest.mark.parametrize("bad_query", ["", "   ", "\t\n"])
async def test_search_memory_invalid_query_rejected_without_touching_repository(store, bad_query):
    conn, device_id = store
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    result = await search_memory(query=bad_query)

    assert result["status"] == "error"
    # No memory_query_requested/completed audit event: the repository was
    # never reached for a rejected, empty query.
    events = AuditRepository(conn).list_recent(50)
    assert not any(e.action.startswith("memory_query") for e in events)


async def test_search_memory_non_numeric_limit_falls_back_to_default_without_crashing(store):
    conn, device_id = store
    _make_memory(conn, device_id, "fallback limit test")
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    result = await search_memory(query="fallback limit test", limit="not-a-number")

    assert result["status"] == "success"


async def test_search_memory_repository_exception_handled_safely(store, monkeypatch):
    conn, device_id = store
    _make_memory(conn, device_id, "will not be reached")
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    def _boom(self, text, limit):
        raise RuntimeError("simulated repository failure")

    monkeypatch.setattr(MemoryRepository, "query", _boom)

    result = await search_memory(query="anything")

    assert result == {
        "status": "error",
        "message": "memory search is temporarily unavailable",
    }
    events = AuditRepository(conn).list_recent(50)
    failed = [e for e in events if e.action == "memory_query_completed" and e.outcome == "failure"]
    assert len(failed) == 1


def test_search_memory_has_no_owner_override_parameter(store):
    """The model can never redirect a search to another device's data:
    the only parameters exposed to it are query/limit — origin_device_id
    is bound at tool-construction time, outside model control."""
    conn, device_id = store
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    params = set(inspect.signature(search_memory).parameters)

    assert params == {"query", "limit"}


def test_get_current_time_returns_utc_iso8601():
    result = get_current_time()

    assert result["status"] == "success"
    parsed = result["current_time_utc"]
    # utc_now().isoformat() always carries a UTC offset (+00:00) — this
    # is the same abstraction every durable REVA timestamp uses.
    assert re.search(r"\+00:00$", parsed)


def test_agent_module_never_opens_or_queries_sqlite_directly():
    """`reva_core/agent/` may type-hint a `sqlite3.Connection` handed to it
    by `CoreLifecycle` (that's `import sqlite3` — legitimate, appears in
    both `adk_orchestrator.py` and `tools/memory.py`), but must never open
    its own connection or execute raw SQL — it only ever reaches storage
    through `MemoryRepository`/`AuditRepository`."""
    agent_dir = Path(__file__).resolve().parents[2] / "reva_core" / "agent"
    hits = []
    for path in agent_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "sqlite3.connect(" in text or re.search(r"\.execute(?:many)?\(", text):
            hits.append(path)
    assert hits == [], f"direct SQLite connection/query found in reva_core/agent/: {hits}"


def test_reva_agent_exposes_exactly_search_and_time_tools_no_mutation(store):
    conn, device_id = store
    search_memory = build_search_memory_tool(conn, device_id, _CID)
    agent = build_reva_agent(model="unused-in-this-test", tools=[search_memory, get_current_time])

    tool_names = {tool.__name__ for tool in agent.tools}

    assert tool_names == {"search_memory", "get_current_time"}
    mutating = {"remember", "create_memory", "update_memory", "delete_memory"}
    assert tool_names.isdisjoint(mutating)
