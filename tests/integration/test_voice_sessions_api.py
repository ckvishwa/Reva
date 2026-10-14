"""/v1/voice/sessions and its WebSocket event stream (ARD-300 §4)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import jsonschema
import pytest
from starlette.websockets import WebSocketDisconnect

from reva_core.api.voice_sessions import make_stop_speaking
from reva_core.session.coordinator import SessionCoordinator
from reva_core.session.state import SessionState

_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2] / "contracts" / "session-event.schema.json"
    ).read_text(encoding="utf-8")
)


def _open(client, auth_headers) -> dict:
    response = client.post("/v1/voice/sessions", headers=auth_headers, json={})
    assert response.status_code == 201, response.text
    return response.json()


def _events_url(session: dict) -> str:
    return f"/v1/voice/sessions/{session['session_id']}/events"


def test_open_session_requires_the_bearer_token(client):
    assert client.post("/v1/voice/sessions", json={}).status_code == 401


def test_open_session_returns_idle_state_and_deadlines(client, auth_headers):
    session = _open(client, auth_headers)

    assert session["state"] == "idle"
    assert session["turn_epoch"] == 0
    assert session["schema_version"] == "2.0"
    assert set(session["deadlines_ms"]) == {"stt", "model", "tool", "tts"}
    assert session["events_path"] == _events_url(session)


def test_open_session_rejects_unknown_fields(client, auth_headers):
    response = client.post(
        "/v1/voice/sessions", headers=auth_headers, json={"device_id": "device-0001", "x": 1}
    )

    assert response.status_code == 422


def test_session_count_is_bounded(client, auth_headers):
    statuses = [
        client.post("/v1/voice/sessions", headers=auth_headers, json={}).status_code
        for _ in range(6)
    ]

    assert statuses[:4] == [201, 201, 201, 201]
    assert statuses[4:] == [429, 429]


def test_delete_releases_the_session(client, auth_headers):
    session = _open(client, auth_headers)

    first = client.delete(f"/v1/voice/sessions/{session['session_id']}", headers=auth_headers)
    second = client.delete(f"/v1/voice/sessions/{session['session_id']}", headers=auth_headers)

    assert first.status_code == 204
    assert second.status_code == 404
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(_events_url(session), headers=auth_headers),
    ):
        pass


def test_delete_requires_the_bearer_token(client, auth_headers):
    session = _open(client, auth_headers)

    assert client.delete(f"/v1/voice/sessions/{session['session_id']}").status_code == 401


def test_websocket_without_a_token_is_refused_and_audited(client, auth_headers, core):
    session = _open(client, auth_headers)

    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect(_events_url(session)),
    ):
        pass

    assert excinfo.value.code == 1008
    actions = [e.action for e in _audit(core)]
    assert "authentication_failed" in actions


def test_websocket_with_a_wrong_token_is_refused(client, auth_headers):
    session = _open(client, auth_headers)

    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect(_events_url(session), headers={"Authorization": "Bearer wrong"}),
    ):
        pass

    assert excinfo.value.code == 1008


def test_websocket_never_accepts_the_token_in_the_query_string(client, auth_headers, core):
    session = _open(client, auth_headers)

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"{_events_url(session)}?token={core.local_token}"),
    ):
        pass


def test_websocket_unknown_session_is_refused(client, auth_headers):
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/v1/voice/sessions/does-not-exist-0001/events", headers=auth_headers
        ),
    ):
        pass


def test_websocket_replays_state_then_follows_capture_state(client, auth_headers):
    session = _open(client, auth_headers)

    with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
        first = ws.receive_json()
        ws.send_json({"type": "capture.requested"})
        acquiring = ws.receive_json()
        ws.send_json({"type": "capture.open"})
        listening = ws.receive_json()
        ws.send_json({"type": "capture.lost"})
        errored = ws.receive_json()
        idle_after = ws.receive_json()

    events = [first, acquiring, listening, errored, idle_after]
    for event in events:
        jsonschema.validate(event, _SCHEMA)
        assert event["session_id"] == session["session_id"]
    assert [e["sequence"] for e in events] == sorted({e["sequence"] for e in events})
    assert first["payload"]["state"] == "idle"
    assert acquiring["payload"]["state"] == "acquiring_permission"
    assert listening["payload"]["state"] == "listening"
    assert "error" in {e["kind"] for e in (errored, idle_after)}


def test_listening_is_not_reported_until_the_client_says_the_mic_is_open(client, auth_headers):
    session = _open(client, auth_headers)

    with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
        ws.receive_json()
        ws.send_json({"type": "capture.requested"})
        event = ws.receive_json()

    assert event["payload"]["state"] == "acquiring_permission"


def test_illegal_control_message_is_a_typed_error_and_changes_nothing(client, auth_headers):
    session = _open(client, auth_headers)

    with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
        ws.receive_json()
        ws.send_json({"type": "capture.open"})
        error = ws.receive_json()

    assert error["kind"] == "error"
    assert error["payload"]["code"] == "BAD_CONTROL_MESSAGE"
    assert error["payload"]["recoverable"] is True


@pytest.mark.parametrize("message", [{"type": "nope"}, {"no_type": 1}, {"type": 5}])
def test_unknown_control_messages_are_typed_errors(client, auth_headers, message):
    session = _open(client, auth_headers)

    with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
        ws.receive_json()
        ws.send_json(message)
        error = ws.receive_json()

    assert error["payload"]["code"] == "BAD_CONTROL_MESSAGE"


def test_malformed_json_is_a_typed_error_not_a_crash(client, auth_headers):
    session = _open(client, auth_headers)

    with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
        ws.receive_json()
        ws.send_text("{not json")
        error = ws.receive_json()

    assert error["payload"]["code"] == "BAD_CONTROL_MESSAGE"


def test_dropping_the_websocket_returns_the_session_to_safe_idle(client, auth_headers):
    session = _open(client, auth_headers)
    with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
        ws.receive_json()
        ws.send_json({"type": "capture.requested"})
        ws.receive_json()
        ws.send_json({"type": "capture.open"})
        ws.receive_json()

    live = client.app.state.voice_sessions.get(session["session_id"])
    deadline = time.monotonic() + 3.0
    while live.state != SessionState.IDLE and time.monotonic() < deadline:
        time.sleep(0.02)

    assert live.state == SessionState.IDLE
    assert live.turn_epoch >= 1, "the abandoned turn must be invalidated"


def test_websocket_routes_are_not_hidden_from_the_route_audit(client):
    from tests.conftest import iter_effective_routes

    websocket_paths = {
        route.path
        for route in iter_effective_routes(client.app)
        if route.__class__.__name__ == "APIWebSocketRoute"
    }

    assert websocket_paths == {"/v1/voice/sessions/{session_id}/events"}


async def test_stop_speaking_hook_stops_the_selected_tts_provider():
    stops: list[int] = []

    class _Tts:
        async def stop(self, *, turn_epoch: int) -> None:
            stops.append(turn_epoch)

    class _Lifecycle:
        text_to_speech_provider = _Tts()

    await make_stop_speaking(_Lifecycle())(7)

    assert stops == [7]


async def test_stop_speaking_hook_is_a_no_op_without_tts():
    class _Lifecycle:
        text_to_speech_provider = None

    await make_stop_speaking(_Lifecycle())(1)


def test_coordinator_is_exposed_for_diagnostics(client):
    assert isinstance(client.app.state.voice_sessions, SessionCoordinator)


def _audit(core):
    from reva_core.storage.repositories.audit_repository import AuditRepository

    return AuditRepository(core.connection).list_recent(50)
