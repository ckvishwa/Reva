"""The pure parts of the owner-run evaluation tools (STT benchmark, wake-word scoring)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "voice"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stt = load("stt_benchmark")
wake = load("wake_eval")


@pytest.mark.parametrize(
    ("number", "words"),
    [
        (0, "zero"),
        (12, "twelve"),
        (21, "twenty one"),
        (100, "one hundred"),
        (1500, "one thousand five hundred"),
    ],
)
def test_numbers_are_spelled_out(number: int, words: str) -> None:
    assert stt.spell_number(number) == words


def test_digits_and_spoken_forms_normalise_to_the_same_words() -> None:
    assert stt.normalise("add $12 for lunch") == stt.normalise("Add twelve dollars for lunch.")
    assert stt.normalise("45.50") == ["forty", "five", "point", "fifty"]
    assert stt.normalise("$2,000 income") == stt.normalise("two thousand dollars income")


def test_wer_counts_word_substitutions_insertions_and_deletions() -> None:
    assert stt.wer([("open calculator", "open calculator")]) == 0.0
    assert stt.wer([("open calculator", "open the calculator")]) == pytest.approx(0.5)
    assert stt.wer([("open calculator now", "open calendar")]) == pytest.approx(2 / 3)
    assert stt.wer([]) == 0.0


def test_the_script_has_fifty_sentences_with_finance_phrases() -> None:
    sentences = stt.load_script()

    assert len(sentences) == 50
    assert sum("dollars" in s or "budget" in s for s in sentences) >= 10


def test_wake_scoring() -> None:
    result = wake.score(
        "porcupine", negative_seconds=7200, false_accepts=3, positives=50, detected=47
    )

    assert result.false_accepts_per_hour == pytest.approx(1.5)
    assert result.miss_rate == pytest.approx(0.06)
    assert result.negative_hours == 2.0


def test_wake_scoring_with_no_data_does_not_divide_by_zero() -> None:
    result = wake.score("openwakeword", 0, 0, 0, 0)

    assert result.false_accepts_per_hour == 0.0 and result.miss_rate == 0.0
