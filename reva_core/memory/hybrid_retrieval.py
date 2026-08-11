# reva_core/memory/hybrid_retrieval.py
"""Hybrid lexical + semantic memory ranking.

query
  |-- lexical candidates: MemoryRepository.query (existing LIKE search)
  `-- semantic candidates: cosine similarity over memory_embeddings
             |
      normalize both to [0,1]
             |
   hybrid = semantic_weight * semantic_norm + lexical_weight * lexical_norm
             |
  drop hybrid < minimum_confidence (only when a genuine semantic
  signal exists for this search), sort, deterministic tie-break

Never raises on embedding-backend failure: a failed query embedding
degrades to lexical-only ranking rather than failing the whole search
(this is what keeps GET /v1/memories and search_memory working when
Ollama is down after startup). "Degrades to lexical-only" means exactly
that: when there is no genuine semantic signal for this search — no
query embedding at all (no provider, or the embed call failed), or the
corpus has zero embedding rows for this model_id (e.g. Ollama was down
for the whole startup backfill, or a memory was created mid-session and
hasn't been backfilled yet) — `minimum_confidence` — calibrated for the
blended 70/30 signal — is not applied, so the result set matches what
`MemoryRepository.query` alone would have returned, not a silently
truncated subset of it.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest
from reva_core.shared.contracts.memory import Memory, RetentionState
from reva_core.shared.logging import get_logger
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

logger = get_logger("memory.hybrid_retrieval")

_LEXICAL_CANDIDATE_LIMIT = 50


@dataclass(frozen=True)
class RankedMemory:
    memory: Memory
    hybrid_score: float
    semantic_score: float
    lexical_score: float


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def hybrid_search(
    conn: sqlite3.Connection,
    embedding_provider: EmbeddingProvider | None,
    *,
    query: str,
    limit: int,
    model_id: str,
    correlation_id: str,
    config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG,
) -> list[RankedMemory]:
    memories_repo = MemoryRepository(conn)
    embeddings_repo = MemoryEmbeddingRepository(conn)

    lexical_matches = memories_repo.query(query, _LEXICAL_CANDIDATE_LIMIT)
    lexical_rank = {m.id: rank for rank, m in enumerate(lexical_matches)}
    lexical_count = len(lexical_matches)

    query_vector: tuple[float, ...] | None = None
    if embedding_provider is not None:
        try:
            request = EmbeddingRequest(text=query, correlation_id=correlation_id)
            embedded = await embedding_provider.embed(request)
            query_vector = embedded.vector
        except Exception:
            logger.warning("query embedding failed; falling back to lexical-only", exc_info=True)
            query_vector = None

    semantic_scores: dict[str, float] = {}
    memories_by_id: dict[str, Memory] = {m.id: m for m in lexical_matches}
    if query_vector is not None:
        for memory_id, vector in embeddings_repo.all_for_model(model_id):
            semantic_scores[memory_id] = max(0.0, cosine_similarity(query_vector, vector))

    candidate_ids = set(lexical_rank) | set(semantic_scores)
    if not candidate_ids:
        return []

    missing_ids = candidate_ids - set(memories_by_id)
    if missing_ids:
        # Semantic-only candidates come from `memory_embeddings`, which has
        # no retention_state predicate of its own (it's a derived index
        # keyed only by memory_id/model_id). Without the `retention_state`
        # check here, an archived/deleted memory whose embedding row was
        # never cleaned up could surface via the semantic path even though
        # `MemoryRepository.query` (the lexical path) would never return
        # it. Excluding it here is sufficient: the id simply won't land in
        # `memories_by_id`, so the loop below's `if candidate_memory is
        # None: continue` silently drops it from the final results.
        placeholders = ",".join("?" for _ in missing_ids)
        rows = conn.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders}) AND retention_state = ?",  # noqa: S608 - placeholders are literal '?' marks, not interpolated values; params passed separately below
            (*missing_ids, RetentionState.ACTIVE.value),
        ).fetchall()
        for row in rows:
            fetched_memory = MemoryRepository._row_to_memory(row)  # noqa: SLF001 - same-package reuse, not a public API break
            memories_by_id[fetched_memory.id] = fetched_memory

    ranked: list[RankedMemory] = []
    for memory_id in candidate_ids:
        candidate_memory = memories_by_id.get(memory_id)
        if candidate_memory is None:
            continue
        in_lexical = memory_id in lexical_rank
        lexical_score = (
            (lexical_count - lexical_rank[memory_id]) / lexical_count if in_lexical else 0.0
        )
        semantic_score = semantic_scores.get(memory_id, 0.0)
        hybrid_score = (
            config.semantic_weight * semantic_score + config.lexical_weight * lexical_score
        )
        # `minimum_confidence` is calibrated for the blended 70/30 signal.
        # When there is no semantic signal at all for this query, applying
        # it anyway is mathematically wrong: every candidate's
        # semantic_score is 0.0, so only the rank-normalized top slice of
        # lexical matches would ever clear the threshold. A
        # degraded-to-lexical-only search must return exactly what
        # `MemoryRepository.query` would have (bounded only by `limit`),
        # never a silently truncated subset. There are two distinct ways
        # "no semantic signal at all" happens, and both must bypass the
        # filter:
        #   1. `query_vector is None` — no embedding provider, or the
        #      query-embedding call itself failed.
        #   2. `not semantic_scores` — the query embedded fine, but
        #      `memory_embeddings` has zero rows for this `model_id` (e.g.
        #      the backfill never ran, or Ollama was down for the whole
        #      startup backfill window). Every candidate's semantic_score
        #      is then 0.0 for the same reason as case 1, so the filter
        #      would truncate to the top third of lexical matches — worse
        #      than plain lexical search.
        # This bypass does NOT apply to an individual candidate that merely
        # lacks its own embedding row while OTHER candidates for this query
        # do have one (ordinary backfill lag) — that candidate's
        # semantic_score of 0.0 is still meaningful relative to candidates
        # that do have a real embedding, so the blended filter stays
        # intentional there.
        if (
            query_vector is not None
            and semantic_scores
            and hybrid_score < config.minimum_confidence
        ):
            continue
        ranked.append(
            RankedMemory(
                memory=candidate_memory,
                hybrid_score=hybrid_score,
                semantic_score=semantic_score,
                lexical_score=lexical_score,
            )
        )

    ranked.sort(key=lambda r: (-r.hybrid_score, -r.memory.updated_at.timestamp(), r.memory.id))
    return ranked[:limit]
