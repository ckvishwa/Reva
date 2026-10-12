"""Adapter from the typed-message seam to the bounded planner."""

from __future__ import annotations

from reva_core.agent.orchestrator import AssistantResponse
from reva_core.planner.pipeline import PlannerPipeline


class PlannerAssistantOrchestrator:
    def __init__(self, pipeline: PlannerPipeline) -> None:
        self._pipeline = pipeline

    async def respond(
        self, *, user_id: str, conversation_id: str, message: str, correlation_id: str
    ) -> AssistantResponse:
        # IDs identify the local turn. They are not included in provider data.
        reply = await self._pipeline.respond(message)
        return AssistantResponse(reply=reply)
