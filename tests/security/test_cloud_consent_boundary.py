import json

import httpx

from reva_core.planner.pipeline import PlannerPipeline
from reva_core.planner.providers import AnthropicDecisionProvider


class _LocalAnswer:
    async def decide(self, *, transcript, capabilities):
        return json.dumps(
            {
                "schema_version": "1.0",
                "session_id": "s",
                "turn_id": "t",
                "kind": "answer",
                "text": "Tokyo.",
            }
        )


async def test_cloud_off_makes_zero_anthropic_network_requests():
    requests = []

    def capture(request):
        requests.append(request)
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    cloud = AnthropicDecisionProvider(client=client, key_reader=lambda: "test-key")
    pipeline = PlannerPipeline(
        local=_LocalAnswer(), cloud=cloud, cloud_enabled=lambda: False, registry={}
    )
    assert await pipeline.respond("What's the capital of Japan?", memory="private") == "Tokyo."
    assert requests == []
    await client.aclose()


async def test_cloud_error_does_not_log_key_or_private_context(caplog):
    requests = []

    def capture(request):
        requests.append(request)
        return httpx.Response(500, text="test-key-sentinel")

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    cloud = AnthropicDecisionProvider(client=client, key_reader=lambda: "test-key-sentinel")
    pipeline = PlannerPipeline(
        local=_LocalAnswer(), cloud=cloud, cloud_enabled=lambda: True, registry={}
    )
    assert await pipeline.respond("What's the capital of Japan?", memory="private") == "Tokyo."
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["messages"][0]["content"] == json.dumps(
        {"transcript": "What's the capital of Japan?", "capabilities": []}
    )
    assert "private" not in json.dumps(body)
    assert "test-key-sentinel" not in caplog.text
    await client.aclose()
