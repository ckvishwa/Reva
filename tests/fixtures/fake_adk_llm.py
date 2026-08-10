"""A scripted `google.adk.models.base_llm.BaseLlm` for Slice 5 tests.

Drives the REAL ADK `Runner`/`LlmAgent`/tool-calling loop end to end
against a REAL temp SQLite memory store, with zero network calls and
zero dependency on a running Ollama server — only the model turn
itself is scripted. This is not a Google ADK internals test; it tests
REVA's own orchestrator/tool wiring by giving it deterministic model
output to react to, the same way `FakeLLMProvider`/`FailingLLMProvider`
let Phase 1A tests avoid a real vendor call.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def text_turn(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def function_call_turn(name: str, args: dict[str, Any]) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
        )
    )


class ScriptedAdkLlm(BaseLlm):
    """Yields `turns` in order, one per `generate_content_async` call.

    Each element of `turns` is popped for one model turn — a tool-call
    turn followed by a text turn reproduces the real two-turn
    function-calling loop ADK drives against a real model.
    """

    model: str = "scripted-test-model"
    turns: list[LlmResponse] = []
    requests: list[LlmRequest] = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        index = len(self.requests) - 1
        if index >= len(self.turns):
            raise AssertionError(
                f"ScriptedAdkLlm received more model turns ({index + 1}) than scripted "
                f"({len(self.turns)}) — the agent kept going past the last scripted reply."
            )
        yield self.turns[index]


class FailingAdkLlm(BaseLlm):
    """Always raises — simulates the model/provider being unreachable."""

    model: str = "failing-test-model"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        raise RuntimeError("fake model connection refused")
        yield  # pragma: no cover - unreachable, satisfies the generator type
