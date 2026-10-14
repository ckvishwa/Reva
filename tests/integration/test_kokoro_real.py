"""VOICE-1: the genuine Kokoro package and weights, driven through the production provider.

Opt-in (see `tests/fixtures/real_kokoro.py`). Every test here loads the real 82M model in a
real worker process through the manifest verifier, so the whole file takes a few minutes.
Without the environment these are SKIPPED; a skip is never evidence.

Covers: playable speech, stop, a newer turn invalidating an older one, no overlapping producers,
clean completion, no orphan processes after a hard kill, refusal of bad assets.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from reva_core.models.tts import SpeechChunk
from reva_core.providers.asset_manifest import AssetRefusal, AssetVerificationError
from reva_core.voice.kokoro_provider import KokoroSpeechProvider
from tests.fixtures.process_utils import pid_alive, wait_until_dead
from tests.fixtures.real_kokoro import RealKokoro, make_provider, real_kokoro, wav_stats

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the worker guarantees are verified on Windows"
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
GREETING = "Hello! I'm Reva. My voice system is online and working."
LONG_TEXT = (
    "This is a long test utterance for the interruption check. It has several sentences so that "
    "synthesis is still running when the stop arrives. Here is the third sentence of the text. "
    "And a fourth one follows it. The fifth sentence closes this passage."
)


@pytest.fixture
def real() -> RealKokoro:
    return real_kokoro()


@pytest.fixture
async def provider(real: RealKokoro, tmp_path: Path):
    kokoro = make_provider(real, tmp_path / "speech")
    yield kokoro
    await kokoro.shutdown()


def _delete(chunk: SpeechChunk) -> None:
    chunk.path.unlink(missing_ok=True)


def _kokoro_worker_pids() -> set[int]:
    """Every live process whose command line runs the Kokoro worker module."""
    script = (
        "Get-CimInstance Win32_Process | Where-Object "
        "{ $_.CommandLine -like '*reva_core.voice.kokoro_worker*' -and $_.ProcessId -ne $PID } | "
        "ForEach-Object { $_.ProcessId }"
    )
    done = subprocess.run(  # noqa: S603, S607 - fixed PowerShell query, no user input
        [shutil.which("powershell") or "powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {int(line) for line in done.stdout.split() if line.strip().isdigit()}


# 1. Speak produces playable speech ---------------------------------------------------------


async def test_speak_produces_playable_speech(provider: KokoroSpeechProvider) -> None:
    health = await provider.health()
    assert (health.ok, health.voice) == (True, "af_heart")

    chunks = [c async for c in provider.speak(GREETING, language="en", turn_epoch=1)]

    assert chunks, "no audio was produced"
    assert chunks[-1].final and not any(c.final for c in chunks[:-1])
    assert [c.index for c in chunks] == list(range(len(chunks)))
    total = 0.0
    for chunk in chunks:
        stats = wav_stats(chunk.path)
        assert (stats.sample_rate, stats.channels, stats.sample_width) == (24_000, 1, 2)
        assert stats.peak > 0.05, f"chunk {chunk.index} is silent (peak {stats.peak:.4f})"
        assert 0.01 < stats.rms < 0.7, f"chunk {chunk.index} rms {stats.rms:.4f} implausible"
        assert abs(stats.seconds * 1000 - chunk.duration_ms) < 5
        total += stats.seconds
        _delete(chunk)
    assert 2.0 < total < 15.0, f"{total:.1f}s of speech for a 10-word greeting"


# 2. Stop interrupts an active utterance ----------------------------------------------------


async def test_stop_interrupts_an_active_utterance_and_the_worker_survives(
    provider: KokoroSpeechProvider,
) -> None:
    await provider.health()
    worker_before = provider.worker_pid
    delivered: list[float] = []

    async def consume() -> None:
        async for chunk in provider.speak(LONG_TEXT, language="en", turn_epoch=2):
            delivered.append(time.monotonic())
            _delete(chunk)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.8)  # synthesis is under way
    stop_called = time.monotonic()
    await provider.stop(turn_epoch=3)
    stop_returned = time.monotonic()
    await asyncio.wait_for(task, timeout=10)

    assert stop_returned - stop_called < 0.3, "stop took longer than the 300 ms silence budget"
    assert all(t <= stop_returned for t in delivered), "audio was delivered after stop returned"
    assert provider.worker_pid == worker_before, "stop killed the worker (model reload next time)"

    # The same worker speaks the next utterance.
    chunks = [c async for c in provider.speak("Back again.", language="en", turn_epoch=3)]
    assert chunks and provider.worker_pid == worker_before
    for chunk in chunks:
        _delete(chunk)


# 3. A newer turn invalidates older playback --------------------------------------------------


async def test_a_newer_turn_invalidates_the_older_one(provider: KokoroSpeechProvider) -> None:
    await provider.health()
    old: list[tuple[float, SpeechChunk]] = []
    new: list[tuple[float, SpeechChunk]] = []

    async def consume(epoch: int, text: str, sink: list[tuple[float, SpeechChunk]]) -> None:
        async for chunk in provider.speak(text, language="en", turn_epoch=epoch):
            sink.append((time.monotonic(), chunk))

    first = asyncio.create_task(consume(10, LONG_TEXT, old))
    await asyncio.sleep(0.8)
    second_started = time.monotonic()
    await consume(11, "Newer turn speaking.", new)
    await asyncio.wait_for(first, timeout=10)

    assert new, "the newer turn produced no audio"
    assert {c.turn_epoch for _, c in new} == {11}
    assert all(c.turn_epoch == 10 for _, c in old)
    assert all(t <= second_started + 0.05 for t, _ in old), "old turn spoke after the new one began"

    # A request for an epoch older than the current one is ignored outright.
    assert [c async for c in provider.speak("Too late.", language="en", turn_epoch=10)] == []
    for _, chunk in old + new:
        _delete(chunk)


# 4. Two simultaneous requests cannot overlap ---------------------------------------------------


async def test_simultaneous_requests_never_overlap(provider: KokoroSpeechProvider) -> None:
    await provider.health()
    events: dict[str, list[float]] = {"a": [], "b": []}

    async def consume(name: str, text: str) -> None:
        async for chunk in provider.speak(text, language="en", turn_epoch=20):
            events[name].append(time.monotonic())
            _delete(chunk)
        events[name].append(time.monotonic())  # when the stream ended

    await asyncio.gather(
        consume("a", "First request. It has two sentences."), consume("b", "Second request.")
    )

    assert events["a"] and events["b"]
    one, two = sorted(events.values(), key=lambda times: times[0])
    assert max(one) <= min(two), "two producers delivered audio at the same time"


# 5. Natural completion releases resources ------------------------------------------------------


async def test_natural_completion_releases_resources(
    provider: KokoroSpeechProvider, tmp_path: Path
) -> None:
    chunks = [c async for c in provider.speak("One short sentence.", language="en", turn_epoch=1)]
    assert chunks and chunks[-1].final
    for chunk in chunks:
        _delete(chunk)

    assert provider._active is None  # noqa: SLF001 - no stream is left open after completion
    assert list((tmp_path / "speech").glob("chunk-*.wav")) == []
    worker = provider.worker_pid
    assert worker is not None and pid_alive(worker), "an idle worker should stay warm"

    await provider.shutdown()
    assert wait_until_dead(worker, 5.0), "shutdown left the worker running"
    assert provider.worker_pid is None


# 6. Hard-killing the owner leaves no orphan --------------------------------------------------


def test_killing_the_owner_leaves_no_kokoro_process(real: RealKokoro, tmp_path: Path) -> None:
    before = _kokoro_worker_pids()
    env = {**os.environ}
    host = subprocess.Popen(  # noqa: S603 - this interpreter, fixed module
        [sys.executable, "-m", "tests.fixtures.real_kokoro_host", str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
    )
    assert host.stdout is not None
    started = _worker_pids_after_ready(host)
    try:
        assert started, "no Kokoro worker process appeared"
        host.kill()  # TerminateProcess on the owner only; no Python cleanup runs
        host.wait(timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(pid_alive(p) for p in started):
            time.sleep(0.1)
        survivors = sorted(p for p in started if pid_alive(p))
        assert survivors == [], f"orphaned Kokoro processes: {survivors}"
        assert _kokoro_worker_pids() - before == set()
    finally:
        host.kill()
        for pid in started:
            if pid_alive(pid):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=False)  # noqa: S603, S607


def _worker_pids_after_ready(host: subprocess.Popen[str]) -> set[int]:
    assert host.stdout is not None
    line = host.stdout.readline()
    assert line, "the host exited before the real model was loaded"
    json.loads(line)  # {"pid": <launcher pid>}
    return _kokoro_worker_pids()


# 7. Invalid, missing, tampered or unlisted assets are refused -----------------------------------


def _manifest_variant(real: RealKokoro, tmp_path: Path, edit) -> Path:
    document = json.loads(real.manifest.read_text(encoding="utf-8-sig"))
    edit(document["assets"])
    path = tmp_path / "variant.manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _entry(assets: list[dict], suffix: str) -> dict:
    return next(a for a in assets if a["id"].endswith(suffix))


@pytest.mark.parametrize(
    ("label", "edit", "refusal"),
    [
        (
            "tampered hash",
            lambda a: _entry(a, ".model").update(sha256="0" * 64),
            AssetRefusal.HASH_MISMATCH,
        ),
        (
            "file missing",
            lambda a: _entry(a, ".config").update(path="models/tts/kokoro/1.0/none.json"),
            AssetRefusal.FILE_MISSING,
        ),
        (
            "provenance TODO",
            lambda a: _entry(a, "af_heart").update(provenance_status="TODO"),
            AssetRefusal.PROVENANCE_UNVERIFIED,
        ),
        (
            "excluded",
            lambda a: _entry(a, "af_heart").update(provenance_status="excluded"),
            AssetRefusal.EXCLUDED,
        ),
        (
            "hash not recorded",
            lambda a: _entry(a, ".model").update(sha256="TODO"),
            AssetRefusal.HASH_NOT_RECORDED,
        ),
        (
            "path traversal",
            lambda a: _entry(a, ".config").update(path="..\\..\\Windows\\win.ini"),
            AssetRefusal.PATH_ESCAPE,
        ),
        ("unlisted", lambda a: a.remove(_entry(a, "af_heart")), AssetRefusal.UNLISTED),
    ],
)
async def test_bad_assets_are_refused_and_no_worker_starts(
    real: RealKokoro, tmp_path: Path, label: str, edit, refusal: AssetRefusal
) -> None:
    manifest = _manifest_variant(real, tmp_path, edit)
    kokoro = make_provider(real, tmp_path / "speech", manifest=manifest)
    try:
        before = _kokoro_worker_pids()
        with pytest.raises(AssetVerificationError) as raised:
            await kokoro.health()
        assert raised.value.reason is refusal, label
        assert kokoro.worker_pid is None
        assert _kokoro_worker_pids() - before == set(), "a worker started for refused assets"
    finally:
        await kokoro.shutdown()


async def test_a_missing_manifest_is_refused(real: RealKokoro, tmp_path: Path) -> None:
    kokoro = make_provider(real, tmp_path / "speech", manifest=tmp_path / "nope.json")
    with pytest.raises(AssetVerificationError) as raised:
        await kokoro.health()
    assert raised.value.reason is AssetRefusal.MANIFEST_MISSING
    shutil.rmtree(tmp_path / "speech", ignore_errors=True)
