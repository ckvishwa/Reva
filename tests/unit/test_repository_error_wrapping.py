"""Every repository wraps a raw sqlite3.Error as StorageError instead of
letting it leak — proven here by closing the connection before the
write, the simplest reliable way to force a real sqlite3.Error."""

import pytest

from reva_core.shared.contracts.conversation import Conversation, Message, MessageRole
from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.conversation_repository import ConversationRepository
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.storage.repositories.message_repository import MessageRepository


def test_conversation_repository_wraps_sqlite_error(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    conn.close()
    repo = ConversationRepository(conn)
    now = utc_now()
    with pytest.raises(StorageError):
        repo.insert(
            Conversation(
                id=new_id(), title="x", origin_device_id=new_id(), created_at=now, updated_at=now
            )
        )


def test_message_repository_wraps_sqlite_error(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    conn.close()
    repo = MessageRepository(conn)
    with pytest.raises(StorageError):
        repo.insert(
            Message(
                id=new_id(),
                conversation_id=new_id(),
                role=MessageRole.USER,
                content="x",
                origin_device_id=new_id(),
                created_at=utc_now(),
            )
        )


def test_device_repository_wraps_sqlite_error(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    conn.execute("DROP TABLE devices")
    with pytest.raises(StorageError):
        DeviceRepository(conn).get_or_create_primary_device()


def test_memory_repository_wraps_sqlite_error(tmp_path):
    from reva_core.shared.contracts.memory import Memory, MemoryCategory, MemorySourceReference
    from reva_core.storage.repositories.memory_repository import MemoryRepository

    conn, _ = initialize_database(tmp_path / "reva.db")
    conn.close()
    repo = MemoryRepository(conn)
    now = utc_now()
    with pytest.raises(StorageError):
        repo.insert(
            Memory(
                id=new_id(),
                category=MemoryCategory.NOTE,
                content="x",
                source=MemorySourceReference(origin_device_id=new_id()),
                created_at=now,
                updated_at=now,
            )
        )
