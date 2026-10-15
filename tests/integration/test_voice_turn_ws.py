"""B1: a whole voice turn over the WebSocket, with fake STT and TTS (no model, no microphone)."""

from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.models.stt import TranscriptionInput, TranscriptionResult
from reva_core.models.tts import SynthesizedAudio
from reva_core.orchestration.lifecycle import CoreLifecycle


class FakeSTT:
    def __init__(self) -> None:
        self.texts = ["add twelve dollars for lunch", "make it fifteen"]

    async def transcribe(self, audio: TranscriptionInput) -> TranscriptionResult:
        return TranscriptionResult(
            text=self.texts.pop(0), language="en", duration_ms=900, provider="fake-stt"
        )


class FakeTTS:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.count = 0

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio:
        self.count += 1
        path = self.directory / f"reply-{self.count}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(b"\x01\x00" * 2400)
        return SynthesizedAudio(
            path=path, sample_rate=24000, duration_ms=100, provider="fake-tts", language="en"
        )


def _tone(ms: int) -> bytes:
    return array(
        "h", (int(9000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(16 * ms))
    ).tobytes()


@pytest.fixture
def rig(tmp_path):
    out = tmp_path / "tts"
    out.mkdir()
    settings = load_settings(_env_file=None, data_dir=tmp_path / "data")
    core = CoreLifecycle(
        settings, text_to_speech_provider=FakeTTS(out), speech_to_text_provider=FakeSTT()
    )
    core.startup()
    client = TestClient(create_app(core))
    headers = {"Authorization": f"Bearer {core.local_token}"}
    yield client, headers, core, tmp_path
    core.shutdown()


def _until(ws, kind: str, limit: int = 40) -> dict:
    for _ in range(limit):
        event = ws.receive_json()
        if event["kind"] == kind:
            return event
    raise AssertionError(f"no {kind} event")


def _talk(ws) -> dict:
    ws.send_json({"type": "ptt.down"})
    ws.send_bytes(_tone(600))
    ws.send_json({"type": "ptt.up"})
    return _until(ws, "tts.started")


def test_a_turn_over_the_socket_ends_in_a_fetchable_reply(rig) -> None:
    client, headers, core, tmp = rig
    session = client.post("/v1/voice/sessions", headers=headers, json={}).json()
    url = f"/v1/voice/sessions/{session['session_id']}/events"

    with client.websocket_connect(url, headers=headers) as ws:
        ws.send_json({"type": "capture.requested"})
        ws.send_json({"type": "capture.open"})
        _until(ws, "session.state")
        started = _talk(ws)
        reply = client.get(started["payload"]["audio_path"], headers=headers)
        anonymous = client.get(started["payload"]["audio_path"])

        assert reply.status_code == 200 and reply.headers["content-type"] == "audio/wav"
        assert anonymous.status_code == 401
        ws.send_json({"type": "playback.finished", "turn_epoch": started["turn_epoch"]})
        listening = _until(ws, "tts.stopped")
        assert listening["payload"]["reason"] == "completed"

    rows = core.settings.data_dir.joinpath("turns").glob("turns-*.jsonl")
    assert any("add twelve dollars for lunch" in f.read_text(encoding="utf-8") for f in rows)


def test_make_it_fifteen_changes_the_draft_across_two_turns(rig) -> None:
    client, headers, _, _ = rig
    session = client.post("/v1/voice/sessions", headers=headers, json={}).json()
    url = f"/v1/voice/sessions/{session['session_id']}/events"

    with client.websocket_connect(url, headers=headers) as ws:
        ws.send_json({"type": "capture.requested"})
        ws.send_json({"type": "capture.open"})
        first = _talk(ws)
        ws.send_json({"type": "playback.finished", "turn_epoch": first["turn_epoch"]})
        _until(ws, "tts.stopped")
        ws.send_json({"type": "ptt.down"})
        ws.send_bytes(_tone(600))
        ws.send_json({"type": "ptt.up"})
        text = _until(ws, "assistant.text.final")

    assert text["payload"]["text"] == "Changed to $15.00 for lunch. Say yes to confirm."


def test_audio_for_an_unknown_session_or_audio_id_is_404(rig) -> None:
    client, headers, _, _ = rig
    session = client.post("/v1/voice/sessions", headers=headers, json={}).json()

    assert client.get("/v1/voice/sessions/nope/audio/x", headers=headers).status_code == 404
    assert (
        client.get(
            f"/v1/voice/sessions/{session['session_id']}/audio/x", headers=headers
        ).status_code
        == 404
    )


def test_closing_the_session_deletes_waiting_reply_audio(rig) -> None:
    client, headers, _, tmp = rig
    session = client.post("/v1/voice/sessions", headers=headers, json={}).json()
    url = f"/v1/voice/sessions/{session['session_id']}/events"
    with client.websocket_connect(url, headers=headers) as ws:
        ws.send_json({"type": "capture.requested"})
        ws.send_json({"type": "capture.open"})
        _talk(ws)
    assert (
        client.delete(f"/v1/voice/sessions/{session['session_id']}", headers=headers).status_code
        == 204
    )

    assert not list((tmp / "tts").glob("reply-*.wav"))


def test_binary_frames_before_the_pipeline_exists_cannot_crash_the_socket(rig) -> None:
    client, headers, _, _ = rig
    session = client.post("/v1/voice/sessions", headers=headers, json={}).json()
    url = f"/v1/voice/sessions/{session['session_id']}/events"

    with client.websocket_connect(url, headers=headers) as ws:
        ws.send_bytes(b"\x00\x01")  # not listening yet: ignored
        ws.send_json({"type": "ping"})
        ws.send_json({"type": "mic.mute"})
        ws.send_json({"type": "mic.unmute"})
        ws.send_json({"type": "nonsense"})
        error = _until(ws, "error")

    assert error["payload"]["code"] == "BAD_CONTROL_MESSAGE"
