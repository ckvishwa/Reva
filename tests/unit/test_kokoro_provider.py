"""AR-VA-004 / AR-VA-008 / AR-VA-020: Kokoro provider behavior against a fake worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

from reva_core.models.tts import SpeechChunk
from reva_core.providers.asset_manifest import AssetRefusal, AssetVerificationError
from reva_core.providers.registry import ProviderKind, ProviderRegistry, ProviderSpec
from reva_core.shared.errors import ProviderError, ProviderErrorKind, ValidationError
from reva_core.voice.kokoro_provider import KokoroAssetIds, KokoroSpeechProvider
from tests.fixtures.process_utils import pid_alive, wait_until_dead

_IDS = KokoroAssetIds(config="kokoro.config", model="kokoro.model", voice="kokoro.voice.af_heart")


def _write_assets(root: Path, *, tamper: str | None = None) -> Path:
    files = {
        "kokoro.config": ("config.json", b'{"vocab": {}}'),
        "kokoro.model": ("kokoro-v1_0.pth", b"model-weights"),
        "kokoro.voice.af_heart": ("af_heart.pt", b"voice-tensor"),
    }
    entries = []
    for asset_id, (name, data) in files.items():
        (root / name).write_bytes(b"TAMPERED" if asset_id == tamper else data)
        entries.append(
            {
                "id": asset_id,
                "kind": "tts_model",
                "path": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "source": "test",
                "license": "apache-2.0",
                "provenance_status": "licensed",
            }
        )
    manifest = root / "assets.manifest.json"
    manifest.write_text(
        json.dumps({"manifest_version": "1.0", "asset_root": str(root), "assets": entries}),
        encoding="utf-8",
    )
    return manifest


def _provider(tmp_path: Path, *, tamper: str | None = None, **overrides) -> KokoroSpeechProvider:
    root = tmp_path / "assets"
    root.mkdir(exist_ok=True)
    manifest = _write_assets(root, tamper=tamper)
    options = {
        "python_exe": Path(sys.executable),
        "manifest_path": manifest,
        "asset_root": root,
        "asset_ids": _IDS,
        "output_dir": tmp_path / "speech",
        "worker_module": "tests.fixtures.fake_kokoro_worker",
        "ready_timeout_seconds": 10.0,
        "chunk_timeout_seconds": 5.0,
        "stop_ack_timeout_seconds": 0.5,
    }
    options.update(overrides)
    return KokoroSpeechProvider(**options)


async def _collect(provider: KokoroSpeechProvider, text: str, epoch: int) -> list[SpeechChunk]:
    return [chunk async for chunk in provider.speak(text, language="en", turn_epoch=epoch)]


async def test_health_reports_ready_with_worker_pid(tmp_path):
    provider = _provider(tmp_path)
    try:
        health = await provider.health()
        assert health.ok is True
        assert health.voice == "af_heart"
        assert health.pid is not None and pid_alive(health.pid)
    finally:
        await provider.shutdown()


async def test_tampered_model_is_refused_before_any_worker_starts(tmp_path):
    provider = _provider(tmp_path, tamper="kokoro.model")
    try:
        with pytest.raises(AssetVerificationError) as excinfo:
            await provider.health()
        assert excinfo.value.reason == AssetRefusal.HASH_MISMATCH
        assert provider.worker_pid is None
    finally:
        await provider.shutdown()


async def test_registry_falls_back_when_kokoro_refuses(tmp_path):
    kokoro = _provider(tmp_path, tamper="kokoro.voice.af_heart")

    class _Fallback:
        async def health(self) -> bool:
            return True

    registry = ProviderRegistry()
    registry.register(
        ProviderSpec(ProviderKind.TTS, "kokoro", lambda: kokoro, frozenset({"speak"}), default=True)
    )
    registry.register(ProviderSpec(ProviderKind.TTS, "fallback", _Fallback, frozenset({"speak"})))

    selection = await registry.acquire(ProviderKind.TTS)

    assert selection.name == "fallback"
    assert "hash_mismatch" in selection.skipped[0][1]


async def test_speak_yields_ordered_chunks_tagged_with_the_turn_epoch(tmp_path):
    provider = _provider(tmp_path)
    try:
        chunks = await _collect(provider, "Hello there.", epoch=1)
    finally:
        await provider.shutdown()

    assert [c.index for c in chunks] == [0, 1, 2]
    assert [c.final for c in chunks] == [False, False, True]
    assert {c.turn_epoch for c in chunks} == {1}
    assert all(c.sample_rate == 24_000 and c.duration_ms == 100 for c in chunks)
    assert all(c.path.is_file() for c in chunks)


async def test_stop_mid_stream_ends_audio_within_300ms_and_delivers_nothing_after(tmp_path):
    provider = _provider(tmp_path)
    received: list[SpeechChunk] = []
    stop_returned_at = 0.0
    stop_called_at = 0.0
    try:
        async for chunk in provider.speak("slow", language="en", turn_epoch=1):
            received.append(chunk)
            if len(received) == 2:
                stop_called_at = time.monotonic()
                await provider.stop(turn_epoch=2)
                stop_returned_at = time.monotonic()
    finally:
        await provider.shutdown()

    assert len(received) == 2, "no chunk may be delivered after stop() was called"
    assert stop_returned_at - stop_called_at <= 0.3


async def test_new_epoch_interrupts_old_stream_without_overlap(tmp_path):
    provider = _provider(tmp_path)
    delivered: list[tuple[int, int]] = []

    async def play(text: str, epoch: int) -> None:
        async for chunk in provider.speak(text, language="en", turn_epoch=epoch):
            delivered.append((chunk.turn_epoch, chunk.index))
            await asyncio.sleep(0)

    try:
        first = asyncio.create_task(play("slow", 1))
        while not delivered:
            await asyncio.sleep(0.01)
        await play("Second.", 2)
        await first
    finally:
        await provider.shutdown()

    epochs = [epoch for epoch, _ in delivered]
    first_new = epochs.index(2)
    assert 1 not in epochs[first_new:], "an old-epoch chunk arrived after the new epoch began"
    assert [i for e, i in delivered if e == 2] == [0, 1, 2]
    assert not (tmp_path / "speech" / "overlap-detected").exists()


async def test_stale_epoch_speak_produces_no_audio(tmp_path):
    provider = _provider(tmp_path)
    try:
        await provider.stop(turn_epoch=5)
        chunks = await _collect(provider, "Too late.", epoch=4)
    finally:
        await provider.shutdown()

    assert chunks == []


async def test_worker_that_ignores_stop_is_killed_and_restarts_on_next_speak(tmp_path):
    provider = _provider(tmp_path, stop_ack_timeout_seconds=0.3)
    try:
        stream = provider.speak("hang", language="en", turn_epoch=1)
        await anext(stream)
        hung_pid = provider.worker_pid
        assert hung_pid is not None

        await provider.stop(turn_epoch=2)

        assert wait_until_dead(hung_pid, 3.0)
        chunks = await _collect(provider, "Back again.", epoch=2)
        assert [c.index for c in chunks] == [0, 1, 2]
        assert provider.worker_pid != hung_pid
    finally:
        await provider.shutdown()


async def test_worker_crash_mid_speak_is_unavailable_then_recovers(tmp_path):
    provider = _provider(tmp_path)
    try:
        with pytest.raises(ProviderError) as excinfo:
            await _collect(provider, "crash", epoch=1)
        assert excinfo.value.kind == ProviderErrorKind.UNAVAILABLE

        chunks = await _collect(provider, "Recovered.", epoch=2)
        assert len(chunks) == 3
    finally:
        await provider.shutdown()


async def test_shutdown_leaves_no_worker_process(tmp_path):
    provider = _provider(tmp_path)
    await provider.health()
    pid = provider.worker_pid
    assert pid is not None

    await provider.shutdown()

    assert wait_until_dead(pid, 3.0)
    assert provider.worker_pid is None


async def test_unsupported_language_and_bad_text_are_rejected(tmp_path):
    provider = _provider(tmp_path)
    try:
        with pytest.raises(ValidationError):
            await _collect_lang(provider, "namaste", "te")
        with pytest.raises(ValidationError):
            await _collect(provider, "   ", epoch=1)
        with pytest.raises(ValidationError):
            await _collect(provider, "x" * 801, epoch=1)
    finally:
        await provider.shutdown()


async def _collect_lang(provider: KokoroSpeechProvider, text: str, language: str) -> list:
    return [c async for c in provider.speak(text, language=language, turn_epoch=1)]


async def test_synthesize_joins_chunks_for_the_legacy_speech_route(tmp_path):
    provider = _provider(tmp_path)
    try:
        audio = await provider.synthesize("Hello there.", "en")
    finally:
        await provider.shutdown()

    assert audio.path.is_file()
    assert audio.sample_rate == 24_000
    assert audio.duration_ms == 300
    assert audio.language == "en"
    assert audio.provider == "kokoro_af_heart"


async def test_discarded_chunk_files_are_deleted(tmp_path):
    provider = _provider(tmp_path)
    try:
        async for _ in provider.speak("slow", language="en", turn_epoch=1):
            await provider.stop(turn_epoch=2)
            break
        await asyncio.sleep(0.2)
    finally:
        await provider.shutdown()

    leftovers = [p for p in (tmp_path / "speech").glob("chunk-*.wav")]
    # Only the chunk the consumer actually received may remain; stale ones are removed.
    assert len(leftovers) <= 1
