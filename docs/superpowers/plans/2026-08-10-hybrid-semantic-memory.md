# Hybrid Semantic Memory Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Memory retrieval becomes hybrid lexical + semantic instead of depending primarily on keyword overlap, while preserving every existing invariant (owner isolation via per-instance SQLite, explicit-write-only, ADK read-only, restart persistence, audit events).

**Architecture:** A derived, rebuildable `memory_embeddings` table (never the source of truth — `memories` stays authoritative, per the existing contract docstring) stores one embedding per `(memory_id, model_id)`. A new `OllamaEmbeddingProvider` implements the existing (currently unused) `EmbeddingProvider` protocol against a local Ollama embedding model. A restart-safe backfill runs at `CoreLifecycle.startup()` and never blocks/crashes startup if the embedding backend is unreachable. A new `hybrid_retrieval` module combines lexical `LIKE` candidates with cosine-similarity semantic candidates using centralized, testable weights (0.70 semantic / 0.30 lexical by default), normalizes both to `[0,1]`, applies a minimum-confidence cutoff, and breaks ties deterministically. Both consumers of memory search — the explicit `GET /v1/memories` route and ADK's `search_memory` tool — call the same hybrid path, so C# and the model automatically benefit without either one calculating a score.

**Tech Stack:** Python 3.12, stdlib `sqlite3`/`struct`/`math` (no numpy — vector count stays small enough that pure-Python cosine similarity is fast), `httpx` (promoted from dev-only to a runtime dependency) for the Ollama HTTP call, pytest/pytest-asyncio (already configured `asyncio_mode = "auto"`).

## Global Constraints

