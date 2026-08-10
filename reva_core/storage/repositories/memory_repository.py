"""Persistence for `memories`.

Query strategy: normalized case-insensitive substring matching via
SQL `LIKE` against `lower(content)`. This is deliberately not semantic
search — no tokenization, stemming, or ranking beyond recency. See
docs/architecture/storage-design.md for why that is the right scope
for Phase 1A and docs/testing/acceptance-matrix.md for what remains
PLANNED (real semantic retrieval).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.errors import StorageError

_TAG_DELIMITER = ","


def _tags_to_column(tags: tuple[str, ...]) -> str:
    return _TAG_DELIMITER.join(tags)


def _tags_from_column(value: str) -> tuple[str, ...]:
    return tuple(t for t in value.split(_TAG_DELIMITER) if t)


class MemoryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, memory: Memory) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO memories
                    (id, category, content, source_conversation_id, source_message_id,
                     origin_device_id, source_note, tags, retention_state, sync_version,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.category.value,
                    memory.content,
                    memory.source.conversation_id,
                    memory.source.message_id,
                    memory.source.origin_device_id,
                    memory.source.note,
                    _tags_to_column(memory.tags),
                    memory.retention_state.value,
                    memory.sync_version,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                ),
            )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to insert memory {memory.id}: {exc}") from exc

    def query(self, text: str, limit: int) -> list[Memory]:
        normalized = f"%{text.strip().lower()}%"
        rows = self._conn.execute(
            """
            SELECT * FROM memories
            WHERE retention_state = ? AND lower(content) LIKE ?
            ORDER BY updated_at DESC, ROWID DESC
            LIMIT ?
            """,
            (RetentionState.ACTIVE.value, normalized, limit),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            content=row["content"],
            source=MemorySourceReference(
                conversation_id=row["source_conversation_id"],
                message_id=row["source_message_id"],
                origin_device_id=row["origin_device_id"],
                note=row["source_note"],
            ),
            tags=_tags_from_column(row["tags"]),
            retention_state=RetentionState(row["retention_state"]),
            sync_version=row["sync_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
