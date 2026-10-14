"""VOICE-1 security review: gaps found beyond tests/integration/test_voice_sessions_api.py."""

from __future__ import annotations

import logging

import pytest
from starlette.websockets import WebSocketDisconnect


def _open(client, auth_headers) -> dict:
    response = client.post("/v1/voice/sessions", headers=auth_headers, json={})
    assert response.status_code == 201, response.text
    return response.json()


def _events_url(session: dict) -> str:
    return f"/v1/voice/sessions/{session['session_id']}/events"


def test_an_oversized_control_message_is_refused_without_being_parsed(client, auth_headers):
    session = _open(client, auth_headers)

    with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
        ws.receive_json()
        ws.send_text('{"type": "ping", "pad": "' + "x" * 1_000_000 + '"}')
        error = ws.receive_json()
        # The session is still alive and answers an ordinary control message afterwards.
        ws.send_json({"type": "capture.requested"})
        follow = ws.receive_json()

    assert error["payload"]["code"] == "BAD_CONTROL_MESSAGE"
    assert follow["payload"].get("code") != "BAD_CONTROL_MESSAGE"


@pytest.mark.parametrize("header", ["Bearer café-token", "Bearer ÿþ"])
def test_a_non_ascii_bearer_is_a_clean_refusal_not_a_server_error(client, auth_headers, header):
    session = _open(client, auth_headers)

    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect(
            _events_url(session), headers={"Authorization": header.encode("latin-1")}
        ),
    ):
        pass

    assert excinfo.value.code == 1008


def test_the_token_never_reaches_the_logs_or_the_event_stream(client, auth_headers, core, caplog):
    token = core.local_token
    session = _open(client, auth_headers)
    with caplog.at_level(logging.DEBUG):
        with client.websocket_connect(_events_url(session), headers=auth_headers) as ws:
            first = ws.receive_json()
            ws.send_text("{broken")
            error = ws.receive_json()
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                _events_url(session), headers={"Authorization": "Bearer wrong-" + token[:6]}
            ),
        ):
            pass

    assert token not in caplog.text
    assert token not in str(first) + str(error)
    assert "wrong-" + token[:6] not in caplog.text


def test_a_closed_session_cannot_be_attached_to(client, auth_headers):
    session = _open(client, auth_headers)
    assert (
        client.delete(f"/v1/voice/sessions/{session['session_id']}", headers=auth_headers)
    ).status_code == 204

    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect(_events_url(session), headers=auth_headers),
    ):
        pass

    assert excinfo.value.code == 1008


def test_a_second_delete_is_a_404_not_a_crash(client, auth_headers):
    session = _open(client, auth_headers)
    url = f"/v1/voice/sessions/{session['session_id']}"
    assert client.delete(url, headers=auth_headers).status_code == 204
    assert client.delete(url, headers=auth_headers).status_code == 404
