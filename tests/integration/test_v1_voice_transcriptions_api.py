from __future__ import annotations

import math
import struct
import wave
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.models.stt import SpeechToTextProvider, TranscriptionInput, TranscriptionResult
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.storage.repositories.audit_repository import AuditRepository


class FakeTranscriptionProvider(SpeechToTextProvider):
    def __init__(self, text: str = "Which project did I make for malware analysis?") -> None:
        self.text = text
        self.calls: list[TranscriptionInput] = []
        self.seen_existing_path = False

    async def transcribe(self, audio: TranscriptionInput) -> TranscriptionResult:
        self.calls.append(audio)
        self.seen_existing_path = audio.path.exists()
        return TranscriptionResult(
            text=self.text,
            language="en",
            duration_ms=3100,
            provider="fake-stt",
        )


class FailingTranscriptionProvider(SpeechToTextProvider):
    def __init__(self, kind: ProviderErrorKind) -> None:
        self.kind = kind

    async def transcribe(self, audio: TranscriptionInput) -> TranscriptionResult:
        raise ProviderError(self.kind, "fake STT failure")


def _wav_bytes(*, duration_seconds: float = 0.1, sample_rate: int = 16_000) -> bytes:
    stream = BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(int(duration_seconds * sample_rate)):
            sample = int(1000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wav.writeframesraw(struct.pack("<h", sample))
    return stream.getvalue()


@pytest.fixture
def transcription_core(tmp_path):
    provider = FakeTranscriptionProvider()
    settings = load_settings(_env_file=None, data_dir=tmp_path / "data")
    lifecycle = CoreLifecycle(settings, speech_to_text_provider=provider)
    lifecycle.startup()
    try:
        yield lifecycle, provider
    finally:
        lifecycle.shutdown()


@pytest.fixture
def transcription_client(transcription_core):
    lifecycle, _ = transcription_core
    return TestClient(create_app(lifecycle))


@pytest.fixture
def transcription_auth_headers(transcription_core):
    lifecycle, _ = transcription_core
    return {"Authorization": f"Bearer {lifecycle.local_token}"}


def test_voice_transcription_returns_text_and_deletes_uploaded_audio(
    transcription_core, transcription_client, transcription_auth_headers
):
    _, provider = transcription_core

    response = transcription_client.post(
        "/v1/voice/transcriptions",
        content=_wav_bytes(),
        headers={**transcription_auth_headers, "Content-Type": "audio/wav"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 1,
        "text": "Which project did I make for malware analysis?",
        "language": "en",
        "duration_ms": 3100,
    }
    assert provider.seen_existing_path
    assert len(provider.calls) == 1
    assert provider.calls[0].media_type == "audio/wav"
    assert not provider.calls[0].path.exists()
    assert provider.calls[0].path.name == "input.wav"


def test_voice_transcription_rejects_empty_audio(transcription_client, transcription_auth_headers):
    response = transcription_client.post(
        "/v1/voice/transcriptions",
        content=b"",
        headers={**transcription_auth_headers, "Content-Type": "audio/wav"},
    )

    assert response.status_code == 400


def test_voice_transcription_rejects_unsupported_media_type(
    transcription_client, transcription_auth_headers
):
    response = transcription_client.post(
        "/v1/voice/transcriptions",
        content=_wav_bytes(),
        headers={**transcription_auth_headers, "Content-Type": "audio/mpeg"},
    )

    assert response.status_code == 415


def test_voice_transcription_rejects_oversized_audio(tmp_path):
    provider = FakeTranscriptionProvider()
    settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        stt_max_upload_bytes=4,
    )
    lifecycle = CoreLifecycle(settings, speech_to_text_provider=provider)
    lifecycle.startup()
    try:
        client = TestClient(create_app(lifecycle))
        headers = {"Authorization": f"Bearer {lifecycle.local_token}", "Content-Type": "audio/wav"}

        response = client.post("/v1/voice/transcriptions", content=_wav_bytes(), headers=headers)
    finally:
        lifecycle.shutdown()

    assert response.status_code == 413
    assert provider.calls == []


def test_voice_transcription_rejects_invalid_wav(transcription_client, transcription_auth_headers):
    response = transcription_client.post(
        "/v1/voice/transcriptions",
        content=b"not a wav",
        headers={**transcription_auth_headers, "Content-Type": "audio/wav"},
    )

    assert response.status_code == 400


def test_voice_transcription_rejects_overlong_duration(tmp_path):
    provider = FakeTranscriptionProvider()
    settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        stt_max_duration_seconds=0.05,
    )
    lifecycle = CoreLifecycle(settings, speech_to_text_provider=provider)
    lifecycle.startup()
    try:
        client = TestClient(create_app(lifecycle))
        headers = {"Authorization": f"Bearer {lifecycle.local_token}", "Content-Type": "audio/wav"}

        response = client.post("/v1/voice/transcriptions", content=_wav_bytes(), headers=headers)
    finally:
        lifecycle.shutdown()

    assert response.status_code == 400
    assert provider.calls == []


@pytest.mark.parametrize(
    ("kind", "expected_status"),
    [
        (ProviderErrorKind.UNAVAILABLE, 503),
        (ProviderErrorKind.TIMEOUT, 504),
        (ProviderErrorKind.INVALID_RESPONSE, 502),
    ],
)
def test_voice_transcription_maps_provider_failures(tmp_path, kind, expected_status):
    settings = load_settings(_env_file=None, data_dir=tmp_path / "data")
    lifecycle = CoreLifecycle(settings, speech_to_text_provider=FailingTranscriptionProvider(kind))
    lifecycle.startup()
    try:
        client = TestClient(create_app(lifecycle))
        headers = {"Authorization": f"Bearer {lifecycle.local_token}", "Content-Type": "audio/wav"}
        voice_response = client.post(
            "/v1/voice/transcriptions", content=_wav_bytes(), headers=headers
        )
        message_response = client.post(
            "/v1/messages",
            json={"content": "typed fallback"},
            headers={"Authorization": f"Bearer {lifecycle.local_token}"},
        )
    finally:
        lifecycle.shutdown()

    assert voice_response.status_code == expected_status
    assert message_response.status_code == 200


def test_voice_transcription_audit_metadata_excludes_transcript(
    transcription_core, transcription_client, transcription_auth_headers
):
    lifecycle, provider = transcription_core

    response = transcription_client.post(
        "/v1/voice/transcriptions",
        content=_wav_bytes(),
        headers={**transcription_auth_headers, "Content-Type": "audio/wav"},
    )

    assert response.status_code == 200
    events = AuditRepository(lifecycle.connection).list_recent(20)
    voice_events = [event for event in events if event.action.startswith("voice_transcription_")]
    assert {event.action for event in voice_events} >= {
        "voice_transcription_requested",
        "voice_transcription_completed",
    }
    serialized_metadata = " ".join(str(event.metadata) for event in voice_events)
    assert provider.text not in serialized_metadata
    assert "duration_ms" in serialized_metadata
