# Test Strategy

## Categories and what's in each (through Phase 1A)

- **Unit** (`tests/unit/`) — config loading and defaults, UUIDv7
  generation, UTC datetime validation, contract shape/serialization,
  error hierarchy, log redaction, migration-runner error handling,
  package import smoke, local auth token lifecycle, correlation ID
  resolution, API schema validation (empty/oversized/tag-bounds
  rejection), `TypedInteractionService` semantics (remember: parsing,
  query normalization/ordering/bounded limit, ProviderError fallback),
  the `transaction()` context manager's commit/rollback behavior,
  repository-level `StorageError` wrapping.
- **Integration** (`tests/integration/`) — SQLite bootstrap (WAL,
  foreign keys, migrations, idempotent restart), audit event round trip
  through real SQLite, `CoreLifecycle` startup/shutdown (including the
  local token and primary device ID becoming available after startup
  and stable across restart), the FastAPI `/health`/`/version`
  boundary, `python -m reva_core` smoke test, every `/v1/*` route
  exercised through a real `TestClient` against a real tmp_path SQLite
  database (auth, memory create/query, typed messages, audit-events
  listing), and the memory-creation-plus-audit-event transactional
  integrity test.
- **Contract** (`tests/contract/`) — every domain Pydantic contract and
  every Phase 1A API schema round-trips through JSON with
  `schema_version` intact and rejects invalid enum/naive-datetime
  input; every provider fake satisfies its `Protocol`; a failing fake
  proves `ProviderError` normalization.
- **Security** (`tests/security/`) — loopback-only host enforcement,
  log redaction, API exposes no unexpected routes (including no
  tool/action/execute/command-named route) and returns 404 (not a
  stack trace) for unknown paths, every `/v1/*` route rejects missing/
  invalid auth, the local token never appears in a response body or
  log line even on failure, SQL-injection-shaped memory content is
  stored as inert literal text, and both `StorageError` and an
  unexpected exception produce the same safe generic 500 body.
- **E2E** (`tests/e2e/`) — exactly one test:
  `test_phase1a_typed_memory_vertical_slice.py`, the scenario this
  phase exists to prove (bootstrap → authenticate → save memory →
  audit event → restart → authenticate → query → source-attributed
  result). No UI, voice, Android, or cloud E2E exists — see below.

## What is still not tested, and why

- No UI tests (Playwright or otherwise) — no UI exists. Building an
  E2E harness for a UI that isn't there produces a test that always
  either skips or tests nothing real.
- No voice/STT/TTS behavioral tests beyond Protocol conformance — no
  real provider exists; the fakes are for contract shape, not audio
  quality or latency.
- No policy/tool execution tests — `policy/` and `tools/` do not exist
  yet; a test asserting "policy blocks X" with no policy engine would
  be testing nothing. `tests/security/test_no_tool_endpoint.py` instead
  tests the negative: that no such surface has been added.
- No real-LLM-provider tests — no real adapter exists; `FakeLLMProvider`
  and the `ProviderError` fallback path are both tested directly.

## Running tests (Windows PowerShell)

See `docs/development/testing.md` for exact commands.

## Meaningful vs. decorative tests

Every test in this repository asserts a specific, falsifiable behavior
against real implementation code (SQLite via `tmp_path`, real Pydantic
validation, a real FastAPI `TestClient`) — no test mocks the thing it
is meant to verify. Where a feature does not exist, its test does not
exist either; the acceptance matrix marks it `NOT STARTED` or
`PLANNED` instead of a passing placeholder.
