import json

from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.planner.orchestrator import PlannerAssistantOrchestrator
from reva_core.planner.pipeline import ExecutionEvidence
from reva_core.planner.providers import OllamaDecisionProvider


def test_core_uses_local_planner_by_default(tmp_path):
    lifecycle = CoreLifecycle(load_settings(_env_file=None, data_dir=tmp_path))
    try:
        lifecycle.startup()
        assert isinstance(lifecycle.assistant_orchestrator, PlannerAssistantOrchestrator)
    finally:
        lifecycle.shutdown()


def test_core_routes_model_action_through_authorize_and_executor(tmp_path, monkeypatch):
    class Executor:
        def __init__(self):
            self.calls = []

        async def execute(self, tool, decision):
            self.calls.append((tool, decision))
            return ExecutionEvidence("verified", "Opened Calculator.")

    async def propose(self, *, transcript, capabilities):
        return json.dumps(
            {
                "schema_version": "1.0",
                "session_id": "s",
                "turn_id": "t",
                "kind": "propose_action",
                "tool": {
                    "capability_id": "windows.app.open",
                    "target_device_id": "local",
                    "args": {"app_key": "calculator"},
                },
            }
        )

    monkeypatch.setattr(OllamaDecisionProvider, "decide", propose)
    executor = Executor()
    lifecycle = CoreLifecycle(
        load_settings(_env_file=None, data_dir=tmp_path), planner_executor=executor
    )
    try:
        lifecycle.startup()
        client = TestClient(create_app(lifecycle))
        response = client.post(
            "/v1/messages",
            json={"content": "Could you launch Calculator?"},
            headers={"Authorization": f"Bearer {lifecycle.local_token}"},
        )
        assert response.status_code == 200
        assert response.json()["reply"] == "Opened Calculator."
        assert executor.calls[0][1].tier == "T1"
    finally:
        lifecycle.shutdown()
