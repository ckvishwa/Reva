"""`AdkAssistantOrchestrator` — the ADK implementation of
`AssistantOrchestrator`.

Owns the ADK `Runner`, the long-lived `InMemorySessionService` (ADK
session/runtime state — see module docstring below), and builds a
fresh `RevaAgent` + tool closures bound to the current request's
connection/device/correlation id on every `respond()` call. Rebuilding
the agent per call is cheap (no I/O — the agent is a small object
graph) and is how the request-scoped correlation id reaches the
`search_memory` tool's audit trail without threading state through
ADK's session machinery.

ADK session vs. REVA durable memory
------------------------------------
`InMemorySessionService` holds ADK's own per-conversation runtime state
(the message history ADK feeds back to the model within one
conversation). It is intentionally in-memory and per-process: it is
NOT persisted, NOT REVA durable memory, and vanishes on restart. REVA's
durable, user-owned memory lives only in the `memories` SQLite table,
reached exclusively through `agent/tools/memory.py`'s `search_memory`
(read) and the existing `POST /v1/memories` explicit-create path
(write) — this orchestrator never touches that table directly, and
never gives ADK's session store anything durable to hold.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from reva_core.agent.orchestrator import AssistantResponse
from reva_core.agent.reva_agent import build_reva_agent
from reva_core.agent.tools.memory import build_search_memory_tool
from reva_core.agent.tools.system import get_current_time
from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.repositories.audit_repository import AuditRepository

if TYPE_CHECKING:
    from google.adk.models.base_llm import BaseLlm
    from google.adk.sessions import BaseSessionService

_APP_NAME = "reva"
_DEFAULT_TIMEOUT_SECONDS = 30.0


class AdkAssistantOrchestrator:
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        origin_device_id: str,
        model: str | BaseLlm,
        session_service: BaseSessionService | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._conn = conn
        self._origin_device_id = origin_device_id
        self._model = model
        # InMemorySessionService.__init__ ships without a return annotation
        # upstream — the untyped-call warning is about ADK's own signature,
        # not anything unclear on our side.
        self._session_service = session_service or InMemorySessionService()  # type: ignore[no-untyped-call]
        self._timeout_seconds = timeout_seconds

    async def respond(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
        correlation_id: str,
    ) -> AssistantResponse:
        audit = AuditRepository(self._conn)
        audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.PROVIDER,
                action="adk_orchestration_started",
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                actor_device_id=self._origin_device_id,
                metadata={"conversation_id": conversation_id, "message_length": len(message)},
                occurred_at=utc_now(),
            )
        )

        search_memory = build_search_memory_tool(self._conn, user_id, correlation_id)
        agent = build_reva_agent(model=self._model, tools=[search_memory, get_current_time])
        runner = Runner(
            app_name=_APP_NAME,
            agent=agent,
            session_service=self._session_service,
            auto_create_session=True,
        )

        try:
            final_text, tool_names = await asyncio.wait_for(
                self._run(runner, user_id=user_id, session_id=conversation_id, message=message),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            self._record_failure(audit, correlation_id, kind="timeout")
            raise ProviderError(
                ProviderErrorKind.TIMEOUT, "ADK orchestration did not respond in time."
            ) from exc
        except Exception as exc:
            self._record_failure(audit, correlation_id, kind="unavailable")
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "ADK orchestration is currently unavailable."
            ) from exc

        if final_text is None:
            self._record_failure(audit, correlation_id, kind="invalid_response")
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "ADK produced no final response text."
            )

        for tool_name in tool_names:
            audit.insert(
                AuditEvent(
                    id=new_id(),
                    category=AuditEventCategory.TOOL,
                    action="tool_invoked",
                    outcome=AuditOutcome.SUCCESS,
                    correlation_id=correlation_id,
                    actor_device_id=self._origin_device_id,
                    metadata={"tool_name": tool_name},
                    occurred_at=utc_now(),
                )
            )

        audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.PROVIDER,
                action="adk_orchestration_completed",
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                actor_device_id=self._origin_device_id,
                metadata={"reply_length": len(final_text), "tool_call_count": len(tool_names)},
                occurred_at=utc_now(),
            )
        )
        return AssistantResponse(reply=final_text)

    @staticmethod
    async def _run(
        runner: Runner, *, user_id: str, session_id: str, message: str
    ) -> tuple[str | None, list[str]]:
        content = types.Content(role="user", parts=[types.Part(text=message)])
        final_text: str | None = None
        tool_names: list[str] = []

        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            for call in event.get_function_calls():
                if call.name:
                    tool_names.append(call.name)
            if event.is_final_response() and event.content and event.content.parts:
                text_parts = [part.text for part in event.content.parts if part.text]
                if text_parts:
                    final_text = "".join(text_parts)

        return final_text, tool_names

    def _record_failure(self, audit: AuditRepository, correlation_id: str, *, kind: str) -> None:
        audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.PROVIDER,
                action="adk_orchestration_failed",
                outcome=AuditOutcome.FAILURE,
                correlation_id=correlation_id,
                actor_device_id=self._origin_device_id,
                metadata={"error_kind": kind},
                occurred_at=utc_now(),
            )
        )


def build_adk_orchestrator(
    *,
    conn: sqlite3.Connection,
    origin_device_id: str,
    model_name: str,
    model_api_base: str,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> AdkAssistantOrchestrator:
    """Builds the production `AdkAssistantOrchestrator` against a real
    LiteLlm-wrapped model endpoint. Imports `LiteLlm` lazily so that
    constructing this is the only place `litellm` needs to be
    importable — everything else in this module only depends on
    `google.adk`'s core (non-`extensions`) package.
    """
    from google.adk.models.lite_llm import LiteLlm

    model = LiteLlm(model=model_name, api_base=model_api_base)
    return AdkAssistantOrchestrator(
        conn=conn,
        origin_device_id=origin_device_id,
        model=model,
        timeout_seconds=timeout_seconds,
    )
