"""Deterministic fallback providers shipped as real Phase 1A runtime
code — not test infrastructure.

Phase 1A has no real LLM adapter (Phase 0/1A explicitly exclude cloud
credentials and vendor SDKs). `TypedInteractionService` needs *some*
`LLMProvider` to satisfy the provider boundary (ADR-005) rather than
special-casing "no provider," so `FakeLLMProvider` is the documented,
deterministic default: it echoes the prompt, makes no network call, and
is never mistaken for a real model's reasoning. Every API response
produced through it is documented as such — see
docs/architecture/data-flow.md.
"""

from __future__ import annotations

from reva_core.models.llm import LLMProvider, LLMRequest, LLMResponse


class FakeLLMProvider(LLMProvider):
    """Deterministic, vendor-free stand-in used as the Phase 1A default."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=f"Received: {request.prompt}",
            correlation_id=request.correlation_id,
        )
