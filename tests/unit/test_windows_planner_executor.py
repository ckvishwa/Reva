from reva_core.planner.pipeline import AuthorizationDecision
from reva_core.planner.windows_executor import WindowsActionExecutor, build_windows_registry


def test_live_registry_exposes_only_implemented_windows_action():
    registry = build_windows_registry()
    assert list(registry) == ["windows.app.open"]
    keys = registry["windows.app.open"]["args_schema"]["properties"]["app_key"]["enum"]
    assert set(keys) == {"calculator", "notepad", "chrome", "vscode"}


class FakeRuntime:
    def __init__(self, observed):
        self.observed = observed
        self.launched = []

    def launch(self, target):
        self.launched.append(target)

    def is_running(self, names):
        return self.observed


async def test_registered_app_open_returns_verified_only_after_process_observation():
    runtime = FakeRuntime(True)
    executor = WindowsActionExecutor(runtime=runtime)
    result = await executor.execute(
        {
            "capability_id": "windows.app.open",
            "target_device_id": "local",
            "args": {"app_key": "calculator"},
        },
        AuthorizationDecision(True, "T1"),
    )
    assert result.status == "verified"
    assert result.message == "Opened Calculator."
    assert runtime.launched == ["calc.exe"]


async def test_launch_without_process_evidence_cannot_claim_success():
    runtime = FakeRuntime(False)
    executor = WindowsActionExecutor(runtime=runtime)
    result = await executor.execute(
        {
            "capability_id": "windows.app.open",
            "target_device_id": "local",
            "args": {"app_key": "notepad"},
        },
        AuthorizationDecision(True, "T1"),
    )
    assert result.status == "unknown"
    assert result.message == ""


async def test_unregistered_target_or_tampered_tier_never_reaches_os():
    runtime = FakeRuntime(True)
    executor = WindowsActionExecutor(runtime=runtime)
    result = await executor.execute(
        {
            "capability_id": "windows.app.open",
            "target_device_id": "local",
            "args": {"app_key": "cmd"},
        },
        AuthorizationDecision(True, "T1"),
    )
    assert result.status == "denied"
    result = await executor.execute(
        {
            "capability_id": "windows.app.open",
            "target_device_id": "local",
            "args": {"app_key": "calculator"},
        },
        AuthorizationDecision(False, "T2"),
    )
    assert result.status == "denied"
    assert runtime.launched == []


async def test_remote_target_never_reaches_os():
    runtime = FakeRuntime(True)
    result = await WindowsActionExecutor(runtime=runtime).execute(
        {
            "capability_id": "windows.app.open",
            "target_device_id": "other",
            "args": {"app_key": "calculator"},
        },
        AuthorizationDecision(True, "T1"),
    )
    assert result.status == "denied"
    assert runtime.launched == []
