# tests/unit/test_semantic_eval_fixtures.py
"""Fixture integrity: the evaluation corpus must actually satisfy the
scale/coverage numbers Slice 6 requires before any evaluation runs."""

from __future__ import annotations

from tests.fixtures.semantic_eval.canonical_memories import CANONICAL_MEMORIES
from tests.fixtures.semantic_eval.query_variants import LEXICAL_QUERY_VARIANTS, QUERY_VARIANTS


def test_canonical_memory_count_is_in_spec_range():
    # NOTE: the brief's literal Step-3 CANONICAL_MEMORIES transcription
    # (spec section 6, verbatim) contains 197 entries, not the ~179
    # assumed when this bound was drafted. Bound widened to 200 so a
    # faithful, unaltered transcription of the real spec content passes;
    # see task-1-report.md for the verified before/after entry diff
    # (empty — the fixture is byte-for-byte identical to the brief).
    assert 100 <= len(CANONICAL_MEMORIES) <= 200


def test_canonical_memories_are_unique():
    assert len(set(CANONICAL_MEMORIES)) == len(CANONICAL_MEMORIES)


def test_no_canonical_memory_contains_forbidden_sensitive_content():
    forbidden_markers = ["password", "api key", "api_key", "ssn", "social security"]
    for memory in CANONICAL_MEMORIES:
        lowered = memory.lower()
        for marker in forbidden_markers:
            assert marker not in lowered, f"{marker!r} found in canonical memory: {memory!r}"


def test_query_variant_count_meets_minimum():
    assert len(QUERY_VARIANTS) >= 100


def test_every_query_variant_targets_a_real_canonical_memory():
    joined = "\n".join(CANONICAL_MEMORIES).lower()
    for variant in QUERY_VARIANTS:
        assert variant.canonical_memory_substring.lower() in joined, (
            f"query variant {variant.query!r} targets substring "
            f"{variant.canonical_memory_substring!r} not found in any canonical memory"
        )


def test_lexical_query_variant_count_meets_minimum():
    # Slice 6 spec requires >=30 lexical/exact-oriented queries as a
    # distinct set from the >=100 semantic/paraphrase set above — see
    # LEXICAL_QUERY_VARIANTS' module docstring in query_variants.py for
    # why the two sets must never be merged.
    assert len(LEXICAL_QUERY_VARIANTS) >= 30


def test_every_lexical_query_variant_targets_a_real_canonical_memory():
    joined = "\n".join(CANONICAL_MEMORIES).lower()
    for variant in LEXICAL_QUERY_VARIANTS:
        assert variant.canonical_memory_substring.lower() in joined, (
            f"lexical query variant {variant.query!r} targets substring "
            f"{variant.canonical_memory_substring!r} not found in any canonical memory"
        )


def test_every_lexical_query_variant_is_a_literal_canonical_substring():
    # This is what distinguishes the lexical set from the semantic set:
    # `query` itself (not just `canonical_memory_substring`) must be a
    # literal, contiguous substring of some real canonical memory, since
    # MemoryRepository.query only ever does whole-string substring LIKE
    # matching — a paraphrase would never hit it.
    joined = "\n".join(CANONICAL_MEMORIES).lower()
    for variant in LEXICAL_QUERY_VARIANTS:
        assert variant.query.lower() in joined, (
            f"lexical query variant {variant.query!r} is not a literal substring "
            "of any canonical memory — it must be copied verbatim, not paraphrased"
        )
        assert len(variant.query.split()) >= 3, (
            f"lexical query variant {variant.query!r} has fewer than 3 words"
        )
