"""S06 first-audio budget: how the worker cuts text into chunks and trims the first one.

* The first chunk is the first *clause* when the first sentence is long, so audio starts sooner.
* Kokoro starts every phrase with a stretch of near-silence. On the first chunk of an utterance it
  is trimmed (keeping 20 ms), because nobody should wait for silence. Later chunks are left alone:
  the pauses between sentences are part of the voice.
"""

from __future__ import annotations

import pytest

from reva_core.voice import kokoro_worker as worker

RATE = worker.SAMPLE_RATE


def silence(ms: int) -> list[float]:
    return [0.0] * (RATE * ms // 1000)


def voice(ms: int, level: float = 0.2) -> list[float]:
    return [level] * (RATE * ms // 1000)


# --------------------------------------------------------------------------- trimming


def test_leading_silence_is_trimmed_to_twenty_milliseconds() -> None:
    samples = silence(210) + voice(500)

    trimmed = worker.trim_leading_silence(samples)

    assert len(trimmed) == RATE * 20 // 1000 + RATE * 500 // 1000
    assert trimmed[RATE * 20 // 1000] == 0.2


def test_near_silence_counts_as_silence() -> None:
    quiet = [0.001] * (RATE * 150 // 1000)

    trimmed = worker.trim_leading_silence(quiet + voice(300))

    assert len(trimmed) == RATE * 20 // 1000 + RATE * 300 // 1000


def test_audio_that_starts_with_sound_is_untouched() -> None:
    samples = voice(300)

    assert worker.trim_leading_silence(samples) == samples


def test_short_leading_silence_is_not_extended_or_cut_below_the_kept_margin() -> None:
    samples = silence(10) + voice(200)

    assert worker.trim_leading_silence(samples) == samples


def test_a_chunk_that_is_all_silence_is_left_alone() -> None:
    samples = silence(300)

    assert worker.trim_leading_silence(samples) == samples


def test_trimming_never_touches_the_sound_itself() -> None:
    samples = silence(300) + [0.5, -0.5, 0.25] + silence(100)

    trimmed = worker.trim_leading_silence(samples)

    assert trimmed[-(len(samples) - 300 * RATE // 1000) :] == samples[300 * RATE // 1000 :]


# -------------------------------------------------------------------------- chunking


def test_sentences_are_chunked_at_sentence_ends() -> None:
    assert worker.split_for_synthesis("Hello! I'm Reva. Ready?") == [
        "Hello!",
        "I'm Reva.",
        "Ready?",
    ]


def test_a_long_first_sentence_splits_at_the_first_comma_that_makes_a_real_clause() -> None:
    text = "Okay, and once you have confirmed the amount with the bank, I will record it for you."

    chunks = worker.split_for_synthesis(text)

    assert chunks[0] == "Okay, and once you have confirmed the amount with the bank,"
    assert chunks[1] == "I will record it for you."


def test_a_short_sentence_is_not_split() -> None:
    assert worker.split_for_synthesis("Yes, I can.") == ["Yes, I can."]


def test_only_the_first_sentence_is_split_by_clause() -> None:
    first = "Hello there and welcome back to the app, I hope your day is going well so far."
    text = first + " Second sentence, which is fairly long as well, goes here for the test."

    chunks = worker.split_for_synthesis(text)

    assert chunks[0].endswith(",") and chunks[0] != first
    assert chunks[-1] == "Second sentence, which is fairly long as well, goes here for the test."


@pytest.mark.parametrize("text", ["", "   ", "..."])
def test_text_with_nothing_to_say_gives_no_chunks_or_only_punctuation(text: str) -> None:
    assert all(chunk.strip() for chunk in worker.split_for_synthesis(text))


def test_a_clause_that_is_too_short_to_stand_alone_is_not_cut_off() -> None:
    text = "No, that is not something I am able to do because it has not been set up yet here."

    chunks = worker.split_for_synthesis(text)

    assert chunks[0] == text, "'No,' is two characters of audio; it stays with the rest"


def test_no_chunk_is_lost_or_reordered() -> None:
    text = "Well, I think we should start with the budget, then look at bills. After that, we rest."

    chunks = worker.split_for_synthesis(text)

    assert " ".join(chunks).replace("  ", " ") == text
