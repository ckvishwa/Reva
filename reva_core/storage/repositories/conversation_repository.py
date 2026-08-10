"""Persistence for `conversations`. Insert-only in Phase 1A — no read
path exists yet because nothing needs to list/search conversations
until a real chat history view is built (Phase 1B+)."""

from __future__ import annotations

import sqlite3

from reva_core.shared.contracts.conversation import Conversation
from reva_core.shared.errors import StorageError


class ConversationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, conversation: Conversation) -> None:
        try:
            self._conn.execute(
                "INSERT INTO conversations "
                "(id, title, origin_device_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    conversation.id,
                    conversation.title,
                    conversation.origin_device_id,
                    conversation.created_at.isoformat(),
                    conversation.updated_at.isoformat(),
                ),
            )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to insert conversation {conversation.id}: {exc}") from exc
