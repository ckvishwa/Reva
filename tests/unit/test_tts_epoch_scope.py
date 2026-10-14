"""S06: `turn_epoch` belongs to a session, not to the whole TTS provider.

Each `VoiceSession` numbers its turns from 0. Until S06 the provider kept ONE epoch and ignored any
`speak` whose epoch was below it, so after one session interrupted, another session (or the same one
reopened) was silently ignored. The provider now keeps an epoch per scope (the session id). There is
still exactly one audio producer: a request from another scope waits its turn, and a session can
only silence its own speech.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

from reva_core.voice.kokoro_provider import KokoroSpeechProvider
from tests.fixtures.kokoro_assets import IDS, write_assets


@pytest.fixture
async def provider(tmp_path: Path):
    root = tmp_path / "assets"
    manifest = write_assets(root)
    kokoro = KokoroSpeechProvider(
        python_exe=Path(sys.executable),
        manifest_path=manifest,
        asset_root=root,
        asset_ids=IDS,
        output_dir=tmp_path / "speech",
        worker_module="tests.fixtures.fake_kokoro_worker",
        ready_timeout_seconds=10.0,
    )
    yield kokoro
    await kokoro.shutdown()


async def _speak(provider, text: str, *, scope: str, epoch: int) -> list[tuple[float, int]]:
    seen: list[tuple[float, int]] = []
    async for chunk in provider.speak(text, language="en", turn_epoch=epoch, scope=scope):
        seen.append((time.monotonic(), chunk.index))
        chunk.path.unlink(missing_ok=True)
    return seen


async def test_a_second_session_with_lower_epochs_can_still_speak(provider) -> None:
    await provider.stop(turn_epoch=5, scope="session-a")  # session A has interrupted five times

    # Session B is brand new: its first turn is epoch 1.
    chunks = await _speak(provider, "Hello from B.", scope="session-b", epoch=1)

    assert chunks, "session B was silently ignored because epochs were global"


async def test_the_same_session_is_still_gated_by_its_own_epoch(provider) -> None:
    await provider.stop(turn_epoch=5, scope="session-a")

    stale = await _speak(provider, "Too late.", scope="session-a", epoch=4)
    current = await _speak(provider, "Right now.", scope="session-a", epoch=5)

    assert stale == []
    assert current


async def test_one_session_cannot_silence_another(provider) -> None:
    speaking = asyncio.create_task(_speak(provider, "slow", scope="session-b", epoch=1))
    await asyncio.sleep(0.4)  # B is part-way through a long utterance

    await provider.stop(turn_epoch=9, scope="session-a")  # A interrupts; this is not B's business
    chunks = await asyncio.wait_for(speaking, timeout=10)

    assert len(chunks) == 40, "session B's speech was cut short by session A"


async def test_a_session_silences_its_own_speech(provider) -> None:
    speaking = asyncio.create_task(_speak(provider, "slow", scope="session-a", epoch=1))
    await asyncio.sleep(0.4)

    await provider.stop(turn_epoch=2, scope="session-a")
    chunks = await asyncio.wait_for(speaking, timeout=10)

    assert 0 < len(chunks) < 40


async def test_two_concurrent_sessions_never_overlap_and_both_finish(provider) -> None:
    first, second = await asyncio.gather(
        _speak(provider, "slow", scope="session-a", epoch=3),
        _speak(provider, "Short one.", scope="session-b", epoch=1),
    )

    assert first and second
    one, two = sorted((first, second), key=lambda times: times[0][0])
    assert max(t for t, _ in one) <= min(t for t, _ in two), "two producers delivered at once"
    assert len(first) == 40 and len(second) == 3


async def test_a_newer_turn_in_one_scope_cancels_only_that_scopes_older_turn(provider) -> None:
    older = asyncio.create_task(_speak(provider, "slow", scope="session-a", epoch=1))
    await asyncio.sleep(0.4)

    newer = await _speak(provider, "Newer turn.", scope="session-a", epoch=2)
    cut = await asyncio.wait_for(older, timeout=10)

    assert newer
    assert 0 < len(cut) < 40


async def test_the_legacy_unscoped_calls_behave_as_before(provider) -> None:
    assert await _speak(provider, "Hello.", scope="", epoch=1)
    await provider.stop(turn_epoch=3)
    assert await _speak(provider, "Stale.", scope="", epoch=2) == []
