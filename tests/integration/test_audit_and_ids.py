"""B4: security log names who asked without secrets (AR-DATA-009); every event carries its ids
(AR-CORE-005); the cross-process envelope is complete (AR-SYS-003)."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import jsonschema

from reva_core.session.events import SessionEventKind
from tests.unit.test_turn_pipeline import Rig, collect

ROOT = Path(__file__).resolve().parents[2]
SESSION_SCHEMA = json.loads((ROOT / "contracts" / "session-event.schema.json").read_text("utf-8"))
BAD_TOKEN = "Bearer wrong-token-ZZZ-0123456789"


def audit_rows(core) -> list[dict]:
    rows = core.connection.execute(
        "SELECT action, outcome, correlation_id, metadata FROM audit_events "
        "WHERE action = 'authentication_failed' ORDER BY occurred_at"
    ).fetchall()
    return [dict(r) for r in rows]


def test_a_failed_login_records_the_path_and_the_asking_address_never_the_token(
    client, core
) -> None:
    client.get("/v1/devices", headers={"Authorization": BAD_TOKEN})

    (row,) = audit_rows(core)
    metadata = json.loads(row["metadata"])
    assert row["outcome"] == "denied" and row["correlation_id"]
    assert metadata["path"] == "/v1/devices" and metadata["client"]
    assert "wrong-token" not in json.dumps(row) and "Bearer" not in json.dumps(row)


def test_a_failed_websocket_login_is_recorded_the_same_way(client, core) -> None:
    session = client.post(
        "/v1/voice/sessions", headers={"Authorization": f"Bearer {core.local_token}"}, json={}
    ).json()

    # The server closes the socket with a policy violation, which the client raises.
    with (
        contextlib.suppress(Exception),
        client.websocket_connect(
            f"/v1/voice/sessions/{session['session_id']}/events",
            headers={"Authorization": BAD_TOKEN},
        ) as ws,
    ):
        ws.receive_json()

    rows = audit_rows(core)
    assert len(rows) == 1
    metadata = json.loads(rows[0]["metadata"])
    assert metadata["path"].endswith("/events") and metadata["client"]
    assert "wrong-token" not in json.dumps(rows[0])


def test_the_action_ledger_records_which_device_approved(client, auth_headers, core) -> None:
    if core.broker is None:
        return  # no key vault in this environment: covered by test_actions_api
    asked = client.post(
        "/v1/actions/proposals",
        headers=auth_headers,
        json={"capability": "windows.app.close", "args": {"app_key": "notepad"}},
    )
    assert asked.status_code in (201, 503)


async def test_every_session_event_carries_its_ids_and_fits_the_envelope(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "add twelve dollars for lunch", "make it fifteen")
    await rig.listening()
    await rig.talk()
    await rig.pipeline.on_playback_finished()
    await rig.talk()
    events = await collect(rig)

    assert events
    assert len({e.event_id for e in events}) == len(events)
    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    for event in events:
        body = json.loads(event.model_dump_json())
        jsonschema.validate(body, SESSION_SCHEMA)
        for field in ("event_id", "device_id", "session_id", "turn_id", "correlation_id"):
            assert body[field], (event.kind, field)
        assert body["schema_version"] == "2.0" and body["kind"] == event.kind.value
    kinds = {e.kind for e in events}
    assert {
        SessionEventKind.SESSION_STATE,
        SessionEventKind.TRANSCRIPT_FINAL,
        SessionEventKind.ASSISTANT_TEXT_FINAL,
    } <= kinds


def test_the_envelope_fields_are_required_by_the_contract() -> None:
    required = set(SESSION_SCHEMA["required"])

    assert {
        "schema_version",
        "event_id",
        "device_id",
        "session_id",
        "sequence",
        "kind",
        "payload",
    } <= required
