"""Persistence for `memory_embeddings` — a derived, rebuildable index.

Vectors are packed as little-endian float32 BLOBs (struct 'f') rather
than JSON text: fixed-size binary keeps rows small and decode fast for
the pure-Python cosine comparison in reva_core/memory/hybrid_retrieval.py.
A row whose BLOB length isn't a multiple of 4 bytes is corrupt (never
possible via this repository's own upsert path, but defensive against a
future manual edit or partial write) and is skipped, not raised, by
`all_for_model` — see docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md
Task 2 for why (malformed/corrupt embedding handling must degrade
gracefully, never crash retrieval).
"""

from __future__ import annotations

import sqlite3
import struct

from reva_core.shared.errors import StorageError
from reva_core.shared.logging import get_logger
from reva_core.shared.time import utc_now

logger = get_logger("storage.memory_embeddings")


def _encode_vector(vector: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _decode_vector(blob: bytes) -> tuple[float, ...] | None:
    if len(blob) % 4 != 0:
        return None
    count = len(blob) // 4
    try:
        return struct.unpack(f"<{count}f", blob)
    except struct.error:
        return None


class MemoryEmbeddingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, memory_id: str, model_id: str, vector: tuple[float, ...]) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO memory_embeddings (memory_id, model_id, dims, vector, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(memory_id, model_id) DO UPDATE SET
                    dims = excluded.dims, vector = excluded.vector, created_at = excluded.created_at
                """,
                (memory_id, model_id, len(vector), _encode_vector(vector), utc_now().isoformat()),
            )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to upsert embedding for memory {memory_id}: {exc}") from exc

    def get(self, memory_id: str, model_id: str) -> tuple[float, ...] | None:
        row = self._conn.execute(
            "SELECT vector FROM memory_embeddings WHERE memory_id = ? AND model_id = ?",
            (memory_id, model_id),
        ).fetchone()
        if row is None:
            return None
        return _decode_vector(row["vector"])

    def all_for_model(self, model_id: str) -> list[tuple[str, tuple[float, ...]]]:
        rows = self._conn.execute(
            "SELECT memory_id, vector FROM memory_embeddings WHERE model_id = ?",
            (model_id,),
        ).fetchall()
        results: list[tuple[str, tuple[float, ...]]] = []
        for row in rows:
            decoded = _decode_vector(row["vector"])
            if decoded is None:
                logger.warning(
                    "skipping corrupt embedding",
                    extra={"memory_id": row["memory_id"], "model_id": model_id},
                )
                continue
            results.append((row["memory_id"], decoded))
        return results

    def missing_for_model(self, model_id: str, batch_size: int) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            """
            SELECT m.id AS memory_id, m.content AS content
            FROM memories m
            LEFT JOIN memory_embeddings e ON e.memory_id = m.id AND e.model_id = ?
            WHERE e.memory_id IS NULL AND m.retention_state = 'active'
            ORDER BY m.created_at ASC
            LIMIT ?
            """,
            (model_id, batch_size),
        ).fetchall()
        return [(row["memory_id"], row["content"]) for row in rows]
