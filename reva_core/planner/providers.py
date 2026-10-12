"""Transport adapters for local Ollama and opt-in Anthropic planning."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

JsonDict = dict[str, Any]

_TOOL_FORMAT: JsonDict = {
    "type": "object",
    "properties": {
        "capability_id": {"type": "string"},
        "target_device_id": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["capability_id", "target_device_id", "args"],
    "additionalProperties": False,
}
_KINDS = ("answer", "clarify", "propose_action", "propose_plan")
_CLASSIFY_FORMAT: JsonDict = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": list(_KINDS)}},
    "required": ["kind"],
    "additionalProperties": False,
}
_KIND_FIELD: dict[str, tuple[str, JsonDict]] = {
    "answer": ("text", {"type": "string"}),
    "clarify": ("question", {"type": "string"}),
    "propose_action": ("tool", _TOOL_FORMAT),
    "propose_plan": ("steps", {"type": "array", "items": _TOOL_FORMAT}),
}


def _decision_format(kind: str, capabilities: list[JsonDict]) -> JsonDict:
    field, field_schema = _KIND_FIELD[kind]
    if kind == "propose_action" and len(capabilities) == 1:
        field_schema = {
            **_TOOL_FORMAT,
            "properties": {
                **_TOOL_FORMAT["properties"],
                "capability_id": {"type": "string", "enum": [capabilities[0]["capability_id"]]},
                "args": capabilities[0]["args_schema"],
            },
        }
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "session_id": {"type": "string", "enum": ["current"]},
            "turn_id": {"type": "string", "enum": ["current"]},
            "kind": {"type": "string", "enum": [kind]},
            field: field_schema,
        },
        "required": ["schema_version", "session_id", "turn_id", "kind", field],
        "additionalProperties": False,
    }


_CLASSIFIER = (
    "Choose exactly one PlannerDecision kind. Factual questions answer directly from knowledge: "
    "answer. Explicit request to use a listed capability: propose_action. "
    "Two related actions: propose_plan. Missing or unclear target: clarify. "
    "A short phrase such as 'open it' with no previous context is clarify. "
    "Return only JSON with kind."
)
_SYSTEM = (
    "You are REVA's planner. Return one JSON object matching the required schema. "
    "Always include schema_version='1.0', session_id='current', turn_id='current'. "
    "For a general knowledge question, answer from knowledge with kind='answer' and text; "
    "never call an app tool to answer a factual question. "
    "For an explicit app-opening request, use kind='propose_action' and a listed capability. "
    "For an ambiguous request, use kind='clarify' and question. "
    "A tool has capability_id, target_device_id='local', and args exactly matching its "
    "capability's args_schema. Only listed capabilities exist. Do not claim action success. "
    'Example factual answer: {"schema_version":"1.0","session_id":"current",'
    '"turn_id":"current","kind":"answer","text":"Tokyo."}. '
    "Return JSON only."
)


def _consented_input(transcript: str, capabilities: list[JsonDict]) -> str:
    return json.dumps({"transcript": transcript, "capabilities": capabilities})


class OllamaDecisionProvider:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        model: str = "qwen2.5:3b-instruct-q4_K_M",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 30,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._model = model
        self._url = base_url.rstrip("/") + "/api/chat"

    async def decide(self, *, transcript: str, capabilities: list[JsonDict]) -> str:
        payload = _consented_input(transcript, capabilities)
        classification = await self._client.post(
            self._url,
            json={
                "model": self._model,
                "stream": False,
                "format": _CLASSIFY_FORMAT,
                "options": {"temperature": 0, "num_predict": 32},
                "messages": [
                    {"role": "system", "content": _CLASSIFIER},
                    {"role": "user", "content": payload},
                ],
            },
        )
        classification.raise_for_status()
        kind_result = json.loads(classification.json()["message"]["content"])
        if set(kind_result) != {"kind"} or kind_result["kind"] not in _KINDS:
            raise ValueError("invalid planner classification")
        kind = kind_result["kind"]
        if kind == "propose_action" and len(capabilities) == 1:
            capability = capabilities[0]
            if capability["capability_id"] == "windows.app.open":
                choices = (
                    capability["args_schema"]
                    .get("properties", {})
                    .get("app_key", {})
                    .get("enum", [])
                )
                if not any(
                    re.search(r"\b" + re.escape(str(choice)) + r"\b", transcript, re.IGNORECASE)
                    for choice in choices
                ):
                    kind = "clarify"
        field = _KIND_FIELD[kind][0]
        response = await self._client.post(
            self._url,
            json={
                "model": self._model,
                "stream": False,
                "format": _decision_format(kind, capabilities),
                "options": {"temperature": 0, "num_predict": 512},
                "messages": [
                    {
                        "role": "system",
                        "content": _SYSTEM
                        + f" Chosen kind: {kind}. Include only base fields and {field}.",
                    },
                    {"role": "user", "content": payload},
                ],
            },
        )
        response.raise_for_status()
        return str(response.json()["message"]["content"])


class AnthropicDecisionProvider:
    def __init__(
        self,
        *,
        key_reader: Callable[[], str | None],
        client: httpx.AsyncClient | None = None,
        model: str = "claude-sonnet-4-6",
        timeout_seconds: float = 30,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._key_reader = key_reader
        self._model = model

    async def decide(self, *, transcript: str, capabilities: list[JsonDict]) -> str:
        key = self._key_reader()
        if not key:
            raise RuntimeError("Anthropic credential unavailable")
        payload = _consented_input(transcript, capabilities)
        classification = await self._complete(
            key=key, payload=payload, system=_CLASSIFIER, schema=_CLASSIFY_FORMAT, max_tokens=64
        )
        kind_result = json.loads(classification)
        if set(kind_result) != {"kind"} or kind_result["kind"] not in _KINDS:
            raise ValueError("invalid planner classification")
        kind = kind_result["kind"]
        field = _KIND_FIELD[kind][0]
        return await self._complete(
            key=key,
            payload=payload,
            system=_SYSTEM + f" Chosen kind: {kind}. Include only base fields and {field}.",
            schema=_decision_format(kind, capabilities),
            max_tokens=512,
        )

    async def _complete(
        self, *, key: str, payload: str, system: str, schema: JsonDict, max_tokens: int
    ) -> str:
        response = await self._client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": max_tokens,
                "system": system,
                "output_config": {"format": {"type": "json_schema", "schema": schema}},
                "messages": [{"role": "user", "content": payload}],
            },
        )
        response.raise_for_status()
        return "".join(
            block["text"] for block in response.json()["content"] if block.get("type") == "text"
        )
