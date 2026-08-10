"""Framework-neutral assistant orchestration boundary.

The rest of Core (`orchestration/typed_interaction.py`) depends only on
`AssistantOrchestrator`/`AssistantResponse` — never on ADK, never on any
other orchestration framework. `AdkAssistantOrchestrator`
(`agent/adk_orchestrator.py`) is the only implementation today, but the
Protocol is the seam a future implementation would slot into without
touching orchestration or the API layer. See
docs/adr/ADR-017-google-adk-orchestration-dependency.md.

This module intentionally imports nothing from `google.adk` — that is
the whole point of the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AssistantResponse:
    reply: str


@runtime_checkable
class AssistantOrchestrator(Protocol):
    """Produces a conversational reply for one typed message.

    Deliberately narrow: no memory-mutation capability reaches this
    boundary at all (ADR-006) — an orchestrator can only ever produce
    text, never a durable write. `correlation_id` is not in the
    originally-sketched signature; it is added here because every other
    REVA service method threads a correlation_id through for audit
    traceability, and `AdkAssistantOrchestrator` needs it to tie its
    audit events back to the request that triggered them.
    """

    async def respond(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
        correlation_id: str,
    ) -> AssistantResponse: ...