- No vector database, no Pinecone/Weaviate/Qdrant/Elasticsearch. SQLite + pure-Python cosine comparison only.
- `Memory` (`reva_core/shared/contracts/memory.py`) stays the authoritative record; embeddings live only in a separate, rebuildable `memory_embeddings` table referencing `memories.id`.
- Ranking weights (`semantic_weight`, `lexical_weight`, `minimum_confidence`) live in exactly one place (`reva_core/memory/ranking.py`) — never inlined elsewhere.
- ADK's `search_memory` tool signature stays exactly `{query, limit}` — no owner-override parameter, no mutation tool ever added.
- Embedding-backend failure (Ollama unreachable, one record fails to embed) must never crash Core startup, corrupt `memories`, or block the explicit/ADK search paths — always degrade to lexical-only rather than error.
- No audit event may contain full memory content or a raw embedding vector — metadata stays counts/lengths only, matching the existing pattern.
- CI (`python -m reva_core` startup/shutdown smoke test) has no Ollama running — startup and the backfill it triggers must both complete quickly and successfully in that environment (empty `memories` table means zero embed calls regardless of Ollama's reachability; a non-empty table with Ollama down must still not fail startup).
- Do not touch `desktop/` in this plan — no C# ranking/embedding code is ever introduced (verified by Plan 1's constraints and this plan's Task 8 test).

---

## File Structure

New files:
- `reva_core/memory/__init__.py` (new package)
- `reva_core/memory/ranking.py` — `HybridRankingConfig`, `DEFAULT_HYBRID_RANKING_CONFIG`.
- `reva_core/memory/hybrid_retrieval.py` — `RankedMemory`, `cosine_similarity`, `hybrid_search`.
- `reva_core/memory/embedding_backfill.py` — `BackfillResult`, `backfill_missing_embeddings`.
- `reva_core/models/embedding_providers.py` — `OllamaEmbeddingProvider`.
- `reva_core/storage/repositories/memory_embedding_repository.py` — `MemoryEmbeddingRepository`.
- `reva_core/storage/migrations_sql/0002_memory_embeddings.sql`
- Tests: `tests/unit/test_ranking.py`, `tests/unit/test_memory_embedding_repository.py`, `tests/unit/test_hybrid_retrieval.py`, `tests/unit/test_ollama_embedding_provider.py`, `tests/integration/test_embedding_backfill.py`, `tests/integration/test_hybrid_semantic_cases.py`.

Modified files:
- `pyproject.toml` — add `httpx` to `dependencies`.
- `reva_core/config/settings.py` — add `embedding_model`, `embedding_model_api_base`, `embedding_timeout_seconds`.
- `reva_core/orchestration/lifecycle.py` — build embedding provider, run backfill, expose properties.
- `reva_core/orchestration/typed_interaction.py` — `query_memories` becomes `async`, hybrid-aware.
- `reva_core/api/routes.py` — `await` the now-async `query_memories`, pass embedding provider through.
- `reva_core/agent/tools/memory.py` — `search_memory` becomes `async`, hybrid-aware.
- `reva_core/agent/adk_orchestrator.py` — threads embedding provider/model id/ranking config through.
- `tests/unit/test_agent_tools.py` — update direct `search_memory(...)` call sites for the new async signature.

---

### Task 1: Centralized, testable ranking configuration

**Files:**
- Create: `reva_core/memory/__init__.py`
- Create: `reva_core/memory/ranking.py`
- Test: `tests/unit/test_ranking.py`

**Interfaces:**
- Produces: `HybridRankingConfig(semantic_weight: float, lexical_weight: float, minimum_confidence: float)` (frozen dataclass), `DEFAULT_HYBRID_RANKING_CONFIG: HybridRankingConfig`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ranking.py
"""Ranking weights must live in exactly one place and be testable in
isolation — see docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md."""

from __future__ import annotations

import pytest

from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig


def test_default_config_documents_seventy_thirty_split():
    assert DEFAULT_HYBRID_RANKING_CONFIG.semantic_weight == pytest.approx(0.70)
    assert DEFAULT_HYBRID_RANKING_CONFIG.lexical_weight == pytest.approx(0.30)


def test_default_config_weights_sum_to_one():
    total = (
        DEFAULT_HYBRID_RANKING_CONFIG.semantic_weight + DEFAULT_HYBRID_RANKING_CONFIG.lexical_weight
    )
    assert total == pytest.approx(1.0)


def test_config_is_frozen():
    with pytest.raises(AttributeError):
        DEFAULT_HYBRID_RANKING_CONFIG.semantic_weight = 0.5  # type: ignore[misc]


def test_custom_config_is_constructible_for_tests():
    custom = HybridRankingConfig(semantic_weight=0.5, lexical_weight=0.5, minimum_confidence=0.1)

    assert custom.semantic_weight == 0.5
    assert custom.minimum_confidence == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ranking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reva_core.memory'`.

- [ ] **Step 3: Write minimal implementation**

```python
# reva_core/memory/__init__.py
"""Hybrid lexical + semantic memory retrieval — ranking, embeddings, backfill.

Separate from reva_core/storage/repositories/memory_repository.py (raw
persistence) and reva_core/agent/tools/memory.py (the ADK-facing tool):
this package owns only the scoring/combination logic both of those call
into, so the weighting lives in exactly one place.
"""

from __future__ import annotations
```

```python
# reva_core/memory/ranking.py
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


DEFAULT_HYBRID_RANKING_CONFIG = HybridRankingConfig(
    semantic_weight=0.70,
    lexical_weight=0.30,
    minimum_confidence=0.20,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ranking.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add reva_core/memory/__init__.py reva_core/memory/ranking.py tests/unit/test_ranking.py
git commit -m "feat(core): add centralized hybrid ranking configuration"
```

---

### Task 2: `memory_embeddings` schema and repository

**Files:**
- Create: `reva_core/storage/migrations_sql/0002_memory_embeddings.sql`
- Create: `reva_core/storage/repositories/memory_embedding_repository.py`
- Test: `tests/unit/test_memory_embedding_repository.py`

**Interfaces:**
- Produces: `MemoryEmbeddingRepository(conn)` with `upsert(memory_id: str, model_id: str, vector: tuple[float, ...]) -> None`, `get(memory_id: str, model_id: str) -> tuple[float, ...] | None`, `all_for_model(model_id: str) -> list[tuple[str, tuple[float, ...]]]` (skips/logs corrupt rows instead of raising), `missing_for_model(model_id: str, batch_size: int) -> list[tuple[str, str]]` (returns `(memory_id, content)` pairs for active memories with no row for `model_id`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_memory_embedding_repository.py
"""MemoryEmbeddingRepository: a derived, rebuildable index over `memories`
— see reva_core/shared/contracts/memory.py's module docstring for why
this is a separate table, never a column on `memories` itself."""

from __future__ import annotations

import struct

import pytest

from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository


@pytest.fixture
def store(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    yield conn
    conn.close()


def _insert_memory(conn, content: str) -> str:
    now = utc_now()
    memory_id = new_id()
    MemoryRepository(conn).insert(
        Memory(
            id=memory_id,
            category=MemoryCategory.NOTE,
            content=content,
            source=MemorySourceReference(origin_device_id=new_id(), note="test"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    return memory_id


def test_upsert_and_get_roundtrip(store):
    memory_id = _insert_memory(store, "I have a pet cat.")
    repo = MemoryEmbeddingRepository(store)

    repo.upsert(memory_id, "test-model", (0.1, 0.2, 0.3))

    assert repo.get(memory_id, "test-model") == pytest.approx((0.1, 0.2, 0.3))


def test_get_returns_none_when_missing(store):
    memory_id = _insert_memory(store, "no embedding yet")
    repo = MemoryEmbeddingRepository(store)

    assert repo.get(memory_id, "test-model") is None


def test_upsert_is_idempotent_per_memory_and_model(store):
    memory_id = _insert_memory(store, "overwrite me")
    repo = MemoryEmbeddingRepository(store)

    repo.upsert(memory_id, "test-model", (1.0, 0.0))
    repo.upsert(memory_id, "test-model", (0.0, 1.0))

    assert repo.get(memory_id, "test-model") == pytest.approx((0.0, 1.0))
    assert len(repo.all_for_model("test-model")) == 1


def test_missing_for_model_returns_only_unembedded_active_memories(store):
    embedded_id = _insert_memory(store, "already embedded")
    unembedded_id = _insert_memory(store, "not embedded yet")
    repo = MemoryEmbeddingRepository(store)
    repo.upsert(embedded_id, "test-model", (0.1,))

    pending = repo.missing_for_model("test-model", batch_size=100)

    pending_ids = {memory_id for memory_id, _content in pending}
    assert pending_ids == {unembedded_id}


def test_missing_for_model_respects_batch_size(store):
    for i in range(5):
        _insert_memory(store, f"memory {i}")
    repo = MemoryEmbeddingRepository(store)

    pending = repo.missing_for_model("test-model", batch_size=2)

    assert len(pending) == 2


def test_all_for_model_skips_corrupt_rows_without_raising(store):
    memory_id = _insert_memory(store, "will be corrupted")
    repo = MemoryEmbeddingRepository(store)
    repo.upsert(memory_id, "test-model", (0.1, 0.2, 0.3))
    # Simulate corruption: overwrite the BLOB with a length that doesn't
    # divide evenly into float32 records.
    store.execute(
        "UPDATE memory_embeddings SET vector = ? WHERE memory_id = ? AND model_id = ?",
        (b"\x01\x02\x03", memory_id, "test-model"),
    )

    result = repo.all_for_model("test-model")

    assert result == []


def test_different_models_are_independent(store):
    memory_id = _insert_memory(store, "multi-model memory")
    repo = MemoryEmbeddingRepository(store)

    repo.upsert(memory_id, "model-a", (1.0, 0.0))
    repo.upsert(memory_id, "model-b", (0.0, 1.0))

    assert repo.get(memory_id, "model-a") == pytest.approx((1.0, 0.0))
    assert repo.get(memory_id, "model-b") == pytest.approx((0.0, 1.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_embedding_repository.py -v`
Expected: FAIL — migration/module do not exist.

- [ ] **Step 3: Write minimal implementation**

```sql
-- reva_core/storage/migrations_sql/0002_memory_embeddings.sql
-- Migration 0002: derived, rebuildable semantic-embedding index.
--
-- `memories` remains the sole authoritative record (see
-- reva_core/shared/contracts/memory.py's module docstring). This table
-- only ever references memories.id; nothing else may reference this
-- table, so it can always be safely dropped and rebuilt via backfill.
BEGIN;

CREATE TABLE memory_embeddings (
    memory_id   TEXT NOT NULL REFERENCES memories(id),
    model_id    TEXT NOT NULL,
    dims        INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (memory_id, model_id)
);
CREATE INDEX idx_memory_embeddings_model_id ON memory_embeddings(model_id);

COMMIT;
```

```python
# reva_core/storage/repositories/memory_embedding_repository.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_memory_embedding_repository.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Verify migration restart-idempotency against the existing bootstrap test pattern**

Run: `pytest tests/integration/test_storage_bootstrap.py -v`
Expected: PASS unchanged — `apply_migrations` already treats `0002_memory_embeddings.sql` like any other migration file; no code change needed there, this step is a regression check.

- [ ] **Step 6: Commit**

```bash
git add reva_core/storage/migrations_sql/0002_memory_embeddings.sql reva_core/storage/repositories/memory_embedding_repository.py tests/unit/test_memory_embedding_repository.py
git commit -m "feat(core): add memory_embeddings schema and repository"
```

---

### Task 3: Cosine similarity and hybrid ranking algorithm

**Files:**
- Create: `reva_core/memory/hybrid_retrieval.py`
- Test: `tests/unit/test_hybrid_retrieval.py`

**Interfaces:**
- Consumes: `MemoryRepository.query` (existing), `MemoryEmbeddingRepository.all_for_model` (Task 2), `EmbeddingProvider.embed` (existing protocol, `reva_core/models/embedding.py`), `HybridRankingConfig` (Task 1).
- Produces:
  ```python
  @dataclass(frozen=True)
  class RankedMemory:
      memory: Memory
      hybrid_score: float
      semantic_score: float
      lexical_score: float


  async def hybrid_search(
      conn: sqlite3.Connection,
      embedding_provider: EmbeddingProvider | None,
      *,
      query: str,
      limit: int,
      model_id: str,
      correlation_id: str,
      config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG,
  ) -> list[RankedMemory]: ...


  def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float: ...
  ```

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_hybrid_retrieval.py
"""Hybrid ranking: lexical LIKE candidates + semantic cosine candidates,
normalized to [0,1], combined with centralized weights, minimum-confidence
filtered, deterministically tie-broken. Uses a deterministic
DeterministicEmbeddingProvider (below) instead of real Ollama — the real
model's semantic behavior is proven in
tests/integration/test_hybrid_semantic_cases.py (Task 7) and the
Ollama-backed evaluation in docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md.
"""

from __future__ import annotations

import pytest

from reva_core.memory.hybrid_retrieval import cosine_similarity, hybrid_search
from reva_core.memory.ranking import HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_CID = "33333333-3333-3333-3333-333333333333"
_MODEL = "test-model"


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Maps known text substrings to hand-picked vectors so semantic
    relationships are provable without a real embedding model."""

    def __init__(
        self, vectors_by_keyword: dict[str, tuple[float, ...]], default: tuple[float, ...]
    ) -> None:
        self._vectors_by_keyword = vectors_by_keyword
        self._default = default

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        lowered = request.text.lower()
        for keyword, vector in self._vectors_by_keyword.items():
            if keyword in lowered:
                return EmbeddingResult(vector=vector, correlation_id=request.correlation_id)
        return EmbeddingResult(vector=self._default, correlation_id=request.correlation_id)


class FailingEmbeddingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise RuntimeError("embedding backend unreachable")


@pytest.fixture
def store(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    yield conn
    conn.close()


def _insert_memory(conn, content: str) -> Memory:
    now = utc_now()
    memory = Memory(
        id=new_id(),
        category=MemoryCategory.NOTE,
        content=content,
        source=MemorySourceReference(origin_device_id=new_id(), note="test"),
        tags=(),
        retention_state=RetentionState.ACTIVE,
        sync_version=1,
        created_at=now,
        updated_at=now,
    )
    MemoryRepository(conn).insert(memory)
    return memory


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors_is_negative_one():
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_is_zero_not_nan():
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) == 0.0


async def test_semantic_match_ranks_first_with_no_keyword_overlap(store):
    cat_memory = _insert_memory(store, "I have a pet cat.")
    _insert_memory(store, "unrelated distractor about databases")
    embeddings = MemoryEmbeddingRepository(store)
    provider = DeterministicEmbeddingProvider(
        vectors_by_keyword={"cat": (1.0, 0.0), "animal": (1.0, 0.0), "database": (0.0, 1.0)},
        default=(0.0, 0.5),
    )
    for content, memory in [("I have a pet cat.", cat_memory)]:
        embeddings.upsert(memory.id, _MODEL, (1.0, 0.0))

    results = await hybrid_search(
        store,
        provider,
        query="What animal do I own?",
        limit=5,
        model_id=_MODEL,
        correlation_id=_CID,
    )

    assert results
    assert results[0].memory.id == cat_memory.id


async def test_lexical_exact_match_still_surfaces(store):
    memory = _insert_memory(store, "REVA uses Push-To-Talk")
    embeddings = MemoryEmbeddingRepository(store)
    embeddings.upsert(memory.id, _MODEL, (0.0, 0.0))
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 1.0))

    results = await hybrid_search(
        store, provider, query="push-to-talk", limit=5, model_id=_MODEL, correlation_id=_CID
    )

    assert any(r.memory.id == memory.id for r in results)


async def test_below_minimum_confidence_excluded(store):
    _insert_memory(store, "completely unrelated content about spreadsheets")
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 0.0))
    config = HybridRankingConfig(semantic_weight=0.70, lexical_weight=0.30, minimum_confidence=0.99)

    results = await hybrid_search(
        store,
        provider,
        query="banana bread recipe",
        limit=5,
        model_id=_MODEL,
        correlation_id=_CID,
        config=config,
    )

    assert results == []


async def test_tie_break_is_deterministic_across_repeated_calls(store):
    first = _insert_memory(store, "tie candidate alpha")
    second = _insert_memory(store, "tie candidate beta")
    embeddings = MemoryEmbeddingRepository(store)
    embeddings.upsert(first.id, _MODEL, (1.0, 0.0))
    embeddings.upsert(second.id, _MODEL, (1.0, 0.0))
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 0.0))

    results_a = await hybrid_search(
        store, provider, query="tie candidate", limit=5, model_id=_MODEL, correlation_id=_CID
    )
    results_b = await hybrid_search(
        store, provider, query="tie candidate", limit=5, model_id=_MODEL, correlation_id=_CID
    )

    assert [r.memory.id for r in results_a] == [r.memory.id for r in results_b]


async def test_embedding_provider_failure_falls_back_to_lexical_only(store):
    memory = _insert_memory(store, "fallback lexical match content")
    provider = FailingEmbeddingProvider()

    results = await hybrid_search(
        store,
        provider,
        query="fallback lexical match",
        limit=5,
        model_id=_MODEL,
        correlation_id=_CID,
    )

    assert any(r.memory.id == memory.id for r in results)


async def test_none_embedding_provider_uses_lexical_only(store):
    memory = _insert_memory(store, "no provider configured content")

    results = await hybrid_search(
        store, None, query="no provider configured", limit=5, model_id=_MODEL, correlation_id=_CID
    )

    assert any(r.memory.id == memory.id for r in results)


async def test_limit_is_respected(store):
    for i in range(10):
        m = _insert_memory(store, f"bounded candidate {i}")
        MemoryEmbeddingRepository(store).upsert(m.id, _MODEL, (1.0, 0.0))
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 0.0))

    results = await hybrid_search(
        store, provider, query="bounded candidate", limit=3, model_id=_MODEL, correlation_id=_CID
    )

    assert len(results) <= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_hybrid_retrieval.py -v`
Expected: FAIL — `reva_core.memory.hybrid_retrieval` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
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
  drop hybrid < minimum_confidence, sort, deterministic tie-break

Never raises on embedding-backend failure: a failed query embedding
degrades to lexical-only ranking rather than failing the whole search
(this is what keeps GET /v1/memories and search_memory working when
Ollama is down after startup).
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest
from reva_core.shared.contracts.memory import Memory
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
            embedded = await embedding_provider.embed(
                EmbeddingRequest(text=query, correlation_id=correlation_id)
            )
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
        rows = conn.execute(
            f"SELECT * FROM memories WHERE id IN ({','.join('?' for _ in missing_ids)})",
            tuple(missing_ids),
        ).fetchall()
        for row in rows:
            memory = MemoryRepository._row_to_memory(row)  # noqa: SLF001 - same-package reuse, not a public API break
            memories_by_id[memory.id] = memory

    ranked: list[RankedMemory] = []
    for memory_id in candidate_ids:
        memory = memories_by_id.get(memory_id)
        if memory is None:
            continue
        lexical_score = (
            (lexical_count - lexical_rank[memory_id]) / lexical_count
            if memory_id in lexical_rank
            else 0.0
        )
        semantic_score = semantic_scores.get(memory_id, 0.0)
        hybrid_score = (
            config.semantic_weight * semantic_score + config.lexical_weight * lexical_score
        )
        if hybrid_score < config.minimum_confidence:
            continue
        ranked.append(
            RankedMemory(
                memory=memory,
                hybrid_score=hybrid_score,
                semantic_score=semantic_score,
                lexical_score=lexical_score,
            )
        )

    ranked.sort(key=lambda r: (-r.hybrid_score, -r.memory.updated_at.timestamp(), r.memory.id))
    return ranked[:limit]
```

Note: `MemoryRepository._row_to_memory` is a `@staticmethod` already defined on that class (`reva_core/storage/repositories/memory_repository.py:80-97`) — reusing it here avoids duplicating row-to-`Memory` mapping logic; add `# noqa: SLF001` since `ruff`'s `S`/private-access rules would otherwise flag the leading underscore across the module boundary (same package, deliberate reuse, not accidental coupling).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_hybrid_retrieval.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Run ruff and mypy**

Run: `ruff check reva_core/memory/ && mypy reva_core`
Expected: no errors. If `ruff` flags the `_row_to_memory` access differently than anticipated, adjust the `noqa` code to whatever `ruff` actually reports rather than guessing further codes.

- [ ] **Step 6: Commit**

```bash
git add reva_core/memory/hybrid_retrieval.py tests/unit/test_hybrid_retrieval.py
git commit -m "feat(core): add hybrid lexical+semantic memory ranking"
```

---

### Task 4: `OllamaEmbeddingProvider`

**Files:**
- Create: `reva_core/models/embedding_providers.py`
- Test: `tests/unit/test_ollama_embedding_provider.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `OllamaEmbeddingProvider(model: str, api_base: str, timeout_seconds: float = 30.0, client: httpx.AsyncClient | None = None)` implementing `EmbeddingProvider.embed`.

- [ ] **Step 1: Add `httpx` as a runtime dependency**

Modify `pyproject.toml` — move `httpx` from the `dev` optional group into `dependencies` (it stays listed once, under `dependencies`; remove the line from `dev`):

```toml
dependencies = [
    "pydantic>=2.7,<3",
    "pydantic-settings>=2.3,<3",
    "fastapi>=0.111,<1",
    "uvicorn>=0.30,<1",
    "httpx>=0.27,<1",
    "google-adk==2.6.3",
    "litellm==1.96.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2,<9",
    "pytest-asyncio>=0.23,<1",
    "pytest-cov>=5.0,<6",
    "ruff>=0.5,<1",
    "mypy>=1.10,<2",
    "pre-commit>=3.7,<4",
]
```

Run: `pip install -e ".[dev]"`
Expected: succeeds (httpx was already installed transitively/as a dev dep, so this is a metadata move, not a new download).

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_ollama_embedding_provider.py
"""OllamaEmbeddingProvider: local-first embedding backend, no cloud
credential. Uses httpx.MockTransport — no real Ollama server required
for this test; a real-Ollama integration path is exercised only by
docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md's evaluation,
which is explicitly not part of CI."""

from __future__ import annotations

import httpx
import pytest

from reva_core.models.embedding import EmbeddingRequest
from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.shared.errors import ProviderError, ProviderErrorKind

_CID = "44444444-4444-4444-4444-444444444444"


def _client_with_transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_embed_returns_vector_from_ollama_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embeddings"
        body = request.read()
        assert b"nomic-embed-text" in body
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    result = await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert result.vector == pytest.approx((0.1, 0.2, 0.3))
    assert result.correlation_id == _CID


async def test_embed_raises_provider_error_on_connection_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.UNAVAILABLE


async def test_embed_raises_provider_error_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model not found"})

    provider = OllamaEmbeddingProvider(
        model="missing-model",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.INVALID_RESPONSE


async def test_embed_raises_provider_error_on_malformed_json_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.INVALID_RESPONSE


async def test_embed_raises_provider_error_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.TIMEOUT
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_ollama_embedding_provider.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 4: Write minimal implementation**

```python
# reva_core/models/embedding_providers.py
"""Real EmbeddingProvider implementations.

OllamaEmbeddingProvider is the local-first default: same Ollama server
REVA already requires for ADK chat (ollama_chat/llama3.1:8b), reached
via its /api/embeddings HTTP endpoint. No new heavy dependency (no
torch/sentence-transformers) — an embedding model like nomic-embed-text
is a small (~270MB) CPU-friendly Ollama pull, appropriate for the
4GB-VRAM local hardware this runs on.

Vendor exceptions never leak past this module (see
reva_core/shared/errors.py's module docstring) — every httpx failure
mode is normalized into ProviderError with an explicit kind.
"""

from __future__ import annotations

import httpx

from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.shared.errors import ProviderError, ProviderErrorKind

_EMBEDDINGS_PATH = "/api/embeddings"


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        model: str,
        api_base: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(
                f"{self._api_base}{_EMBEDDINGS_PATH}",
                json={"model": self._model, "prompt": request.text},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "Embedding request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "Embedding backend is unreachable."
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()

        if response.status_code != 200:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                f"Embedding backend returned status {response.status_code}.",
            )

        try:
            payload = response.json()
            vector = payload["embedding"]
            if not isinstance(vector, list) or not vector:
                raise ValueError("empty or non-list embedding")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                "Embedding backend returned an unparseable response.",
            ) from exc

        return EmbeddingResult(
            vector=tuple(float(v) for v in vector), correlation_id=request.correlation_id
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_ollama_embedding_provider.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run ruff and mypy**

Run: `ruff check reva_core/models/embedding_providers.py && mypy reva_core`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml reva_core/models/embedding_providers.py tests/unit/test_ollama_embedding_provider.py
git commit -m "feat(core): add Ollama-backed EmbeddingProvider"
```

---

### Task 5: Restart-safe backfill

**Files:**
- Create: `reva_core/memory/embedding_backfill.py`
- Test: `tests/integration/test_embedding_backfill.py`

**Interfaces:**
- Consumes: `MemoryEmbeddingRepository` (Task 2), `EmbeddingProvider` (existing protocol).
- Produces: `BackfillResult(embedded_count: int, failed_count: int, failed_memory_ids: tuple[str, ...])`, `async def backfill_missing_embeddings(conn, embedding_provider, *, model_id, correlation_id, batch_size=100) -> BackfillResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_embedding_backfill.py
"""Restart-safe embedding backfill: existing memories without embeddings
stay readable/searchable; backfill converges to zero pending on rerun;
one failing record never corrupts the rest."""

from __future__ import annotations

import pytest

from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_CID = "55555555-5555-5555-5555-555555555555"
_MODEL = "test-model"


class SucceedingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(vector=(0.1, 0.2), correlation_id=request.correlation_id)


class FailOnKeywordProvider(EmbeddingProvider):
    def __init__(self, failing_keyword: str) -> None:
        self._failing_keyword = failing_keyword

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        if self._failing_keyword in request.text:
            raise RuntimeError("simulated embedding failure")
        return EmbeddingResult(vector=(0.1, 0.2), correlation_id=request.correlation_id)


@pytest.fixture
def store(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    yield conn
    conn.close()


def _insert_memory(conn, content: str) -> str:
    now = utc_now()
    memory_id = new_id()
    MemoryRepository(conn).insert(
        Memory(
            id=memory_id,
            category=MemoryCategory.NOTE,
            content=content,
            source=MemorySourceReference(origin_device_id=new_id(), note="test"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    return memory_id


async def test_backfill_embeds_all_missing_memories(store):
    ids = [_insert_memory(store, f"memory {i}") for i in range(3)]

    result = await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    assert result.embedded_count == 3
    assert result.failed_count == 0
    embeddings = MemoryEmbeddingRepository(store)
    for memory_id in ids:
        assert embeddings.get(memory_id, _MODEL) is not None


async def test_backfill_is_idempotent_on_rerun(store):
    _insert_memory(store, "already backfilled")
    await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    second_result = await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    assert second_result.embedded_count == 0


async def test_backfill_skips_failing_record_without_stopping_the_rest(store):
    good_id = _insert_memory(store, "good memory")
    bad_id = _insert_memory(store, "BOOM memory")
    other_good_id = _insert_memory(store, "another good memory")
    provider = FailOnKeywordProvider(failing_keyword="BOOM")

    result = await backfill_missing_embeddings(
        store, provider, model_id=_MODEL, correlation_id=_CID
    )

    assert result.embedded_count == 2
    assert result.failed_count == 1
    assert result.failed_memory_ids == (bad_id,)
    embeddings = MemoryEmbeddingRepository(store)
    assert embeddings.get(good_id, _MODEL) is not None
    assert embeddings.get(other_good_id, _MODEL) is not None
    assert embeddings.get(bad_id, _MODEL) is None


async def test_backfill_does_not_delete_or_alter_source_memory_on_failure(store):
    bad_id = _insert_memory(store, "BOOM memory")
    provider = FailOnKeywordProvider(failing_keyword="BOOM")

    await backfill_missing_embeddings(store, provider, model_id=_MODEL, correlation_id=_CID)

    memory = MemoryRepository(store).query("BOOM", 10)
    assert len(memory) == 1
    assert memory[0].id == bad_id


async def test_backfill_with_zero_pending_memories_is_a_safe_noop(store):
    result = await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    assert result.embedded_count == 0
    assert result.failed_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_embedding_backfill.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# reva_core/memory/embedding_backfill.py
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
    failed_ids: list[str] = []

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
                logger.warning(
                    "failed to embed memory during backfill",
                    extra={"memory_id": memory_id},
                    exc_info=True,
                )
                failed_ids.append(memory_id)

        if not progressed:
            # Every remaining pending record failed this pass — stop
            # instead of looping forever re-attempting the same failures.
            break

    return BackfillResult(
        embedded_count=embedded_count,
        failed_count=len(failed_ids),
        failed_memory_ids=tuple(failed_ids),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_embedding_backfill.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add reva_core/memory/embedding_backfill.py tests/integration/test_embedding_backfill.py
git commit -m "feat(core): add restart-safe embedding backfill"
```

---

### Task 6: Wire embedding provider and backfill into `CoreLifecycle`

**Files:**
- Modify: `reva_core/config/settings.py`
- Modify: `reva_core/orchestration/lifecycle.py`
- Modify: `tests/integration/test_core_lifecycle.py`

**Interfaces:**
- Produces (additions to `Settings`): `embedding_model: str = "nomic-embed-text"`, `embedding_model_api_base: str = "http://127.0.0.1:11434"`, `embedding_timeout_seconds: float = 30.0`.
- Produces (additions to `CoreLifecycle`): `embedding_provider: EmbeddingProvider | None` property, `embedding_model_id: str` property, `ranking_config: HybridRankingConfig` property.

- [ ] **Step 1: Read the current lifecycle test file to match its fixture style**

Run: `cat tests/integration/test_core_lifecycle.py` (or open it) — match its existing `Settings`/`CoreLifecycle` construction pattern (likely a `tmp_path`-based `data_dir` and `load_settings(data_dir=...)`) before writing new tests, so new tests use the same fixture idiom rather than inventing a second one.

- [ ] **Step 2: Write the failing tests**

Add to `tests/integration/test_core_lifecycle.py`:

```python
def test_startup_builds_embedding_provider(tmp_path):
    from reva_core.models.embedding_providers import OllamaEmbeddingProvider

    settings = load_settings(data_dir=tmp_path / "data")
    lifecycle = CoreLifecycle(settings)

    lifecycle.startup()

    assert isinstance(lifecycle.embedding_provider, OllamaEmbeddingProvider)
    assert lifecycle.embedding_model_id == settings.embedding_model
    lifecycle.shutdown()


def test_startup_succeeds_even_when_embedding_backend_is_unreachable(tmp_path, monkeypatch):
    """Ollama is never running in CI. Startup with a non-empty memories
    table and an unreachable embedding backend must still reach HEALTHY —
    this is the core CI-safety guarantee for this slice."""
    from reva_core.shared.contracts.health import CoreStatus
    from reva_core.shared.contracts.memory import (
        Memory,
        MemoryCategory,
        MemorySourceReference,
        RetentionState,
    )
    from reva_core.shared.ids import new_id
    from reva_core.shared.time import utc_now
    from reva_core.storage.bootstrap import initialize_database
    from reva_core.storage.repositories.memory_repository import MemoryRepository

    data_dir = tmp_path / "data"
    conn, _ = initialize_database(data_dir / "reva.db")
    now = utc_now()
    MemoryRepository(conn).insert(
        Memory(
            id=new_id(),
            category=MemoryCategory.NOTE,
            content="pre-existing memory",
            source=MemorySourceReference(origin_device_id=new_id(), note="test"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    conn.close()

    settings = load_settings(data_dir=data_dir, embedding_model_api_base="http://127.0.0.1:1")
    lifecycle = CoreLifecycle(settings)

    health = lifecycle.startup()

    assert health.status == CoreStatus.HEALTHY
    lifecycle.shutdown()


def test_startup_with_empty_memories_table_does_not_require_embedding_backend(tmp_path):
    from reva_core.shared.contracts.health import CoreStatus

    settings = load_settings(
        data_dir=tmp_path / "data", embedding_model_api_base="http://127.0.0.1:1"
    )
    lifecycle = CoreLifecycle(settings)

    health = lifecycle.startup()

    assert health.status == CoreStatus.HEALTHY
    lifecycle.shutdown()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/integration/test_core_lifecycle.py -v -k embedding`
Expected: FAIL — `lifecycle.embedding_provider` does not exist.

- [ ] **Step 4: Extend `Settings`**

Modify `reva_core/config/settings.py` — add after `adk_timeout_seconds` (line 48):

```python
    # Local-first embedding backend for hybrid semantic memory retrieval
    # (Slice 6). Same Ollama server the "adk" orchestrator path already
    # requires — see reva_core/models/embedding_providers.py.
    embedding_model: str = "nomic-embed-text"
    embedding_model_api_base: str = "http://127.0.0.1:11434"
    embedding_timeout_seconds: float = 30.0
```

- [ ] **Step 5: Extend `CoreLifecycle`**

Modify `reva_core/orchestration/lifecycle.py`. Add imports:

```python
from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider
from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.shared.ids import new_id
```

Add to `__init__` (after `self._assistant_orchestrator: AssistantOrchestrator | None = None`):

```python
        self._embedding_provider: EmbeddingProvider | None = None
        self._ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG
```

Modify `startup()` — insert after the `self._local_token = ensure_local_token(...)` line and before the `if self._settings.assistant_orchestrator == "adk":` block:

```python
        self._embedding_provider = OllamaEmbeddingProvider(
            model=self._settings.embedding_model,
            api_base=self._settings.embedding_model_api_base,
            timeout_seconds=self._settings.embedding_timeout_seconds,
        )
        self._run_startup_backfill()
```

Add a private helper method (any position after `startup`, before `shutdown`):

```python
    def _run_startup_backfill(self) -> None:
        # asyncio.run is safe here: startup() runs before uvicorn creates
        # its own event loop. Any failure (Ollama unreachable, a single
        # record failing to embed) must never prevent Core from becoming
        # HEALTHY — this is a best-effort warm-up, not a startup
        # precondition. An empty memories table (the common CI case)
        # embeds zero records regardless of backend reachability.
        import asyncio

        assert self._embedding_provider is not None
        assert self._conn is not None
        try:
            result = asyncio.run(
                backfill_missing_embeddings(
                    self._conn,
                    self._embedding_provider,
                    model_id=self._settings.embedding_model,
                    correlation_id=new_id(),
                )
            )
            logger.info(
                "embedding backfill completed",
                extra={"embedded_count": result.embedded_count, "failed_count": result.failed_count},
            )
        except Exception:
            logger.warning("embedding backfill failed at startup; continuing without it", exc_info=True)
```

Add properties (near the existing `assistant_orchestrator` property):

```python
@property
def embedding_provider(self) -> EmbeddingProvider | None:
    return self._embedding_provider


@property
def embedding_model_id(self) -> str:
    return self._settings.embedding_model


@property
def ranking_config(self) -> HybridRankingConfig:
    return self._ranking_config
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/integration/test_core_lifecycle.py -v`
Expected: PASS, all tests including the 3 new ones. `test_startup_succeeds_even_when_embedding_backend_is_unreachable` must complete quickly (`http://127.0.0.1:1` is a fast-failing connection refusal, not a hanging timeout).

- [ ] **Step 7: Run the CI-equivalent startup/shutdown smoke test locally**

Run: `python -m reva_core` (with `REVA_DATA_DIR` set to a scratch temp dir, `Ctrl+C` after it logs healthy, or reuse whatever the existing CI step in `.github/workflows/ci.yml` line ~55-58 actually invokes)
Expected: starts and shuts down cleanly with no Ollama running — confirms this task didn't regress the CI smoke test.

- [ ] **Step 8: Commit**

```bash
git add reva_core/config/settings.py reva_core/orchestration/lifecycle.py tests/integration/test_core_lifecycle.py
git commit -m "feat(core): build embedding provider and run backfill at Core startup"
```

---

### Task 7: Hybrid retrieval on both consumers — explicit search and ADK `search_memory`

**Files:**
- Modify: `reva_core/orchestration/typed_interaction.py`
- Modify: `reva_core/api/routes.py`
- Modify: `reva_core/agent/tools/memory.py`
- Modify: `reva_core/agent/adk_orchestrator.py`
- Modify: `tests/unit/test_agent_tools.py`
- Test: `tests/integration/test_hybrid_semantic_cases.py`

**Interfaces:**
- `TypedInteractionService.__init__` gains `embedding_provider: EmbeddingProvider | None = None, embedding_model_id: str = "", ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG`.
- `TypedInteractionService.query_memories` becomes `async def query_memories(self, query: str, limit: int, correlation_id: str) -> list[Memory]`.
- `build_search_memory_tool` gains `embedding_provider: EmbeddingProvider | None = None, embedding_model_id: str = "", ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG`; the returned `search_memory` callable becomes `async def search_memory(query: str, limit: int = 5) -> dict[str, Any]` (signature parameter names unchanged — `{"query", "limit"}` — only sync-vs-async changes).

This is the task that proves spec section 4's semantic behaviors (CASE 1-5 + negative case) end-to-end through the real service/tool boundary, using the same `DeterministicEmbeddingProvider` pattern as Task 3 (fast, network-free — the real-Ollama-backed proof lives in the Plan 3 evaluation).

- [ ] **Step 1: Write the failing integration test for spec section 4's cases**

```python
# tests/integration/test_hybrid_semantic_cases.py
"""Proves docs/superpowers/plans WORK-ORDER section 4's required semantic
behaviors through TypedInteractionService.query_memories — the same path
GET /v1/memories uses. Deterministic embeddings (not real Ollama) keep
this fast and CI-safe; see the Plan 3 evaluation for real-model numbers."""

from __future__ import annotations

import pytest

from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.shared.contracts.memory import MemoryCategory
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.device_repository import DeviceRepository

_CID = "66666666-6666-6666-6666-666666666666"
_MODEL = "test-model"


class TopicEmbeddingProvider(EmbeddingProvider):
    """Assigns each known topic a distinct axis so cosine similarity
    reflects the intended semantic relationship deterministically."""

    _TOPICS = ["cat", "night", "sdet", "iphone", "maltrace", "recipe"]

    def _vector_for(self, text: str) -> tuple[float, ...]:
        lowered = text.lower()
        vector = [0.0] * len(self._TOPICS)
        matched = False
        for i, topic in enumerate(self._TOPICS):
            if topic in lowered:
                vector[i] = 1.0
                matched = True
        if not matched:
            vector = [0.05] * len(self._TOPICS)
        return tuple(vector)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            vector=self._vector_for(request.text), correlation_id=request.correlation_id
        )


@pytest.fixture
def service(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    svc = TypedInteractionService(
        conn,
        device_id,
        embedding_provider=TopicEmbeddingProvider(),
        embedding_model_id=_MODEL,
    )
    yield svc, conn, device_id
    conn.close()


async def _remember(service, content: str) -> None:
    svc, conn, _ = service
    memory = svc.create_explicit_memory(content, MemoryCategory.NOTE, (), _CID)
    from reva_core.memory.embedding_backfill import backfill_missing_embeddings

    await backfill_missing_embeddings(
        conn, TopicEmbeddingProvider(), model_id=_MODEL, correlation_id=_CID
    )
    return memory


async def test_case_1_pet_cat(service):
    await _remember(service, "I have a pet cat.")
    svc, _, _ = service

    results = await svc.query_memories("What animal do I own?", 5, _CID)

    assert results and "cat" in results[0].content.lower()


async def test_case_2_works_late_at_night(service):
    await _remember(service, "I prefer working late at night.")
    svc, _, _ = service

    results = await svc.query_memories("When do I usually like doing focused work?", 5, _CID)

    assert results and "night" in results[0].content.lower()


async def test_case_3_sdet_career_target(service):
    await _remember(service, "My main career target is SDET.")
    svc, _, _ = service

    results = await svc.query_memories("What kind of testing job am I targeting?", 5, _CID)

    assert results and "sdet" in results[0].content.lower()


async def test_case_4_iphone_daily_driver(service):
    await _remember(service, "I use an iPhone 12 as my main phone.")
    svc, _, _ = service

    results = await svc.query_memories("Which handset is my daily driver?", 5, _CID)

    assert results and "iphone" in results[0].content.lower()


async def test_case_5_maltrace_project(service):
    await _remember(service, "I built MalTrace to analyze malware behavior.")
    svc, _, _ = service

    results = await svc.query_memories("Which project did I make for malware analysis?", 5, _CID)

    assert results and "maltrace" in results[0].content.lower()


async def test_negative_case_no_confident_match(service):
    await _remember(service, "I have a pet cat.")
    await _remember(service, "My main career target is SDET.")
    svc, _, _ = service

    results = await svc.query_memories("best recipe for banana bread", 5, _CID)

    assert not any("cat" in r.content.lower() or "sdet" in r.content.lower() for r in results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_hybrid_semantic_cases.py -v`
Expected: FAIL — `TypedInteractionService.__init__` doesn't accept `embedding_provider`, and `query_memories` is not awaitable.

- [ ] **Step 3: Update `TypedInteractionService`**

Modify `reva_core/orchestration/typed_interaction.py`. Add imports:

```python
from reva_core.memory.hybrid_retrieval import hybrid_search
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider
```

Modify `__init__` (lines 65-79) to add two parameters and store them:

```python
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
        self._audit = AuditRepository(conn)
```

Replace `query_memories` (lines 196-227):

```python
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
```

- [ ] **Step 4: Update `routes.py` to await the now-async call and pass the provider through**

Modify `reva_core/api/routes.py`. Update `_service()` (lines 45-50):

```python
    def _service() -> TypedInteractionService:
        return TypedInteractionService(
            lifecycle.connection,
            lifecycle.primary_device_id,
            orchestrator=lifecycle.assistant_orchestrator,
            embedding_provider=lifecycle.embedding_provider,
            embedding_model_id=lifecycle.embedding_model_id,
            ranking_config=lifecycle.ranking_config,
        )
```

Update `get_memories` (line 98):

```python
        memories = await _service().query_memories(
            query_request.query, query_request.limit, header_correlation_id
        )
```

- [ ] **Step 5: Update `build_search_memory_tool` to be hybrid-aware and async**

Modify `reva_core/agent/tools/memory.py`. Add imports:

```python
from reva_core.memory.hybrid_retrieval import hybrid_search
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider
```

Modify `build_search_memory_tool`'s signature and inner function (lines 41-126):

```python
def build_search_memory_tool(
    conn: sqlite3.Connection,
    origin_device_id: str,
    correlation_id: str,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_model_id: str = "",
    ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG,
) -> Callable[..., dict[str, Any]]:
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
```

- [ ] **Step 6: Thread the provider through `AdkAssistantOrchestrator`**

Modify `reva_core/agent/adk_orchestrator.py`. Add imports:

```python
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider
```

Modify `AdkAssistantOrchestrator.__init__` (lines 55-71) to accept and store the three new optional parameters:

```python
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        origin_device_id: str,
        model: str | BaseLlm,
        session_service: BaseSessionService | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_model_id: str = "",
        ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG,
    ) -> None:
        self._conn = conn
        self._origin_device_id = origin_device_id
        self._model = model
        self._session_service = session_service or InMemorySessionService()  # type: ignore[no-untyped-call]
        self._timeout_seconds = timeout_seconds
        self._embedding_provider = embedding_provider
        self._embedding_model_id = embedding_model_id
        self._ranking_config = ranking_config
```

Modify the `search_memory = build_search_memory_tool(...)` call inside `respond()` (line 95):

```python
search_memory = build_search_memory_tool(
    self._conn,
    user_id,
    correlation_id,
    embedding_provider=self._embedding_provider,
    embedding_model_id=self._embedding_model_id,
    ranking_config=self._ranking_config,
)
```

Modify `build_adk_orchestrator` (lines 190-212) to accept and forward the same three parameters:

```python
def build_adk_orchestrator(
    *,
    conn: sqlite3.Connection,
    origin_device_id: str,
    model_name: str,
    model_api_base: str,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_model_id: str = "",
    ranking_config: HybridRankingConfig = DEFAULT_HYBRID_RANKING_CONFIG,
) -> AdkAssistantOrchestrator:
    from google.adk.models.lite_llm import LiteLlm

    model = LiteLlm(model=model_name, api_base=model_api_base)
    return AdkAssistantOrchestrator(
        conn=conn,
        origin_device_id=origin_device_id,
        model=model,
        timeout_seconds=timeout_seconds,
        embedding_provider=embedding_provider,
        embedding_model_id=embedding_model_id,
        ranking_config=ranking_config,
    )
```

Modify `reva_core/orchestration/lifecycle.py`'s `startup()` call site of `build_adk_orchestrator` (added in Task 6, originally lines 48-54 of the pre-Task-6 file) to pass the three new arguments:

```python
            self._assistant_orchestrator = build_adk_orchestrator(
                conn=self._conn,
                origin_device_id=self._primary_device_id,
                model_name=self._settings.adk_model,
                model_api_base=self._settings.adk_model_api_base,
                timeout_seconds=self._settings.adk_timeout_seconds,
                embedding_provider=self._embedding_provider,
                embedding_model_id=self._settings.embedding_model,
                ranking_config=self._ranking_config,
            )
```

- [ ] **Step 7: Update existing direct `search_memory(...)` call sites in `test_agent_tools.py` for the new async signature**

`search_memory` is now `async def` unconditionally (even with `embedding_provider=None`), so every direct call must be awaited. `pyproject.toml`'s `asyncio_mode = "auto"` means changing a test function to `async def` is sufficient — no `@pytest.mark.asyncio` needed. Modify `tests/unit/test_agent_tools.py`:

Change these 7 test function signatures from `def test_...(store...)` to `async def test_...(store...)`, and their `search_memory(...)` call sites from `result = search_memory(...)` to `result = await search_memory(...)`:
`test_search_memory_returns_matching_content`, `test_search_memory_case_insensitive_and_trims_query`, `test_search_memory_limit_is_bounded_to_max`, `test_search_memory_zero_results_returns_empty_success`, `test_search_memory_invalid_query_rejected_without_touching_repository`, `test_search_memory_non_numeric_limit_falls_back_to_default_without_crashing`, `test_search_memory_repository_exception_handled_safely`.

Leave `test_search_memory_has_no_owner_override_parameter` as a plain `def` — `inspect.signature(search_memory)` works identically on an `async def` callable and does not need to call/await it.

Leave `test_get_current_time_returns_utc_iso8601`, `test_agent_module_never_opens_or_queries_sqlite_directly`, and `test_reva_agent_exposes_exactly_search_and_time_tools_no_mutation` unchanged — none of them call `search_memory` directly.

- [ ] **Step 8: Run the full affected test suite**

Run: `pytest tests/unit/test_agent_tools.py tests/unit/test_adk_orchestrator.py tests/integration/test_v1_memories_api.py tests/integration/test_hybrid_semantic_cases.py -v`
Expected: PASS. `test_v1_memories_api.py` needs no source edits — `TestClient`'s async route handling already awaits `get_memories` correctly; this run just confirms no regression. If `google-adk==2.6.3`'s automatic function-tool wrapping does not invoke `async def search_memory` correctly, `test_adk_orchestrator.py::test_memory_question_invokes_search_memory_and_answers_correctly` fails here — that is the real, first signal of an ADK async-tool incompatibility and should be debugged via `superpowers:systematic-debugging` before continuing, not worked around by reverting to sync.

- [ ] **Step 9: Run full Python suite, ruff, mypy**

Run: `ruff format --check . && ruff check . && mypy reva_core && pytest`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add reva_core/orchestration/typed_interaction.py reva_core/api/routes.py reva_core/agent/tools/memory.py reva_core/agent/adk_orchestrator.py reva_core/orchestration/lifecycle.py tests/unit/test_agent_tools.py tests/integration/test_hybrid_semantic_cases.py
git commit -m "feat(core): route explicit and ADK memory search through hybrid retrieval"
```

---

### Task 8: Security/invariant regression tests

**Files:**
- Modify: `tests/unit/test_agent_tools.py` (verify existing invariant tests still pass unmodified in spirit)
- Test: `tests/security/test_hybrid_retrieval_invariants.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.

- [ ] **Step 1: Write the failing tests**

```python
# tests/security/test_hybrid_retrieval_invariants.py
"""Invariants hybrid retrieval must not weaken: no owner-override
parameter on search_memory, no memory-mutation tool, audit metadata
never carries full content or raw vectors, C# never appears as a
consumer of ranking/embedding code (verified by absence of any such
import path — the real enforcement is architectural: reva_core has no
knowledge of desktop/ at all)."""

from __future__ import annotations

import inspect

from reva_core.agent.reva_agent import build_reva_agent
from reva_core.agent.tools.memory import build_search_memory_tool
from reva_core.agent.tools.system import get_current_time
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.audit_repository import AuditRepository
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_CID = "77777777-7777-7777-7777-777777777777"


def test_search_memory_still_exposes_only_query_and_limit(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    search_memory = build_search_memory_tool(conn, device_id, _CID, embedding_provider=None)

    params = set(inspect.signature(search_memory).parameters)

    assert params == {"query", "limit"}
    conn.close()


def test_agent_still_exposes_exactly_two_read_only_tools(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    search_memory = build_search_memory_tool(conn, device_id, _CID)
    agent = build_reva_agent(model="unused-in-this-test", tools=[search_memory, get_current_time])

    tool_names = {tool.__name__ for tool in agent.tools}

    assert tool_names == {"search_memory", "get_current_time"}
    assert tool_names.isdisjoint({"remember", "create_memory", "update_memory", "delete_memory"})
    conn.close()


async def test_query_audit_metadata_never_contains_memory_content(tmp_path):
    from reva_core.shared.contracts.memory import (
        Memory,
        MemoryCategory,
        MemorySourceReference,
        RetentionState,
    )
    from reva_core.shared.ids import new_id
    from reva_core.shared.time import utc_now

    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    now = utc_now()
    secret_content = "a very specific secret memory content string"
    MemoryRepository(conn).insert(
        Memory(
            id=new_id(),
            category=MemoryCategory.NOTE,
            content=secret_content,
            source=MemorySourceReference(origin_device_id=device_id, note="test"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    search_memory = build_search_memory_tool(conn, device_id, _CID)

    await search_memory(query="secret memory")

    events = AuditRepository(conn).list_recent(50)
    for event in events:
        assert secret_content not in str(event.metadata)
    conn.close()


def test_reva_core_package_has_no_reference_to_desktop_directory():
    """Architectural check, not a runtime one: reva_core/ must never
    import or reference the C# desktop project — ranking/embedding logic
    living only in Python is enforced by there being no code path for it
    to leak through, not by convention alone."""
    import pathlib

    reva_core_dir = pathlib.Path(__file__).resolve().parents[2] / "reva_core"
    for path in reva_core_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Reva.Desktop" not in text
        assert "desktop\\" not in text and "desktop/" not in text
```

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `pytest tests/security/test_hybrid_retrieval_invariants.py -v`
Expected: these should PASS immediately if Tasks 1-7 were implemented correctly (this task is a regression/invariant proof, not new production code) — if any fails, it indicates Task 7 broke an invariant and must be fixed there, not by weakening this test.

- [ ] **Step 3: Run the full Python suite one more time**

Run: `ruff format --check . && ruff check . && mypy reva_core && pytest`
Expected: all green — this is the same command set CI's `python` job runs (`.github/workflows/ci.yml`).

- [ ] **Step 4: Commit**

```bash
git add tests/security/test_hybrid_retrieval_invariants.py
git commit -m "test(core): add hybrid retrieval security/invariant regression tests"
```

---

## Self-Review Notes (already applied above)

- Spec coverage: `EmbeddingProvider` boundary used for real (Task 4), no vector DB (Task 3 uses stdlib only), derived/rebuildable embedding table (Task 2), restart-safe idempotent backfill that never corrupts storage on a single failure (Task 5), centralized/testable weights with normalization and deterministic tie-breaking and minimum-confidence no-match handling (Tasks 1 & 3), both consumers (explicit route + ADK tool) upgraded (Task 7), owner isolation preserved via existing per-instance-SQLite architecture (documented in Task 8, no new per-row owner column introduced — matches "no user accounts... in this slice"), ADK stays read-only / no mutation tool / no owner-override parameter (Task 8), audit never carries memory content (Task 8), explicit-writes-only and no-implicit-memory-creation are untouched by this plan (no code path in Tasks 1-8 writes to `memories`, only to `memory_embeddings`).
- Section 4's 5 semantic cases + negative case: Task 7 Step 1 tests all six directly, matching the spec's exact wording.
- No placeholders: every step has literal code or literal file diffs.
- Type consistency checked: `HybridRankingConfig`, `RankedMemory`, `BackfillResult`, `MemoryEmbeddingRepository` method names/signatures are identical everywhere they're referenced across Tasks 1-8.
- Out of scope for this plan (covered by docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md instead): the 500+ memory corpus, Recall@k/latency benchmarking, the Desktop Memory Panel manual demo, and the automatic-startup / full-semantic-ADK real E2E tests.
