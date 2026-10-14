"""S06 first-audio budget: the voice is loaded when Core starts, not on the first sentence.

Loading Kokoro takes about nine seconds. Core warms it in the background after it is up: startup
does not wait for it, a failure to warm is logged and never fatal, and the first real utterance
finds a worker that is already running.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.providers.tts import RegistryTTS, build_tts_registry
from tests.fixtures.kokoro_assets import write_assets
from tests.fixtures.process_utils import pid_alive, wait_until_dead


def _tts(tmp_path: Path, *, tamper: str | None = None) -> tuple[RegistryTTS, object]:
    root = tmp_path / "assets"
    write_assets(root, tamper=tamper)
    settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        tts_enabled=True,
        asset_root=root,
        kokoro_python=Path(sys.executable),
        kokoro_config_asset_id="kokoro.config",
        kokoro_model_asset_id="kokoro.model",
        kokoro_voice_asset_id="kokoro.voice.af_heart",
    )
    registry = build_tts_registry(
        settings, tmp_path / "speech", kokoro_worker_module="tests.fixtures.fake_kokoro_worker"
    )
    return RegistryTTS(registry, preferred="kokoro"), settings


async def test_warming_starts_the_worker_before_anything_is_spoken(tmp_path: Path) -> None:
    tts, _ = _tts(tmp_path)
    try:
        assert await tts.warm() is True

        provider = tts.selected_provider
        assert provider is not None and provider.worker_pid is not None
        warmed = provider.worker_pid
        chunks = [c async for c in provider.speak("Hello.", language="en", turn_epoch=1)]

        assert chunks and provider.worker_pid == warmed, "speaking started a second worker"
    finally:
        await tts.shutdown()


async def test_a_voice_that_cannot_be_warmed_is_reported_not_raised(tmp_path: Path) -> None:
    tts, _ = _tts(tmp_path, tamper="kokoro.model")
    try:
        assert await tts.warm() is False
    finally:
        await tts.shutdown()


async def test_warming_twice_is_harmless(tmp_path: Path) -> None:
    tts, _ = _tts(tmp_path)
    try:
        assert await tts.warm() and await tts.warm()
        assert tts.selected_provider.worker_pid is not None
    finally:
        await tts.shutdown()


def _app_with(tts: RegistryTTS, tmp_path: Path, *, warm: bool = True):
    settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "core",
        assistant_orchestrator="deterministic",
        tts_warm_on_start=warm,
    )
    lifecycle = CoreLifecycle(settings, text_to_speech_provider=tts)
    lifecycle.startup()
    return lifecycle, create_app(lifecycle)


def test_core_starts_and_answers_health_while_the_voice_is_still_loading(tmp_path: Path) -> None:
    release = threading.Event()
    started = threading.Event()

    class _SlowTts:
        async def warm(self) -> bool:
            started.set()
            await asyncio.to_thread(release.wait, 10)
            return True

        async def shutdown(self) -> None:
            return None

    lifecycle, app = _app_with(_SlowTts(), tmp_path)  # type: ignore[arg-type]
    try:
        began = time.monotonic()
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert time.monotonic() - began < 3, "startup waited for the voice"
            assert started.wait(5), "the warm-up never began"
            release.set()
    finally:
        release.set()
        lifecycle.shutdown()


def test_warm_up_can_be_switched_off(tmp_path: Path) -> None:
    called = threading.Event()

    class _Tts:
        async def warm(self) -> bool:
            called.set()
            return True

        async def shutdown(self) -> None:
            return None

    lifecycle, app = _app_with(_Tts(), tmp_path, warm=False)  # type: ignore[arg-type]
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            time.sleep(0.3)
        assert not called.is_set()
    finally:
        lifecycle.shutdown()


def test_a_warm_up_that_crashes_does_not_stop_core(tmp_path: Path) -> None:
    class _BrokenTts:
        async def warm(self) -> bool:
            raise RuntimeError("model exploded")

        async def shutdown(self) -> None:
            return None

    lifecycle, app = _app_with(_BrokenTts(), tmp_path)  # type: ignore[arg-type]
    try:
        with TestClient(app) as client:
            time.sleep(0.2)
            assert client.get("/health").status_code == 200
    finally:
        lifecycle.shutdown()


def test_shutting_down_cancels_a_warm_up_that_is_still_running(tmp_path: Path) -> None:
    cancelled = threading.Event()

    class _HangingTts:
        async def warm(self) -> bool:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return True

        async def shutdown(self) -> None:
            return None

    lifecycle, app = _app_with(_HangingTts(), tmp_path)  # type: ignore[arg-type]
    try:
        with TestClient(app):
            time.sleep(0.2)
        assert cancelled.wait(5), "the warm-up was left running after shutdown"
    finally:
        lifecycle.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="process liveness helper is Windows-focused")
async def test_a_warmed_worker_ends_with_the_provider(tmp_path: Path) -> None:
    tts, _ = _tts(tmp_path)
    await tts.warm()
    pid = tts.selected_provider.worker_pid
    assert pid is not None and pid_alive(pid)

    await tts.shutdown()

    assert wait_until_dead(pid, 5.0)
