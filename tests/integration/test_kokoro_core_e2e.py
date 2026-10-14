"""VOICE-1: a real Core (process and lifecycle) with the real Kokoro provider.

Opt-in (see `tests/fixtures/real_kokoro.py`). Throw-away data directory, loopback only, a port
picked by the OS. Checks the legacy speech route end to end, then both ways a Core can end:
`lifecycle.shutdown()` (in-process, as `__main__` runs it) and a hard kill (nothing in Python
runs). In both, no Kokoro process may survive. A CTRL_BREAK is not used as a "graceful stop":
this Core exits at once on it without running shutdown, with or without Kokoro.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.security.local_token import token_path_for
from reva_core.shared.contracts.health import CoreStatus
from tests.fixtures.real_kokoro import ASSET_ROOT_VAR, PYTHON_VAR, real_kokoro, wav_stats
from tests.integration.test_kokoro_real import GREETING, _kokoro_worker_pids

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process semantics")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Core:
    def __init__(self, tmp_path: Path) -> None:
        real = real_kokoro()
        self.data_dir = tmp_path / "data"
        self.port = _free_port()
        self.log = tmp_path / "core.log"
        env = {
            **os.environ,
            "REVA_DATA_DIR": str(self.data_dir),
            "REVA_API_PORT": str(self.port),
            "REVA_TTS_ENABLED": "1",
            "REVA_TTS_PROVIDER": "kokoro",
            "REVA_KOKORO_PYTHON": os.environ[PYTHON_VAR],
            "REVA_ASSET_ROOT": os.environ[ASSET_ROOT_VAR],
            "REVA_DOMAIN_KEYSTORE": "memory",
        }
        assert real.manifest.is_file()
        self._log_handle = self.log.open("wb")
        self.process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed module
            [sys.executable, "-m", "reva_core", "--serve"],
            cwd=_REPO_ROOT,
            env=env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def wait_healthy(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert self.process.poll() is None, f"Core exited early:\n{self.output()}"
            try:
                with urllib.request.urlopen(  # noqa: S310 - loopback URL built above
                    f"{self.base}/health", timeout=2
                ) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        raise AssertionError(f"Core never became healthy:\n{self.output()}")

    def token(self) -> str:
        return token_path_for(self.data_dir).read_text(encoding="utf-8").strip()

    def speak(self, text: str) -> bytes:
        request = urllib.request.Request(  # noqa: S310 - loopback URL built above
            f"{self.base}/v1/voice/speech",
            data=json.dumps({"text": text, "language": "en"}).encode(),
            headers={
                "Authorization": f"Bearer {self.token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
            assert response.status == 200
            return response.read()

    def output(self) -> str:
        self._log_handle.flush()
        return self.log.read_text(encoding="utf-8", errors="replace")[-4000:]

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        self._log_handle.close()


def _wait_no_workers(before: set[int], timeout: float = 15.0) -> set[int]:
    deadline = time.monotonic() + timeout
    left = _kokoro_worker_pids() - before
    while left and time.monotonic() < deadline:
        time.sleep(0.3)
        left = _kokoro_worker_pids() - before
    return left


@pytest.fixture
def core(tmp_path: Path):
    instance = _Core(tmp_path)
    yield instance
    instance.close()


def test_the_speech_route_returns_real_audio(core: _Core, tmp_path: Path) -> None:
    before = _kokoro_worker_pids()
    core.wait_healthy()

    audio = core.speak(GREETING)

    wav = tmp_path / "speech.wav"
    wav.write_bytes(audio)
    stats = wav_stats(wav)
    assert audio[:4] == b"RIFF"
    assert (stats.sample_rate, stats.channels) == (24_000, 1)
    assert stats.peak > 0.05 and stats.seconds > 2.0
    assert _kokoro_worker_pids() - before, "the speech request should have started a worker"


def test_the_lifecycle_shutdown_ends_the_real_worker(tmp_path: Path) -> None:
    """What `python -m reva_core --serve` does: serve on one loop, then `lifecycle.shutdown()`.

    The provider is used on a loop that is then closed (uvicorn's), and shutdown runs its async
    cleanup on a fresh loop. That must still complete, close Core, and end the worker.
    """
    real = real_kokoro()
    settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        tts_enabled=True,
        kokoro_python=real.python,
        asset_root=real.asset_root,
        tts_provider="kokoro",
        tts_ready_timeout_seconds=120.0,
    )
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    before = _kokoro_worker_pids()
    tts = lifecycle.text_to_speech_provider
    assert tts is not None

    async def serve() -> None:
        audio = await tts.synthesize("Hello there.", "en")
        assert audio.duration_ms > 500

    asyncio.run(serve())
    assert _kokoro_worker_pids() - before, "the worker should be alive until shutdown"

    lifecycle.shutdown()

    assert lifecycle.health().status is CoreStatus.STOPPED
    assert _wait_no_workers(before) == set(), "a Kokoro process outlived lifecycle.shutdown()"


def test_a_hard_kill_of_core_leaves_no_kokoro_process(core: _Core) -> None:
    before = _kokoro_worker_pids()
    core.wait_healthy()
    core.speak("Short line.")
    assert _kokoro_worker_pids() - before

    core.process.kill()  # TerminateProcess: no Python cleanup runs
    core.process.wait(timeout=10)

    assert _wait_no_workers(before) == set(), "a Kokoro process outlived a killed Core"
