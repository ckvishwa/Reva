import asyncio
import json

import pytest

from reva_core.planner.pipeline import (
    ExecutionEvidence,
    PlannerPipeline,
    authorize,
    validate_decision,
)

REGISTRY = {
    "windows.app.open": {
        "tier": "T1",
        "args_schema": {
            "type": "object",
            "required": ["app_key"],
            "properties": {"app_key": {"enum": ["calculator"]}},
            "additionalProperties": False,
        },
    },
}


class RecordingProvider:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def decide(self, *, transcript, capabilities):
        self.calls.append((transcript, capabilities))
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def answer(text="Tokyo"):
    return json.dumps(
        {"schema_version": "1.0", "session_id": "s", "turn_id": "t", "kind": "answer", "text": text}
    )


def action(**extra):
    return {
        "schema_version": "1.0",
        "session_id": "s",
        "turn_id": "t",
        "kind": "propose_action",
        "tool": {
            "capability_id": "windows.app.open",
            "target_device_id": "pc",
            "args": {"app_key": "calculator"},
        },
        **extra,
    }


def test_schema_invalid_output_is_rejected():
    with pytest.raises(ValueError):
        validate_decision('{"kind":"answer","text":"Tokyo"}', REGISTRY)
    with pytest.raises(ValueError):
        validate_decision(json.dumps(action(tier="T0")), REGISTRY)


def test_only_registered_capabilities_and_arguments_are_accepted():
    unregistered = action()
    unregistered["tool"]["capability_id"] = "shell.run"
    with pytest.raises(ValueError):
        validate_decision(json.dumps(unregistered), REGISTRY)
    invalid_args = action()
    invalid_args["tool"]["args"]["app_key"] = "cmd"
    with pytest.raises(ValueError):
        validate_decision(json.dumps(invalid_args), REGISTRY)


def test_authorize_uses_registry_tier_even_if_proposal_is_tampered():
    proposal = action()
    proposal["tier"] = "T0"
    decision = authorize(proposal["tool"], REGISTRY)
    assert decision.tier == "T1"
    assert decision.allowed


async def test_cloud_off_sends_nothing_to_cloud_and_local_sees_only_transcript_and_capabilities():
    cloud = RecordingProvider(answer("cloud"))
    local = RecordingProvider(answer())
    pipeline = PlannerPipeline(
        local=local, cloud=cloud, cloud_enabled=lambda: False, registry=REGISTRY
    )
    result = await pipeline.respond("what's the capital of Japan", memory={"secret": "private"})
    assert result == "Tokyo"
    assert cloud.calls == []
    assert local.calls == [
        (
            "what's the capital of Japan",
            [
                {
                    "capability_id": "windows.app.open",
                    "args_schema": REGISTRY["windows.app.open"]["args_schema"],
                }
            ],
        )
    ]


async def test_cloud_failure_falls_back_to_local_then_safe_failure():
    cloud = RecordingProvider(ConnectionError("secret-key-must-not-appear"))
    local = RecordingProvider(answer())
    pipeline = PlannerPipeline(
        local=local, cloud=cloud, cloud_enabled=lambda: True, registry=REGISTRY
    )
    assert await pipeline.respond("Japan?") == "Tokyo"
    local.output = ConnectionError("offline")
    assert await pipeline.respond("Japan?") == "I can't answer that right now."


async def test_cloud_on_prefers_anthropic_decision():
    cloud = RecordingProvider(answer("Cloud Tokyo"))
    local = RecordingProvider(answer("Local Tokyo"))
    pipeline = PlannerPipeline(
        local=local, cloud=cloud, cloud_enabled=lambda: True, registry=REGISTRY
    )
    assert await pipeline.respond("Japan?") == "Cloud Tokyo"
    assert len(cloud.calls) == 1
    assert local.calls == []


async def test_cloud_deadline_falls_back_to_local():
    class HangingCloud:
        async def decide(self, *, transcript, capabilities):
            await asyncio.sleep(1)
            return answer("cloud")

    pipeline = PlannerPipeline(
        local=RecordingProvider(answer()),
        cloud=HangingCloud(),
        cloud_enabled=lambda: True,
        registry=REGISTRY,
        provider_timeout_seconds=0.01,
    )
    assert await pipeline.respond("Japan?") == "Tokyo"


async def test_model_action_narration_never_becomes_success_without_executor_evidence():
    local = RecordingProvider(json.dumps(action()))
    pipeline = PlannerPipeline(
        local=local, cloud=None, cloud_enabled=lambda: False, registry=REGISTRY
    )
    assert await pipeline.respond("could you launch calculator") == "I can't answer that right now."


async def test_forged_answer_cannot_claim_action_success():
    local = RecordingProvider(answer("I opened Calculator successfully."))
    pipeline = PlannerPipeline(
        local=local, cloud=None, cloud_enabled=lambda: False, registry=REGISTRY
    )
    assert await pipeline.respond("Please open calculator") == "I can't answer that right now."
    local.output = answer("Calculator is now open.")
    assert await pipeline.respond("Please open calculator") == "I can't answer that right now."


async def test_action_success_is_spoken_only_from_verified_executor_evidence():
    class Executor:
        def __init__(self):
            self.calls = []

        async def execute(self, tool, decision):
            self.calls.append((tool, decision))
            return ExecutionEvidence("verified", "Opened Calculator.")

    executor = Executor()
    pipeline = PlannerPipeline(
        local=RecordingProvider(json.dumps(action())),
        cloud=None,
        cloud_enabled=lambda: False,
        registry=REGISTRY,
        executor=executor,
    )
    assert await pipeline.respond("Please open calculator") == "Opened Calculator."
    assert executor.calls[0][1].tier == "T1"
