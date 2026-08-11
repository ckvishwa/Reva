"""Restart-safe backfill for memories missing an embedding.

Idempotent by construction: MemoryEmbeddingRepository.missing_for_model
only ever returns rows with no (memory_id, model_id) row yet, so a
rerun after a previous full or partial success naturally converges to
zero pending. A record that fails to embed is skipped (never raised
past this function) and reported in BackfillResult.failed_memory_ids —
the source `memories` row is never touched.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest
from reva_core.shared.logging import get_logger
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository

logger = get_logger("memory.embedding_backfill")


@dataclass(frozen=True)
class BackfillResult:
    embedded_count: int
    failed_count: int
    failed_memory_ids: tuple[str, ...]


async def backfill_missing_embeddings(
    conn: sqlite3.Connection,
    embedding_provider: EmbeddingProvider,
    *,
    model_id: str,
    correlation_id: str,
    batch_size: int = 100,
) -> BackfillResult:
    repo = MemoryEmbeddingRepository(conn)
    embedded_count = 0
    failed_ids: set[str] = set()

    while True:
        pending = repo.missing_for_model(model_id, batch_size)
        if not pending:
            break

        progressed = False
        for memory_id, content in pending:
            try:
                result = await embedding_provider.embed(
                    EmbeddingRequest(text=content, correlation_id=correlation_id)
                )
                repo.upsert(memory_id, model_id, result.vector)
                embedded_count += 1
                progressed = True
            except Exception:
                logger.warning("failed to embed memory during backfill", extra={"memory_id": memory_id}, exc_info=True)
                failed_ids.add(memory_id)

        if not progressed:
            # Every remaining pending record failed this pass — stop
            # instead of looping forever re-attempting the same failures.
            break

    return BackfillResult(embedded_count=embedded_count, failed_count=len(failed_ids), failed_memory_ids=tuple(sorted(failed_ids)))
