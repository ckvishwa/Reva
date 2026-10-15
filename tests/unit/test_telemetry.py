"""B4: telemetry is off by default, local, redacted and removable (AR-CORE-013)."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reva_core.telemetry import ALLOWED_EVENTS, DIRECTORY, MAX_FILE_BYTES, Telemetry

ROOT = Path(__file__).resolve().parents[2]


def make(tmp_path: Path, day: int = 15) -> Telemetry:
    return Telemetry(tmp_path, clock=lambda: datetime(2026, 10, day, 13, 45, 12, tzinfo=UTC))


def test_it_is_off_by_default_and_records_nothing(tmp_path: Path) -> None:
    telemetry = make(tmp_path)

    assert telemetry.enabled is False
    assert telemetry.record("core.start", ok=True) is False
    assert not (tmp_path / DIRECTORY).exists() and telemetry.read() == []


def test_switched_on_it_records_a_day_not_a_time_and_only_allowed_fields(tmp_path: Path) -> None:
    telemetry = make(tmp_path)
    telemetry.set_enabled(True)

    wrote = telemetry.record(
        "voice.turn",
        ok=True,
        duration_ms=412,
        transcript="add twelve dollars for lunch",
        amount=12.5,
        device_id="device-0001",
        path=r"C:\Users\someone\secret.txt",
        status="verified",
        code="CORE.INTERNAL",
    )

    row = telemetry.read()[0]
    assert wrote is True
    assert row == {
        "event": "voice.turn",
        "day": "2026-10-15",
        "ok": True,
        "duration_ms": 412,
        "status": "verified",
        "code": "CORE.INTERNAL",
    }
    text = (tmp_path / DIRECTORY / "events-20261015.jsonl").read_text(encoding="utf-8")
    for private in ("lunch", "12.5", "device-0001", "secret", "13:45"):
        assert private not in text


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("ok", "yes"),
        ("duration_ms", -1),
        ("duration_ms", 10**9),
        ("duration_ms", True),
        ("duration_ms", 1.5),
        ("code", "free text with spaces"),
        ("code", "internal_error"),
        ("status", "it worked great"),
        ("count", -3),
    ],
)
def test_a_value_that_is_not_the_right_kind_is_dropped_not_stored(
    tmp_path: Path, field: str, bad: object
) -> None:
    telemetry = make(tmp_path)
    telemetry.set_enabled(True)

    telemetry.record("voice.turn", **{field: bad})

    assert telemetry.read() == [{"event": "voice.turn", "day": "2026-10-15"}]


def test_an_event_name_outside_the_list_is_refused(tmp_path: Path) -> None:
    telemetry = make(tmp_path)
    telemetry.set_enabled(True)

    assert telemetry.record("user.said.something", ok=True) is False
    assert telemetry.read() == []
    assert "core.start" in ALLOWED_EVENTS


def test_removing_deletes_every_file_and_switches_it_off(tmp_path: Path) -> None:
    telemetry = make(tmp_path)
    telemetry.set_enabled(True)
    telemetry.record("core.start", ok=True)
    telemetry_b = make(tmp_path, day=16)
    telemetry_b.record("core.stop", ok=True)

    removed = telemetry.remove_all()

    assert removed == 2 and telemetry.read() == []
    assert not (tmp_path / DIRECTORY).exists()
    assert telemetry.enabled is False
    assert telemetry.record("core.start", ok=True) is False


def test_a_day_file_has_a_size_cap_and_old_files_are_pruned(tmp_path: Path) -> None:
    telemetry = make(tmp_path)
    telemetry.set_enabled(True)
    path = tmp_path / DIRECTORY / "events-20261015.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * MAX_FILE_BYTES)

    assert telemetry.record("core.start", ok=True) is False

    for day in range(1, 29):
        make(tmp_path, day=day).record("core.start", ok=True)
    assert len(list((tmp_path / DIRECTORY).glob("events-*.jsonl"))) <= 14


def test_a_damaged_switch_file_means_off(tmp_path: Path) -> None:
    (tmp_path / "telemetry.json").write_text("{ nope", encoding="utf-8")

    assert make(tmp_path).enabled is False
    (tmp_path / "telemetry.json").write_text(json.dumps({"enabled": "true"}), encoding="utf-8")
    assert make(tmp_path).enabled is False  # only a real true counts


def test_the_telemetry_module_has_no_network_code() -> None:
    tree = ast.parse((ROOT / "reva_core" / "telemetry" / "__init__.py").read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not imported & {
        "socket", "http", "urllib", "httpx", "requests", "aiohttp", "ssl", "smtplib", "ftplib",
        "websockets", "subprocess", "asyncio",
    }  # fmt: skip


# ------------------------------------------------------------------ the API


def test_the_api_switch_off_by_default_and_removable(client, auth_headers, core) -> None:
    url = "/v1/settings/telemetry"

    assert client.get(url).status_code == 401
    first = client.get(url, headers=auth_headers).json()
    on = client.put(url, headers=auth_headers, json={"enabled": True}).json()
    core.telemetry.record("core.stop", ok=True)
    stored = client.get(url, headers=auth_headers).json()
    gone = client.delete(url, headers=auth_headers).json()

    assert first["enabled"] is False and first["leaves_this_pc"] is False
    assert on["enabled"] is True
    assert stored["events_stored"] >= 1
    assert gone["enabled"] is False and gone["events_stored"] == 0


def test_a_server_error_is_counted_by_code_only(core, auth_headers, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from reva_core.api.app import create_app

    client = TestClient(create_app(core), raise_server_exceptions=False)
    client.put("/v1/settings/telemetry", headers=auth_headers, json={"enabled": True})

    def boom(*_a, **_k):
        raise RuntimeError("secret detail that must not be stored")

    monkeypatch.setattr(type(core), "health", boom)
    response = client.get("/health")

    assert response.status_code == 500
    text = json.dumps(core.telemetry.read())
    assert "secret detail" not in text and '"code":"CORE.INTERNAL"' in text.replace(" ", "")


def test_a_bad_body_is_refused(client, auth_headers) -> None:
    assert (
        client.put(
            "/v1/settings/telemetry", headers=auth_headers, json={"enabled": "maybe"}
        ).status_code
        == 422
    )
