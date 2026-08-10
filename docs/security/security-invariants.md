# Security Invariants

Each invariant states whether it is automatically enforced by a test
(through Phase 1A), or is a design commitment awaiting the feature that
would make it testable.

| # | Invariant | Enforcement (through Phase 1A) |
|---|---|---|
| 1 | Core is never publicly exposed in V1. | Enforced by #2 below — Core binds no interface it hasn't validated is loopback. |
| 2 | Network listeners bind only to loopback unless a future ADR changes this. | **Automated**: `load_settings()` raises `ConfigurationError` for non-loopback hosts. `tests/security/test_loopback_enforcement.py`. |
| 3 | Arbitrary shell execution is unsupported. | **Architectural**: no `subprocess`/`eval`/`exec` on untrusted input exists anywhere in the codebase (ADR-012). Not unit-testable as an absence; enforced by code review. |
| 4 | Destructive actions are unsupported. | **Architectural**: no destructive tool exists; `tools/` is unimplemented (PLANNED). Re-verify at Phase 3. |
| 5 | Tool execution cannot bypass policy. | **Design commitment**: `policy/` and `tools/` are both PLANNED (Phase 3); the contracts (`ToolRequest`, `ToolApprovalState`) already model the required chokepoint. Not testable until implemented. |
| 6 | Secrets never enter normal logs. | **Automated**: `tests/unit/test_logging_redaction.py` and `tests/security/test_token_not_leaked.py` prove `api_key`/`password`/`access_token`/`authorization`/etc. are redacted in log output, and that the local auth token never appears in a response body or a log line even on an auth failure. |
| 7 | Raw microphone audio is not persisted by default. | **Design commitment**: `voice/` is unimplemented (PLANNED, Phase 2); no audio-persistence code path exists to violate this yet. |
| 8 | Durable memory requires explicit user intent. | **Automated for the two Phase 1A entry points**: `POST /v1/memories` and the `remember:` prefix are the *only* code paths that write to `memories` (`tests/unit/test_typed_interaction_service.py`); ordinary typed messages never create memory. ADR-006 still applies to any future entry point. |
| 9 | External operations must be auditable. | **Automated**: `tests/integration/test_v1_audit_events_api.py` and `tests/integration/test_memory_audit_transaction.py` prove memory creation is always paired with `memory_create_requested`/`memory_created` audit events, atomically. Broader coverage (tool execution) arrives with Phase 3. |
| 10 | Secrets are separate from normal configuration. | **Automated**: `Settings.llm_provider_api_key` is `SecretStr` (`tests/unit/test_settings.py`); the local auth token lives in its own file, never in `Settings`/`.env` (`tests/unit/test_local_token.py`). |
| 11 | Untrusted paths cannot escape allowlisted boundaries. | **Design commitment**: no file-path tool exists yet (PLANNED, Phase 3); see threat model #8. |
| 12 | UI clients cannot call external service APIs directly. | **Architectural**: no client code exists in this repository yet (`desktop/`, `android/` are PLANNED); the API boundary design (ADR-007) is the intended chokepoint. |
| 13 | Providers cannot mutate durable user state. | **Architectural**: `models/` Protocols expose only request/response methods, no storage handle is passed to a provider; `tests/contract/test_provider_interfaces.py` proves the fakes only return data. `FakeLLMProvider`, now real runtime code, is held to the same rule. |
| 14 | Integrations cannot create durable memory without memory-policy approval. | **Design commitment**: no integrations exist yet (Phase 6+); see `future-expansion-policy.md`. |
| 15 | Persistence changes require migrations. | **Automated**: the only way to change schema is adding a file under `storage/migrations_sql/`, tracked in `schema_migrations`; `tests/integration/test_storage_bootstrap.py` and `tests/unit/test_migrations_runner.py` prove the migration path is the only path exercised. |
| 16 | Every domain (non-`/health`/`/version`) API route requires local authentication. | **Automated**: `tests/security/test_v1_auth_required.py` parametrizes all four `/v1/*` routes and asserts 401 without a valid `Authorization: Bearer <token>` header; `reva_core/api/auth.py::build_auth_dependency` is the single chokepoint every route depends on. |

## Local authentication model (new in Phase 1A)

- **Token generation**: a 256-bit random token (`secrets.token_urlsafe(32)`),
  generated once on first `CoreLifecycle.startup()`
  (`reva_core/security/local_token.py::ensure_local_token`).
- **Token storage (interim)**: a plain file at `<data_dir>/local_auth_token`,
  git-ignored, best-effort `chmod 600` (limited effect on Windows/NTFS —
  the real control is the containing directory's ACLs, same as
  `reva.db`). This is explicitly **not** the final posture.
- **Planned migration**: Windows Credential Manager / DPAPI-backed
  storage. Not implemented in Phase 1A because it isn't required to
  prove the vertical slice, and swapping the storage backend behind
  `ensure_local_token`'s existing signature is a contained change when
  it happens — no API/route code depends on *how* the token is stored.
- **Verification**: `hmac.compare_digest` (constant-time) against the
  `Authorization: Bearer <token>` header. A missing, malformed, or
  wrong token all produce the same generic 401 — the response never
  reveals which.
- **Failure auditing**: every failed attempt writes an
  `authentication_failed` audit event (path only, never the token or
  header value); if that write itself fails, the 401 is still returned
  — auth enforcement never depends on audit persistence succeeding
  (`tests/integration/test_v1_auth.py::test_auth_still_denies_when_failure_audit_write_itself_fails`).

## What "automated" means here

Automated invariants have a test that fails CI if the invariant
regresses. Design-commitment invariants describe a property of a
feature that does not exist yet in this codebase — they cannot be
falsely claimed as "passing" and are not marked as such anywhere in
`docs/testing/acceptance-matrix.md`.
