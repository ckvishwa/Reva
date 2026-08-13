"""Centralized hybrid ranking weights.

Every constant that influences how lexical and semantic scores combine
lives here and nowhere else — see docs/adr for the rationale if one is
added later. 0.70/0.30 is a documented starting point (Slice 6), not a
tuned optimum; see docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md
for the evaluation that validates or adjusts it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HybridRankingConfig:
    semantic_weight: float
    lexical_weight: float
    minimum_confidence: float
    minimum_semantic_only_confidence: float = 0.0


DEFAULT_HYBRID_RANKING_CONFIG = HybridRankingConfig(
    semantic_weight=0.70,
    lexical_weight=0.30,
    minimum_confidence=0.20,
    # Real nomic-embed-text score distribution from the 1000-memory Slice 6
    # evaluation: semantic-only negative candidates topped out at 0.568.
    # This gate only applies when a candidate has no lexical overlap, so
    # exact lexical fallback behavior remains intact.
    minimum_semantic_only_confidence=0.57,
)
