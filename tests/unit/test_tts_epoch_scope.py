"""Known gap, recorded so S06 cannot overlook it: the provider's epoch is global, sessions' are not.

`KokoroSpeechProvider` keeps ONE `_epoch` and ignores `speak(turn_epoch=n)` when n is below it.
Each `VoiceSession` numbers its own turns from 0. Once any session has interrupted (the session's
stop hook calls `provider.stop(turn_epoch=k)`), another session, or the same session after it is
closed and reopened, speaks with a lower number and is silently ignored.

Nothing calls `speak` from a session yet, so nothing is broken today. S06 wires sessions to TTS
and must make the epoch per session (or globally monotonic) first. This test states the wanted
behavior and is a strict xfail: when it starts passing, remove the marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from reva_core.voice.kokoro_provider import KokoroSpeechProvider
from tests.fixtures.kokoro_assets import IDS, write_assets


async def test_a_second_session_with_lower_epochs_can_still_speak(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    manifest = write_assets(root)
    provider = KokoroSpeechProvider(
        python_exe=Path(sys.executable),
        manifest_path=manifest,
        asset_root=root,
        asset_ids=IDS,
        output_dir=tmp_path / "speech",
        worker_module="tests.fixtures.fake_kokoro_worker",
        ready_timeout_seconds=10.0,
    )
    try:
        await provider.stop(turn_epoch=5)  # session A has interrupted five times

        # Session B is brand new: its first turn is epoch 1.
        chunks = [c async for c in provider.speak("Hello from B.", language="en", turn_epoch=1)]

        assert chunks, "session B was silently ignored because the provider epoch is global"
    finally:
        await provider.shutdown()


test_a_second_session_with_lower_epochs_can_still_speak = pytest.mark.xfail(
    strict=True, reason="latent: provider epoch is global; S06 must scope it per session"
)(test_a_second_session_with_lower_epochs_can_still_speak)
