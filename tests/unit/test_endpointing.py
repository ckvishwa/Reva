"""S06: Corx endpointing (ADR-037): ~280 ms end-of-speech, pre-roll, pauses as follow-up turns.

Synthetic clips only (tones and silence built in memory): no microphone, no model, no network. The
recorded-speech fixtures and the Silero backend are in test_endpointing_fixtures.py.
"""

from __future__ import annotations

import math
import random
from array import array

import pytest

from reva_core.voice.endpointing import (
    FRAME_MS,
    SAMPLE_RATE,
    EnergyVad,
    PreRollBuffer,
    SpeechTurn,
    TurnSegmenter,
    VadConfig,
    frames_of,
    segment,
)


def tone(ms: int, amplitude: float = 0.3, hz: int = 220) -> bytes:
    count = SAMPLE_RATE * ms // 1000
    return array(
        "h",
        (
            int(32767 * amplitude * math.sin(2 * math.pi * hz * i / SAMPLE_RATE))
            for i in range(count)
        ),
    ).tobytes()


def silence(ms: int) -> bytes:
    return bytes(SAMPLE_RATE * ms // 1000 * 2)


def hiss(ms: int, dbfs: float = -60.0, seed: int = 7) -> bytes:
    rng = random.Random(seed)  # noqa: S311 - test noise, not security
    peak = int(32768 * 10 ** (dbfs / 20))
    return array("h", (rng.randint(-peak, peak) for _ in range(SAMPLE_RATE * ms // 1000))).tobytes()


def run(*parts: bytes, **kwargs) -> list[SpeechTurn]:
    return segment(frames_of(b"".join(parts)), EnergyVad(), **kwargs)


def test_one_utterance_is_one_turn_closed_about_280_ms_after_it_ends() -> None:
    turns = run(silence(500), tone(1000), silence(1000))

    assert len(turns) == 1
    turn = turns[0]
    assert turn.ended_by == "vad"
    assert turn.follow_up is False and turn.gap_ms is None
    speech_ended_at = 500 + 1000
    # The VAD reports the end 280 ms of silence after the last speech, to the nearest frame.
    assert speech_ended_at + 280 - FRAME_MS <= turn.end_ms <= speech_ended_at + 280 + FRAME_MS
    assert (
        500 - 20 <= turn.start_ms <= 500 + 80
    )  # the start is reported after a few frames of speech


def test_the_turn_keeps_300_ms_of_audio_from_before_speech_was_noticed() -> None:
    turn = run(silence(1000), tone(800), silence(600))[0]

    # pre-roll (300 ms, which includes the ~60 ms the VAD needed) + speech + the closing silence
    assert turn.duration_ms >= 300 + 800 - 20
    head = 2 * SAMPLE_RATE * 100 // 1000
    assert turn.audio[:head] == bytes(head), "the pre-roll starts in the silence before the speech"
    voiced = sum(1 for sample in array("h", turn.audio) if abs(sample) > 1000)
    assert voiced >= SAMPLE_RATE * 760 // 1000 // 2, "the first syllable was clipped, not kept"


def test_a_pause_shorter_than_the_silence_rule_stays_inside_one_turn() -> None:
    turns = run(tone(700), silence(200), tone(700), silence(900))

    assert len(turns) == 1


def test_a_pause_just_under_280_ms_does_not_split_and_one_over_does() -> None:
    assert len(run(tone(600), silence(260), tone(600), silence(900))) == 1
    assert len(run(tone(600), silence(300), tone(600), silence(900))) == 2


def test_a_longer_pause_makes_the_next_speech_a_follow_up_turn() -> None:
    turns = run(tone(900), silence(700), tone(800), silence(900))

    assert [t.follow_up for t in turns] == [False, True]
    assert turns[1].gap_ms is not None and 350 <= turns[1].gap_ms <= 500, (
        "the gap is the silence after the first turn closed, not the whole pause"
    )
    assert [t.index for t in turns] == [0, 1]


def test_speech_long_after_the_last_turn_is_not_a_follow_up() -> None:
    turns = run(tone(600), silence(9_500), tone(600), silence(900))

    assert [t.follow_up for t in turns] == [False, False]


def test_the_follow_up_window_is_configurable() -> None:
    turns = run(tone(600), silence(2_000), tone(600), silence(900), follow_up_window_ms=500)

    assert [t.follow_up for t in turns] == [False, False]


def test_silence_and_quiet_room_noise_make_no_turns() -> None:
    assert run(silence(2000)) == []
    assert run(hiss(2000, dbfs=-62.0)) == []


def test_a_stream_that_ends_mid_speech_is_closed_as_eof() -> None:
    turns = run(silence(300), tone(900))

    assert len(turns) == 1 and turns[0].ended_by == "eof"
    assert turns[0].duration_ms >= 900


def test_frames_of_any_size_give_the_same_turns() -> None:
    clip = b"".join([silence(400), tone(900), silence(700), tone(500), silence(900)])
    reference = segment(frames_of(clip), EnergyVad())

    odd = segment((clip[i : i + 1_000] for i in range(0, len(clip), 1_000)), EnergyVad())

    assert [t.index for t in odd] == [t.index for t in reference]
    assert len(odd) == len(reference) == 2


def test_the_silence_rule_is_a_setting() -> None:
    clip = b"".join([tone(600), silence(400), tone(600), silence(900)])

    assert len(segment(frames_of(clip), EnergyVad(VadConfig(silence_ms=280)))) == 2
    assert len(segment(frames_of(clip), EnergyVad(VadConfig(silence_ms=500)))) == 1


def test_the_preroll_buffer_keeps_only_the_most_recent_frames() -> None:
    buffer = PreRollBuffer(60)  # three 20 ms frames
    for i in range(10):
        buffer.push(bytes([i]))

    assert buffer.drain() == [bytes([7]), bytes([8]), bytes([9])]
    assert buffer.drain() == []


def test_a_segmenter_can_be_fed_live_and_reports_turns_as_they_close() -> None:
    segmenter = TurnSegmenter(EnergyVad())
    closed_at: list[int] = []
    clip = b"".join([silence(200), tone(500), silence(1000)])
    for index, frame in enumerate(frames_of(clip)):
        if segmenter.feed(frame):
            closed_at.append((index + 1) * FRAME_MS)

    assert len(closed_at) == 1
    assert 200 + 500 + 280 - 40 <= closed_at[0] <= 200 + 500 + 280 + 40


@pytest.mark.parametrize("level", [0.02, 0.1, 0.3, 0.8])
def test_the_energy_vad_hears_speech_at_ordinary_levels(level: float) -> None:
    turns = run(silence(300), tone(800, amplitude=level), silence(700))

    assert len(turns) == 1
