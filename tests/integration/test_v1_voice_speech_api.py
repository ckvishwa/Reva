from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.models.tts import SynthesizedAudio, TextToSpeechProvider
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.storage.repositories.audit_repository import AuditRepository


class FakeSpeechProvider(TextToSpeechProvider):
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.last_path: Path | None = None
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio:
        self.calls.append((text, language))
        path = self.output_dir / "speech.wav"
        _write_wav(path)
        self.last_path = path
        return SynthesizedAudio(
            path=path,
            sample_rate=24_000,
            duration_ms=100,
            language=language,
            provider="fake-tts",
        )


class FailingSpeechProvider(TextToSpeechProvider):
    def __init__(self, kind: ProviderErrorKind) -> None:
        self.kind = kind

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio:
        raise ProviderError(self.kind, "fake failure")


def _write_wav(path: Path) -> None:
    sample_rate = 24_000
    frames = sample_rate // 10
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(frames):
            sample = int(1000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wav.writeframesraw(struct.pack("<h", sample))


@pytest.fixture
def voice_core(tmp_path):
    provider = FakeSpeechProvider(tmp_path / "speech-output")
    settings = load_settings(_env_file=None, data_dir=tmp_path / "data")
    lifecycle = CoreLifecycle(settings, text_to_speech_provider=provider)
    lifecycle.startup()
    try:
        yield lifecycle, provider
    finally:
        lifecycle.shutdown()


@pytest.fixture
def voice_client(voice_core):
    lifecycle, _ = voice_core
    return TestClient(create_app(lifecycle))


@pytest.fixture
def voice_auth_headers(voice_core):
    lifecycle, _ = voice_core
    return {"Authorization": f"Bearer {lifecycle.local_token}"}


def test_voice_speech_streams_wav_and_deletes_temp_file(
    voice_core, voice_client, voice_auth_headers
):
    _, provider = voice_core

    response = voice_client.post(
        "/v1/voice/speech",
        json={"text": "Good morning.", "language": "en"},
        headers=voice_auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert provider.calls == [("Good morning.", "en")]
    assert provider.last_path is not None
    assert not provider.last_path.exists()


def test_voice_speech_supports_telugu_language(voice_core, voice_client, voice_auth_headers):
    _, provider = voice_core

    response = voice_client.post(
        "/v1/voice/speech",
        json={"text": "శుభోదయం.", "language": "te"},
        headers=voice_auth_headers,
    )

    assert response.status_code == 200
    assert provider.calls == [("శుభోదయం.", "te")]


def test_voice_speech_rejects_invalid_language(voice_client, voice_auth_headers):
    response = voice_client.post(
        "/v1/voice/speech",
        json={"text": "Bonjour.", "language": "fr"},
        headers=voice_auth_headers,
    )

    assert response.status_code == 422


def test_voice_speech_rejects_oversized_text(voice_client, voice_auth_headers):
    response = voice_client.post(
        "/v1/voice/speech",
        json={"text": "x" * 801, "language": "en"},
        headers=voice_auth_headers,
    )

    assert response.status_code == 422


def test_voice_unavailable_does_not_break_typed_chat(tmp_path):
    settings = load_settings(
        _env_file=None, data_dir=tmp_path, assistant_orchestrator="deterministic"
    )
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    try:
        client = TestClient(create_app(lifecycle))
        headers = {"Authorization": f"Bearer {lifecycle.local_token}"}

        voice_response = client.post(
            "/v1/voice/speech",
            json={"text": "Good morning.", "language": "en"},
            headers=headers,
        )
        message_response = client.post("/v1/messages", json={"content": "hi"}, headers=headers)

        assert voice_response.status_code == 503
        assert message_response.status_code == 200
        assert message_response.json()["reply"] == "Received: hi"
    finally:
        lifecycle.shutdown()


@pytest.mark.parametrize(
    ("kind", "expected_status"),
    [
        (ProviderErrorKind.UNAVAILABLE, 503),
        (ProviderErrorKind.TIMEOUT, 504),
        (ProviderErrorKind.INVALID_RESPONSE, 502),
    ],
)
def test_voice_speech_maps_provider_failures(tmp_path, kind, expected_status):
    settings = load_settings(_env_file=None, data_dir=tmp_path / "data")
    lifecycle = CoreLifecycle(settings, text_to_speech_provider=FailingSpeechProvider(kind))
    lifecycle.startup()
    try:
        client = TestClient(create_app(lifecycle))
        headers = {"Authorization": f"Bearer {lifecycle.local_token}"}
        response = client.post(
            "/v1/voice/speech",
            json={"text": "Good morning.", "language": "en"},
            headers=headers,
        )
    finally:
        lifecycle.shutdown()

    assert response.status_code == expected_status


def test_voice_speech_audit_metadata_excludes_full_text(
    voice_core, voice_client, voice_auth_headers
):
    lifecycle, _ = voice_core
    spoken_text = "Do not persist this full sentence in audit metadata."

    response = voice_client.post(
        "/v1/voice/speech",
        json={"text": spoken_text, "language": "en"},
        headers=voice_auth_headers,
    )

    assert response.status_code == 200
    events = AuditRepository(lifecycle.connection).list_recent(20)
    voice_events = [event for event in events if event.action.startswith("voice_speech_")]
    assert {event.action for event in voice_events} >= {
        "voice_speech_requested",
        "voice_speech_completed",
    }
    serialized_metadata = " ".join(str(event.metadata) for event in voice_events)
    assert spoken_text not in serialized_metadata
    assert "text_length" in serialized_metadata
