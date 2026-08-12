"""`AdkAssistantOrchestrator` behavior, and its wiring into
`TypedInteractionService.handle_typed_message`.

Uses `ScriptedAdkLlm`/`FailingAdkLlm` (tests/fixtures/fake_adk_llm.py)
to drive the REAL ADK Runner/LlmAgent/tool-calling loop against a REAL
temp SQLite memory store — no network call, no Google ADK internals
under test, only REVA's own orchestrator/tool/audit boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest

from reva_core.agent.adk_orchestrator import AdkAssistantOrchestrator
from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.shared.contracts.memory import MemoryCategory
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.audit_repository import AuditRepository
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository
from tests.fixtures.fake_adk_llm import FailingAdkLlm, ScriptedAdkLlm, function_call_turn, text_turn

_CID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def store(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    yield conn, device_id
    conn.close()


async def test_ordinary_chat_creates_zero_tool_calls_and_zero_memory(store):
    conn, device_id = store
    model = ScriptedAdkLlm(turns=[text_turn("The sky is blue.")])
    orchestrator = AdkAssistantOrchestrator(conn=conn, origin_device_id=device_id, model=model)

    response = await orchestrator.respond(
        user_id=device_id, conversation_id="c1", message="why is the sky blue", correlation_id=_CID
    )

    assert response.reply == "The sky is blue."
    assert MemoryRepository(conn).query("", 100) == []
    events = AuditRepository(conn).list_recent(50)
    assert not any(e.action == "tool_invoked" for e in events)


async def test_memory_question_invokes_search_memory_and_answers_correctly(store):
    conn, device_id = store
    from reva_core.shared.contracts.memory import Memory, MemorySourceReference, RetentionState
    from reva_core.shared.ids import new_id
    from reva_core.shared.time import utc_now

    now = utc_now()
    MemoryRepository(conn).insert(
        Memory(
            id=new_id(),
            category=MemoryCategory.NOTE,
            content="My test color is cobalt.",
            source=MemorySourceReference(origin_device_id=device_id, note="test_fixture"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    model = ScriptedAdkLlm(
        turns=[
            function_call_turn("search_memory", {"query": "cobalt", "limit": 5}),
            text_turn("Your test color is cobalt."),
        ]
    )
    orchestrator = AdkAssistantOrchestrator(conn=conn, origin_device_id=device_id, model=model)

    response = await orchestrator.respond(
        user_id=device_id,
        conversation_id="c1",
        message="what test color did I ask you to remember?",
        correlation_id=_CID,
    )

    assert "cobalt" in response.reply
    events = AuditRepository(conn).list_recent(50)
    assert any(
        e.action == "tool_invoked" and e.metadata.get("tool_name") == "search_memory"
        for e in events
    )
    completed = [e for e in events if e.action == "memory_query_completed"]
    assert completed and completed[0].metadata["result_count"] == 1


async def test_conversation_sessions_are_isolated(store):
    conn, device_id = store
    model = ScriptedAdkLlm(turns=[text_turn("reply one"), text_turn("reply two")])
    orchestrator = AdkAssistantOrchestrator(conn=conn, origin_device_id=device_id, model=model)

    await orchestrator.respond(
        user_id=device_id, conversation_id="conversation-a", message="hello a", correlation_id=_CID
    )
    await orchestrator.respond(
        user_id=device_id, conversation_id="conversation-b", message="hello b", correlation_id=_CID
    )

    sessions = orchestrator._session_service.sessions["reva"][device_id]
    assert set(sessions) == {"conversation-a", "conversation-b"}
    events_a = [e.content for e in sessions["conversation-a"].events]
    events_b = [e.content for e in sessions["conversation-b"].events]
    text_a = "".join(p.text or "" for c in events_a if c for p in c.parts)
    text_b = "".join(p.text or "" for c in events_b if c for p in c.parts)
    assert "hello a" in text_a
    assert "hello b" not in text_a
    assert "hello b" in text_b
    assert "hello a" not in text_b


async def test_zero_result_memory_search_produces_safe_reply(store):
    conn, device_id = store
    model = ScriptedAdkLlm(
        turns=[
            function_call_turn("search_memory", {"query": "nonexistent-xyz", "limit": 5}),
            text_turn("I have no matching memory for that."),
        ]
    )
    orchestrator = AdkAssistantOrchestrator(conn=conn, origin_device_id=device_id, model=model)

    response = await orchestrator.respond(
        user_id=device_id,
        conversation_id="c1",
        message="what about nonexistent-xyz?",
        correlation_id=_CID,
    )

    assert "no matching memory" in response.reply.lower()


async def test_tool_repository_exception_does_not_crash_orchestration(store, monkeypatch):
    conn, device_id = store

    def _boom(self, text, limit):
        raise RuntimeError("simulated repository failure")

    monkeypatch.setattr(MemoryRepository, "query", _boom)
    model = ScriptedAdkLlm(
        turns=[
            function_call_turn("search_memory", {"query": "anything", "limit": 5}),
            text_turn("I couldn't search memory just now."),
        ]
    )
    orchestrator = AdkAssistantOrchestrator(conn=conn, origin_device_id=device_id, model=model)

    response = await orchestrator.respond(
        user_id=device_id, conversation_id="c1", message="anything?", correlation_id=_CID
    )

    assert response.reply  # the agent still produced a reply, no crash


async def test_model_failure_raises_provider_error_without_leaking_details(store):
    conn, device_id = store
    orchestrator = AdkAssistantOrchestrator(
        conn=conn, origin_device_id=device_id, model=FailingAdkLlm()
    )

    with pytest.raises(ProviderError) as excinfo:
        await orchestrator.respond(
            user_id=device_id, conversation_id="c1", message="hi", correlation_id=_CID
        )

    assert excinfo.value.kind == ProviderErrorKind.UNAVAILABLE
    assert "fake model connection refused" not in str(excinfo.value)
    assert "token" not in str(excinfo.value).lower()


async def test_timeout_raises_provider_error(store):
    conn, device_id = store

    class SlowLlm(ScriptedAdkLlm):
        async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator:
            await asyncio.sleep(5)
            yield text_turn("too slow")

    orchestrator = AdkAssistantOrchestrator(
        conn=conn, origin_device_id=device_id, model=SlowLlm(), timeout_seconds=0.05
    )

    with pytest.raises(ProviderError) as excinfo:
        await orchestrator.respond(
            user_id=device_id, conversation_id="c1", message="hi", correlation_id=_CID
        )

    assert excinfo.value.kind == ProviderErrorKind.TIMEOUT


async def test_malformed_model_output_raises_provider_error(store):
    from google.adk.models.llm_response import LlmResponse

    conn, device_id = store
    # A turn with no content at all — the agent produced nothing usable.
    model = ScriptedAdkLlm(turns=[LlmResponse(content=None)])
    orchestrator = AdkAssistantOrchestrator(conn=conn, origin_device_id=device_id, model=model)

    with pytest.raises(ProviderError) as excinfo:
        await orchestrator.respond(
            user_id=device_id, conversation_id="c1", message="hi", correlation_id=_CID
        )

    assert excinfo.value.kind == ProviderErrorKind.INVALID_RESPONSE


async def test_explicit_remember_flow_unaffected_by_adk_wiring(store):
    conn, device_id = store
    orchestrator = AdkAssistantOrchestrator(
        conn=conn, origin_device_id=device_id, model=FailingAdkLlm()
    )
    svc = TypedInteractionService(conn, device_id, orchestrator=orchestrator)

    memory = await svc.create_explicit_memory(
        "REVA V1 uses push-to-talk, not always-on listening.", MemoryCategory.NOTE, (), _CID
    )

    assert memory.id
    assert memory.source.note == "explicit_api_memory_creation"
    events = AuditRepository(conn).list_recent(50)
    assert any(e.action == "memory_created" for e in events)
    # The orchestrator (and its always-failing model) was never touched —
    # the explicit-memory path has no dependency on assistant orchestration.
    assert not any(e.action.startswith("adk_orchestration") for e in events)


async def test_handle_typed_message_uses_orchestrator_reply_and_creates_no_memory(store):
    conn, device_id = store
    model = ScriptedAdkLlm(turns=[text_turn("Here is your answer.")])
    orchestrator = AdkAssistantOrchestrator(conn=conn, origin_device_id=device_id, model=model)
    svc = TypedInteractionService(conn, device_id, orchestrator=orchestrator)

    result = await svc.handle_typed_message("just chatting", _CID)

    assert result.reply == "Here is your answer."
    assert result.memory_id is None


async def test_handle_typed_message_falls_back_safely_when_orchestrator_fails(store):
    conn, device_id = store
    orchestrator = AdkAssistantOrchestrator(
        conn=conn, origin_device_id=device_id, model=FailingAdkLlm()
    )
    svc = TypedInteractionService(conn, device_id, orchestrator=orchestrator)

    result = await svc.handle_typed_message("hello while the model is down", _CID)

    assert "unavailable" in result.reply.lower()
    assert result.memory_id is None
