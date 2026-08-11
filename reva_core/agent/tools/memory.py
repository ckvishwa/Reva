"""`search_memory` — the only memory-facing tool RevaAgent has.

Read-only. Calls `MemoryRepository`/`AuditRepository` directly — the
same repository/audit boundary `TypedInteractionService.query_memories`
uses for the explicit Memory Search feature (same SQL, same audit
actions `memory_query_requested`/`memory_query_completed`). No SQLite
statement is written here beyond what `MemoryRepository` already
executes; this module never opens its own connection or database file.

There is deliberately no `remember`/`create_memory`/`update_memory`/
`delete_memory` tool anywhere in this package — ADR-006 requires every
durable memory write to be a distinct, explicit user action outside
the model's control, and the smallest way to guarantee that is to never
give the model a tool capable of it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.memory.hybrid_retrieval import hybrid_search
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.repositories.audit_repository import AuditRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_MAX_RESULTS = 10
_DEFAULT_RESULTS = 5


def _coerce_limit(limit: int | float | str) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return _DEFAULT_RESULTS
    return max(1, min(value, _MAX_RESULTS))


def build_search_memory_tool(
    conn: sqlite3.Connection,
    origin_device_id: str,
    correlation_id: str,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_model_id: str = "",
    ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Builds a `search_memory` tool bound to one request's connection,
    device, and correlation id. Built fresh per `respond()` call
    (cheap — no I/O) so the audit trail it produces ties back to the
    exact request that triggered it, without threading request-scoped
    state through ADK's session/tool-context machinery.
    """
    memories = MemoryRepository(conn)
    audit = AuditRepository(conn)

    async def search_memory(query: str, limit: int = _DEFAULT_RESULTS) -> dict[str, Any]:
        """Search the user's durable REVA memories for a text match.

        Use this when the user asks about something they previously told
        REVA to remember (e.g. "what did I ask you to remember about X",
        "what is my X"). This tool is READ-ONLY — it can never create,
        edit, or delete a memory. If it returns no results, say plainly
        that you have no matching memory; never guess or fabricate one.

        Args:
          query: Text to search for (matched both by keyword and meaning).
          limit: Maximum number of results to return.

        Returns:
          A dict with "status" ("success" or "error"). On success,
          "results" is a list of matching memory content strings, most
          relevant first. On error, "message" is a safe, user-showable
          explanation.
        """
        if not isinstance(query, str) or not query.strip():
            return {"status": "error", "message": "query must not be empty"}
        stripped = query.strip()
        bounded_limit = _coerce_limit(limit)
        now = utc_now()

        try:
            audit.insert(
                AuditEvent(
                    id=new_id(),
                    category=AuditEventCategory.MEMORY,
                    action="memory_query_requested",
                    outcome=AuditOutcome.SUCCESS,
                    correlation_id=correlation_id,
                    actor_device_id=origin_device_id,
                    metadata={
                        "query_length": len(stripped),
                        "limit": bounded_limit,
                        "invoked_by": "reva_agent",
                    },
                    occurred_at=now,
                )
            )
            if embedding_provider is not None:
                ranked = await hybrid_search(
                    conn,
                    embedding_provider,
                    query=stripped,
                    limit=bounded_limit,
                    model_id=embedding_model_id,
                    correlation_id=correlation_id,
                    config=ranking_config,
                )
                results = [r.memory for r in ranked]
            else:
                results = memories.query(stripped, bounded_limit)
        except Exception:
            audit.insert(
                AuditEvent(
                    id=new_id(),
                    category=AuditEventCategory.MEMORY,
                    action="memory_query_completed",
                    outcome=AuditOutcome.FAILURE,
                    correlation_id=correlation_id,
                    actor_device_id=origin_device_id,
                    metadata={"invoked_by": "reva_agent"},
                    occurred_at=utc_now(),
                )
            )
            return {"status": "error", "message": "memory search is temporarily unavailable"}

        audit.insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.MEMORY,
                action="memory_query_completed",
                outcome=AuditOutcome.SUCCESS,
                correlation_id=correlation_id,
                actor_device_id=origin_device_id,
                metadata={"result_count": len(results), "invoked_by": "reva_agent"},
                occurred_at=utc_now(),
            )
        )
        return {"status": "success", "results": [m.content for m in results]}

    return search_memory
