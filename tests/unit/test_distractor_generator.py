"""Distractor generation must be deterministic, clearly test-only, and
never overlap with any real canonical memory content."""

from __future__ import annotations

from tests.fixtures.semantic_eval.canonical_memories import CANONICAL_MEMORIES
from tests.fixtures.semantic_eval.distractor_generator import generate_distractors


def test_generates_exact_requested_count():
    assert len(generate_distractors(50)) == 50


def test_is_deterministic_across_calls():
    assert generate_distractors(100) == generate_distractors(100)


def test_distractors_are_unique():
    distractors = generate_distractors(400)
    assert len(set(distractors)) == len(distractors)


def test_distractors_never_duplicate_a_canonical_memory():
    distractors = set(generate_distractors(400))
    assert distractors.isdisjoint(set(CANONICAL_MEMORIES))


def test_distractors_are_clearly_marked_test_only():
    for distractor in generate_distractors(50):
        assert distractor.startswith("The test user ") or distractor.startswith("Project ")


def test_supports_at_least_five_hundred_without_repeating():
    distractors = generate_distractors(500)
    assert len(distractors) == 500
    assert len(set(distractors)) == 500
