"""Persistence for `messages`. Insert-only in Phase 1A, same reasoning
as `conversation_repository.py`."""

from __future__ import annotations

import sqlite3

from reva_core.shared.contracts.conversation import Message
from reva_core.shared.errors import StorageError


class MessageRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, message: Message) -> None:
        try:
            self._conn.execute(
                "INSERT INTO messages "
                "(id, conversation_id, role, content, origin_device_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message.id,
                    message.conversation_id,
                    message.role.value,
                    message.content,
                    message.origin_device_id,
                    message.created_at.isoformat(),
                ),
            )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to insert message {message.id}: {exc}") from exc
