import json

import httpx
import pytest

from reva_core.planner.providers import AnthropicDecisionProvider, OllamaDecisionProvider


@pytest.mark.asyncio
async def test_ollama_request_contains_only_transcript_and_capability_list():
    captured = []

    def respond(request):
        captured.append(request)
        content = '{"kind":"answer"}' if len(captured) == 1 else "{}"
        return httpx.Response(200, json={"message": {"content": content}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OllamaDecisionProvider(client=client, model="qwen2.5:3b-instruct-q4_K_M")
    capability = {
        "capability_id": "windows.app.open",
        "args_schema": {
            "type": "object",
            "required": ["app_key"],
            "properties": {"app_key": {"enum": ["calculator"]}},
        },
    }
    assert await provider.decide(transcript="Japan?", capabilities=[capability]) == "{}"
    body = json.loads(captured[0].content)
    assert captured[0].url.host == "127.0.0.1"
    assert isinstance(body["format"], dict)
    assert body["messages"][1]["content"] == json.dumps(
        {"transcript": "Japan?", "capabilities": [capability]}
    )
    assert "memory" not in json.dumps(body).lower()
    assert len(captured) == 2
    assert (
        json.loads(captured[1].content)["messages"][1]["content"] == body["messages"][1]["content"]
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_ollama_action_format_requires_registered_arguments():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        content = '{"kind":"propose_action"}' if len(requests) == 1 else "{}"
        return httpx.Response(200, json={"message": {"content": content}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    capability = {
        "capability_id": "windows.app.open",
        "args_schema": {
            "type": "object",
            "required": ["app_key"],
            "properties": {"app_key": {"enum": ["calculator"]}},
        },
    }
    provider = OllamaDecisionProvider(client=client)
    await provider.decide(transcript="Please launch Calculator", capabilities=[capability])
    assert (
        requests[1]["format"]["properties"]["tool"]["properties"]["args"]
        == capability["args_schema"]
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_ollama_does_not_propose_app_action_without_named_target():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        content = '{"kind":"propose_action"}' if len(requests) == 1 else "{}"
        return httpx.Response(200, json={"message": {"content": content}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    capability = {
        "capability_id": "windows.app.open",
        "args_schema": {
            "type": "object",
            "required": ["app_key"],
            "properties": {"app_key": {"enum": ["calculator", "notepad"]}},
        },
    }
    provider = OllamaDecisionProvider(client=client)
    await provider.decide(transcript="Open it", capabilities=[capability])
    assert requests[1]["format"]["properties"]["kind"]["enum"] == ["clarify"]
    await client.aclose()


@pytest.mark.asyncio
async def test_anthropic_request_uses_credential_manager_key_and_no_private_context(caplog):
    captured = []

    def respond(request):
        captured.append(request)
        content = '{"kind":"answer"}' if len(captured) == 1 else '{}'
        return httpx.Response(200, json={"content": [{"type": "text", "text": content}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = AnthropicDecisionProvider(
        client=client, key_reader=lambda: "test-secret-never-log", model="claude-sonnet-4-5"
    )
    assert await provider.decide(transcript="Japan?", capabilities=[]) == "{}"
    assert captured[0].headers["x-api-key"] == "test-secret-never-log"
    body = json.loads(captured[0].content)
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["messages"][0]["content"] == json.dumps(
        {"transcript": "Japan?", "capabilities": []}
    )
    assert len(captured) == 2
    assert captured[1].headers["x-api-key"] == "test-secret-never-log"
    assert "test-secret-never-log" not in caplog.text
    await client.aclose()
