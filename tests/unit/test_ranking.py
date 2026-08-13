"""Ranking weights must live in exactly one place and be testable in
isolation — see docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md."""

from __future__ import annotations

import pytest

from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig


def test_default_config_documents_seventy_thirty_split():
    assert DEFAULT_HYBRID_RANKING_CONFIG.semantic_weight == pytest.approx(0.70)
    assert DEFAULT_HYBRID_RANKING_CONFIG.lexical_weight == pytest.approx(0.30)


def test_default_config_weights_sum_to_one():
    total = (
        DEFAULT_HYBRID_RANKING_CONFIG.semantic_weight + DEFAULT_HYBRID_RANKING_CONFIG.lexical_weight
    )
    assert total == pytest.approx(1.0)


def test_default_config_uses_evaluation_backed_no_match_thresholds():
    assert DEFAULT_HYBRID_RANKING_CONFIG.minimum_confidence == pytest.approx(0.20)
    assert DEFAULT_HYBRID_RANKING_CONFIG.minimum_semantic_only_confidence == pytest.approx(0.57)


def test_config_is_frozen():
    with pytest.raises(AttributeError):
        DEFAULT_HYBRID_RANKING_CONFIG.semantic_weight = 0.5  # type: ignore[misc]


def test_custom_config_is_constructible_for_tests():
    custom = HybridRankingConfig(semantic_weight=0.5, lexical_weight=0.5, minimum_confidence=0.1)

    assert custom.semantic_weight == 0.5
    assert custom.minimum_confidence == 0.1
