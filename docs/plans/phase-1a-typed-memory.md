# Phase 1A — Typed Chat + Explicit Memory Vertical Slice

Status: IMPLEMENTED

## What this phase proved

> Authenticated typed interaction + explicit durable memory + SQLite
> persistence + source-aware retrieval + audit trail + restart recovery.

The full flow works end to end, exercised by
`tests/e2e/test_phase1a_typed_memory_vertical_slice.py`:

```text
start Core
-> authenticate local client (Bearer token)
-> submit typed "remember: ..." request or POST /v1/memories
-> memory saved in SQLite (memories table)
-> audit events saved (memory_create_requested, memory_created)
-> stop Core
-> restart Core (same database, same token file)
-> authenticate local client
-> query saved memory (GET /v1/memories?q=...)
-> correct memory returned with source reference
```

## What was added

- **Local authentication** (`reva_core/security/local_token.py`,
  `reva_core/api/auth.py`): a high-entropy token generated on first
  startup, stored as a plain file in the data directory (interim —
  DPAPI/Credential Manager is PLANNED, see
  `docs/security/security-invariants.md`), required on every `/v1/*`
  route via `Authorization: Bearer <token>`, constant-time compared.
- **A stable primary device ID** (`reva_core/storage/repositories/device_repository.py`):
  every message/memory/audit event needs a real `origin_device_id`;
  Phase 1A doesn't implement device pairing, so one device row is
  created once and reused, persisted via `application_metadata`.
- **Typed interaction contracts** (`reva_core/api/schemas.py`):
  `TypedRequest`/`TypedResponse`, `ExplicitMemoryCreateRequest`/`Response`,
  `MemoryQueryRequest`/`Response`, `ErrorResponse`, `AuditEventListResponse`.
- **`TypedInteractionService`** (`reva_core/orchestration/typed_interaction.py`):
  the only new orchestration use case — typed message acknowledgement
  (via the deterministic `FakeLLMProvider`, `reva_core/models/fakes.py` —
  **no real LLM provider exists**), explicit memory creation, and
  exact/keyword memory query. A `remember: <content>` prefix in a typed
  message routes to the same memory-creation code path as the dedicated
  endpoint — this is the *only* mechanism that infers a memory-worthy
  intent from a message, and it is a literal prefix match, not language
  understanding (ADR-006 still holds: no implicit/inferred memory).
- **Real repositories** for `conversations`, `messages`, `memories`
  (insert + query), on top of Phase 0's `devices`/`audit_events`.
- **Four new API routes**: `POST /v1/messages`, `POST /v1/memories`,
  `GET /v1/memories`, `GET /v1/audit-events` — all authenticated, all
  thin, no SQL/domain logic in the handlers.
- **Six new audit actions**: `typed_request_received`,
  `memory_create_requested`, `memory_created`, `memory_query_requested`,
  `memory_query_completed`, `authentication_failed`.

## Known limitations (intentional, in scope for later phases)

- Memory query is case-insensitive substring matching via SQL `LIKE`,
  ordered by `updated_at DESC, ROWID DESC` for a deterministic
  tiebreak — not semantic search, no tokenization/ranking. Semantic
  retrieval remains PLANNED.
- `GET /v1/audit-events` is limit-only ("most recent N"), not
  cursor-paginated — described as "bounded", not "paginated", to avoid
  overclaiming.
- No update/delete endpoints for memories — out of Phase 1A scope.
- No real LLM provider — every typed-message reply is either the
  deterministic `FakeLLMProvider`'s echo or, if a provider is injected
  that fails, a static "reasoning unavailable" message. Both paths are
  tested (`tests/unit/test_typed_interaction_service.py`).
- Local auth token has no rotation/expiry — first-boot-generated,
  stable until the token file is deleted.

## Open PRD tension carried over from Phase 0

`docs/testing/acceptance-matrix.md` still flags the active-window-context
requirement's phase mismatch between PRD §14 (listed as a V1 acceptance
test) and §15's roadmap (Phase 7). Not touched by Phase 1A; still
unresolved.
