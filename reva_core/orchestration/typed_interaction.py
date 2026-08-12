"""Typed interaction use case: the only orchestration Phase 1A adds.

Supports exactly three things: acknowledging a typed message (with an
optional `remember:` command), explicit memory creation, and exact/
keyword memory query — see docs/architecture/data-flow.md.

Durable memory is created only through `create_explicit_memory` (or the
`remember:` command routed to the same code path) — never inferred
from an ordinary typed message (ADR-006). This holds regardless of how
the reply itself is generated: Phase 1A's deterministic `LLMProvider`
echo, or (Slice 5, opt-in) an `AssistantOrchestrator` — e.g.
`AdkAssistantOrchestrator`, which may use a read-only memory *search*
tool internally, but has no tool capable of a write. See
docs/adr/ADR-017-google-adk-orchestration-dependency.md.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from reva_core.agent.orchestrator import AssistantOrchestrator
from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.memory.hybrid_retrieval import hybrid_search
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest
from reva_core.models.llm import LLMProvider, LLMRequest
from reva_core.shared.contracts.conversation import Conversation, Message, MessageRole
from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.errors import ProviderError, ValidationError
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger
from reva_core.shared.time import utc_now
from reva_core.storage.connection import transaction
from reva_core.storage.repositories.audit_repository import AuditRepository
from reva_core.storage.repositories.conversation_repository import ConversationRepository
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository
from reva_core.storage.repositories.message_repository import MessageRepository

logger = get_logger("orchestration.typed_interaction")

_REMEMBER_PREFIX = "remember:"
_UNAVAILABLE_REPLY = "Model reasoning is currently unavailable; your request was received."
_CONVERSATION_TITLE_MAX_LEN = 80


@dataclass(frozen=True)
class TypedMessageResult:
    conversation_id: str
    message_id: str
    memory_id: str | None
    reply: str


def _extract_remember_command(content: str) -> str | None:
    if not content.lower().startswith(_REMEMBER_PREFIX):
        return None
    remainder = content[len(_REMEMBER_PREFIX) :].strip()
    if not remainder:
        raise ValidationError("'remember:' command requires content after the prefix")
    return remainder


class TypedInteractionService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        origin_device_id: str,
        llm_provider: LLMProvider | None = None,
        orchestrator: AssistantOrchestrator | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_model_id: str = "",
        ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG,
    ) -> None:
        self._conn = conn
        self._origin_device_id = origin_device_id
        self._llm = llm_provider if llm_provider is not None else _default_llm_provider()
        self._orchestrator = orchestrator
        self._embedding_provider = embedding_provider
        self._embedding_model_id = embedding_model_id
        self._ranking_config = ranking_config
        self._conversations = ConversationRepository(conn)
        self._messages = MessageRepository(conn)
        self._memories = MemoryRepository(conn)
        self._memory_embeddings = MemoryEmbeddingRepository(conn)
        self._audit = AuditRepository(conn)

    async def handle_typed_message(self, content: str, correlation_id: str) -> TypedMessageResult:
        stripped = content.strip()
        if not stripped:
            raise ValidationError("typed message content must not be empty")

        remember_text = _extract_remember_command(stripped)
        now = utc_now()
        conversation = Conversation(
            id=new_id(),
            title=stripped[:_CONVERSATION_TITLE_MAX_LEN],
            origin_device_id=self._origin_device_id,
            created_at=now,
            updated_at=now,
        )
        message = Message(
            id=new_id(),
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=stripped,
            origin_device_id=self._origin_device_id,
            created_at=now,
        )

        memory_id: str | None = None
        with transaction(self._conn):
            self._conversations.insert(conversation)
            self._messages.insert(message)
            self._audit.insert(
                AuditEvent(
                    id=new_id(),
                    category=AuditEventCategory.SYSTEM,
                    action="typed_request_received",
                    outcome=AuditOutcome.SUCCESS,
                    correlation_id=correlation_id,
                    actor_device_id=self._origin_device_id,
                    metadata={
                        "content_length": len(stripped),
                        "conversation_id": conversation.id,
                        "message_id": message.id,
                    },
                    occurred_at=now,
                )
            )
            if remember_text is not None:
                memory = self._create_memory_row(
                    content=remember_text,
                    category=MemoryCategory.NOTE,
                    tags=(),
                    source=MemorySourceReference(
                        conversation_id=conversation.id,
                        message_id=message.id,
                        origin_device_id=self._origin_device_id,
                        note="remember_command",
                    ),
                    correlation_id=correlation_id,
                    now=now,
                )
                memory_id = memory.id

        # Deliberately outside the transaction: never hold a SQLite write
        # transaction open across an async provider/orchestrator call.
        try:
            if self._orchestrator is not None:
                assistant_response = await self._orchestrator.respond(
                    user_id=self._origin_device_id,
                    conversation_id=conversation.id,
                    message=stripped,
                    correlation_id=correlation_id,
                )
                reply = assistant_response.reply
            else:
                response = await self._llm.complete(
                    LLMRequest(prompt=stripped, correlation_id=correlation_id)
                )
                reply = response.content
        except ProviderError:
            reply = _UNAVAILABLE_REPLY

        if memory_id is not None:
            reply = f"{reply} Saved as a memory."

        return TypedMessageResult(
            conversation_id=conversation.id,
            message_id=message.id,
            memory_id=memory_id,
            reply=reply,
        )

    async def create_explicit_memory(
        self,
        content: str,
        category: MemoryCategory,
        tags: tuple[str, ...],
        correlation_id: str,
    ) -> Memory:
        stripped = content.strip()
        if not stripped:
            raise ValidationError("memory content must not be empty")

        now = utc_now()
        source = MemorySourceReference(
            origin_device_id=self._origin_device_id,
            note="explicit_api_memory_creation",
        )
        with transaction(self._conn):
            memory = self._create_memory_row(
                content=stripped,
                category=category,
                tags=tags,
                source=source,
                correlation_id=correlation_id,
                now=now,
            )

        # Deliberately outside the transaction: never hold a SQLite write
        # transaction open across an async provider call. Best-effort only
        # — a failure here must never affect the memory write above, which
        # has already committed. A memory that isn't embedded here is
        # naturally picked up by the next restart-safe backfill (it has no
        # memory_embeddings row for this model_id yet).
        if self._embedding_provider is not None:
            try:
                result = await self._embedding_provider.embed(
                    EmbeddingRequest(text=stripped, correlation_id=correlation_id)
                )
                self._memory_embeddings.upsert(memory.id, self._embedding_model_id, result.vector)
                logger.info(
                    "explicit memory embedded on write",
                    extra={"memory_id": memory.id, "model_id": self._embedding_model_id},
                )
            except Exception:
                logger.warning(
                    "failed to embed explicit memory on write; "
                    "will be picked up by the next backfill",
                    extra={"memory_id": memory.id, "model_id": self._embedding_model_id},
                    exc_info=True,
                )

        return memory

    async def query_memories(self, query: str, limit: int, correlation_id: str) -> list[Memory]:
        stripped = query.strip()
        if not stripped:
            raise ValidationError("memory query must not be empty")

        now = utc_now()
        self._audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.MEMORY,
                action="memory_query_requested",
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                actor_device_id=self._origin_device_id,
                metadata={"query_length": len(stripped), "limit": limit},
                occurred_at=now,
            )
        )
        if self._embedding_provider is not None:
            ranked = await hybrid_search(
                self._conn,
                self._embedding_provider,
                query=stripped,
                limit=limit,
                model_id=self._embedding_model_id,
                correlation_id=correlation_id,
                config=self._ranking_config,
            )
            results = [r.memory for r in ranked]
        else:
            results = self._memories.query(stripped, limit)
        self._audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.MEMORY,
                action="memory_query_completed",
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                actor_device_id=self._origin_device_id,
                metadata={"result_count": len(results)},
                occurred_at=utc_now(),
            )
        )
        return results

    def _create_memory_row(
        self,
        *,
        content: str,
        category: MemoryCategory,
        tags: tuple[str, ...],
        source: MemorySourceReference,
        correlation_id: str,
        now: datetime,
    ) -> Memory:
        """Caller must already hold an open transaction — this does not
        open its own (SQLite has no nested-transaction support here)."""
        memory = Memory(
            id=new_id(),
            category=category,
            content=content,
            source=source,
            tags=tags,
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
        self._audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.MEMORY,
                action="memory_create_requested",
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                actor_device_id=self._origin_device_id,
                metadata={
                    "category": category.value,
                    "content_length": len(content),
                    "tag_count": len(tags),
                },
                occurred_at=now,
            )
        )
        self._memories.insert(memory)
        self._audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.MEMORY,
                action="memory_created",
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                actor_device_id=self._origin_device_id,
                metadata={"memory_id": memory.id, "category": category.value},
                occurred_at=now,
            )
        )
        return memory


def _default_llm_provider() -> LLMProvider:
    # Imported lazily so that `reva_core.orchestration` never imports test
    # fixtures; the fake lives in production code specifically because
    # Phase 1A ships with no real provider at all (see module docstring).
    from reva_core.models.fakes import FakeLLMProvider

    return FakeLLMProvider()
