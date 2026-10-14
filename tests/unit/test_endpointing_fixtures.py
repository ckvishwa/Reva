"""S06: endpointing on recorded-speech fixture clips (synthetic Kokoro speech, no microphone).

The clips are built by `tools/voice/make_endpointing_fixtures.py` and committed, with
`expected.json` recording where each phrase was placed. The Energy backend runs everywhere; the
Silero backend (the Corx model) runs through a separate interpreter when REVA_VAD_PYTHON names one
that has `silero-vad`, and is SKIPPED (never passed) otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from array import array
from pathlib import Path

import pytest

from reva_core.voice.endpointing import FRAME_MS, EnergyVad, SpeechTurn, frames_of, segment

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "endpointing"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
REPO_ROOT = Path(__file__).resolve().parents[2]


def pcm(name: str) -> bytes:
    with wave.open(str(FIXTURES / name), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16_000, 1, 2)
        return wav.readframes(wav.getnframes())


def piece(name: str, label: str) -> dict:
    return next(p for p in EXPECTED[name]["layout"] if p["label"] == label)


def last_loud_ms(name: str, before_ms: int) -> int:
    """When speech really stopped before `before_ms`, measured with the VAD's own loudness rule."""
    frames = list(frames_of(pcm(name)))
    last = 0
    for index, frame in enumerate(frames):
        end = (index + 1) * FRAME_MS
        if end > before_ms:
            break
        if EnergyVad.level_dbfs(frame) >= -42.0:
            last = end
    return last


def energy_turns(name: str) -> list[SpeechTurn]:
    return segment(frames_of(pcm(name)), EnergyVad())


def test_two_phrases_with_a_pause_are_two_turns_and_the_second_is_a_follow_up() -> None:
    turns = energy_turns("two_turns.wav")

    assert len(turns) == 2
    assert [t.follow_up for t in turns] == [False, True]
    add, pause = piece("two_turns.wav", "add"), piece("two_turns.wav", "pause")
    assert add["start_ms"] <= turns[0].start_ms <= add["start_ms"] + 500
    assert turns[0].end_ms < pause["end_ms"], "the first turn closed during the pause, not after it"
    actually = piece("two_turns.wav", "actually")
    assert (
        turns[1].start_ms >= pause["end_ms"] - 100
        and turns[1].start_ms <= actually["start_ms"] + 500
    )


def test_the_end_of_speech_is_reported_about_280_ms_after_the_last_word() -> None:
    turns = energy_turns("two_turns.wav") + energy_turns("single_with_margins.wav")
    lags = []
    for name, turn in (
        ("two_turns.wav", turns[0]),
        ("two_turns.wav", turns[1]),
        ("single_with_margins.wav", turns[2]),
    ):
        lags.append(turn.end_ms - last_loud_ms(name, turn.end_ms))

    assert all(280 - FRAME_MS <= lag <= 280 + 2 * FRAME_MS for lag in lags), f"lags in ms: {lags}"


def test_a_short_hesitation_inside_a_sentence_does_not_split_it() -> None:
    turns = energy_turns("short_pause_inside.wav")

    assert len(turns) == 1
    assert turns[0].follow_up is False


def test_a_single_phrase_keeps_its_leading_context_and_closes_once() -> None:
    turns = energy_turns("single_with_margins.wav")

    assert len(turns) == 1 and turns[0].ended_by == "vad"
    speech = piece("single_with_margins.wav", "budget")
    assert turns[0].audio[: 2 * 16 * 100] == bytes(2 * 16 * 100), (
        "starts in the silence before speech"
    )
    assert turns[0].duration_ms >= (speech["end_ms"] - speech["start_ms"]) - 200


def test_a_quiet_room_is_not_speech() -> None:
    assert energy_turns("quiet_room.wav") == []


def test_every_fixture_loads_and_matches_its_recorded_length() -> None:
    for name, info in EXPECTED.items():
        samples = array("h")
        samples.frombytes(pcm(name))
        assert abs(len(samples) / 16 - info["duration_ms"]) <= 1, name


SILERO_PYTHON = os.environ.get("REVA_VAD_PYTHON")

_SILERO_RUNNER = """
import json, sys, wave
sys.path.insert(0, sys.argv[1])
from reva_core.voice.endpointing import SileroVad, frames_of, segment
out = {}
for name in sys.argv[3:]:
    with wave.open(sys.argv[2] + "/" + name, "rb") as w:
        data = w.readframes(w.getnframes())
    turns = segment(frames_of(data), SileroVad())
    out[name] = [
        {"start_ms": t.start_ms, "end_ms": t.end_ms, "follow_up": t.follow_up} for t in turns
    ]
print(json.dumps(out))
"""


@pytest.mark.skipif(
    not SILERO_PYTHON or not Path(SILERO_PYTHON).is_file(),
    reason="Silero check is opt-in: set REVA_VAD_PYTHON to an interpreter with silero-vad",
)
def test_the_silero_backend_finds_the_same_turns_as_the_energy_backend() -> None:
    assert SILERO_PYTHON is not None
    names = ["two_turns.wav", "short_pause_inside.wav", "single_with_margins.wav", "quiet_room.wav"]
    done = subprocess.run(  # noqa: S603 - the configured interpreter, a fixed script, repo fixtures
        [SILERO_PYTHON, "-c", _SILERO_RUNNER, str(REPO_ROOT), str(FIXTURES), *names],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert done.returncode == 0, done.stderr[-800:]
    found = json.loads(done.stdout.strip().splitlines()[-1])

    assert [len(found[n]) for n in names] == [2, 1, 1, 0], found
    assert [t["follow_up"] for t in found["two_turns.wav"]] == [False, True]
    add = piece("two_turns.wav", "add")
    first = found["two_turns.wav"][0]
    assert add["start_ms"] - 100 <= first["start_ms"] <= add["start_ms"] + 700


def test_the_runner_script_compiles() -> None:
    compile(_SILERO_RUNNER, "silero-runner", "exec")
    assert sys.version_info >= (3, 12)
