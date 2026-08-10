# Data Flow

## IMPLEMENTED

- **Core startup** — `python -m reva_core` loads typed config, configures
  structured logging, calls `CoreLifecycle.startup()`, which bootstraps
  SQLite (opens connection, applies migrations), ensures a primary
  device row exists, ensures the local auth token exists, and returns
  a `HealthStatus`.
- **Core shutdown** — `CoreLifecycle.shutdown()` closes the SQLite
  connection and logs a stop event.
- **Health check** — `GET /health` on the loopback-only FastAPI app
  returns the current `HealthStatus` (status, db schema version,
  started_at). `GET /version` returns the package version. Both
  unauthenticated (PRD-irrelevant, no sensitive data).
- **Typed chat (acknowledgement only, no real reasoning)** —
  `User types request → auth check → TypedInteractionService → conversation+message persisted → FakeLLMProvider (deterministic echo, or "unavailable" fallback on ProviderError) → response → audit event (typed_request_received)`.
  `POST /v1/messages`. No real LLM; every reply is documented as
  deterministic/vendor-free. Streaming, multi-turn context, and real
  reasoning remain PLANNED.
- **Explicit memory** —
  `POST /v1/memories { content, category, tags } → auth check → TypedInteractionService.create_explicit_memory → validated → persisted (single transaction with its audit events) → audit events (memory_create_requested, memory_created) → response`.
  Also reachable via a `remember: <content>` prefix inside
  `POST /v1/messages`, routed to the same code path — this is the only
  memory-inference mechanism, and it's a literal prefix match (ADR-006
  still holds: no language-model-inferred memory).
- **Memory retrieval (keyword/exact only, not semantic)** —
  `GET /v1/memories?q=... → auth check → TypedInteractionService.query_memories → SQL LIKE substring match, ordered by updated_at DESC → source-attributed results → audit events (memory_query_requested, memory_query_completed)`.
  Semantic retrieval remains PLANNED — see `docs/architecture/storage-design.md`.
- **Local authentication** —
  `Authorization: Bearer <token> → constant-time compare against CoreLifecycle.local_token → 401 + authentication_failed audit event on mismatch, or correlation ID passed through on success`.
  Token generated once at first startup (`reva_core/security/local_token.py`).
- **Audit trail read** —
  `GET /v1/audit-events → auth check → AuditRepository.list_recent(limit)`.
  Bounded (`limit`, default 50, max 200), not cursor-paginated.

## PLANNED

- **Real LLM reasoning** (Phase 1B+) — a real provider adapter behind
  the existing `LLMProvider` Protocol; `FakeLLMProvider` stays as the
  offline/unavailable fallback path, not replaced.
- **Voice request** (Phase 2) —
  `Push-to-talk → STT → request/retrieval → reasoning → TTS → audit event`
  (PRD §8.2). `STTProvider`/`TTSProvider` Protocols and fakes exist;
  `voice/` lifecycle coordination does not.
- **Tool request** (Phase 3) —
  `User asks for an action → orchestration → policy decision → tool execution → result + audit event`.
  `ToolRequest` contract exists; `policy/` and `tools/` do not.
- **Reminder** (Phase 3) —
  `Text/voice request → reminders/ schedules → notification dispatch (Windows/Android)`.
  `Reminder` contract exists; scheduling does not.
- **Android synchronization** (Phase 5) —
  `Local change → sync_events queue → authenticated transport → remote reconciliation`.
  `SyncEvent` contract exists; transport and reconciliation do not.
