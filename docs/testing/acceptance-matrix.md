# Acceptance Matrix

Maps every PRD §14 acceptance test to target phase, test type, status,
and notes. Allowed status values: `NOT STARTED`, `PLANNED`,
`IMPLEMENTED`, `PASSING`, `BLOCKED`. Nothing below is marked `PASSING`
unless an actual test in this repository exercises it end-to-end for
that requirement.

| # | Requirement (PRD §14) | Target phase | Test type | Test ID | Status | Notes |
|---|---|---|---|---|---|---|
| 1 | Typed request → streamed text response | Phase 1 | E2E | `tests/integration/test_v1_messages_api.py::test_typed_message_returns_deterministic_ack` | IMPLEMENTED | `POST /v1/messages` returns a real, tested response — but non-streaming, and via `FakeLLMProvider` (deterministic echo), not a real LLM. Not marked PASSING because the PRD wording specifically says "streamed"; streaming + a real provider remain PLANNED (Phase 1B+). |
| 2 | Push-to-talk → transcription, text+speech, interrupt | Phase 2 | E2E | — | NOT STARTED | `voice/` unimplemented; `STTProvider`/`TTSProvider` fakes exist for future contract use. |
| 3 | Explicit save memory + retrieve with source | Phase 1 | E2E | `tests/e2e/test_phase1a_typed_memory_vertical_slice.py` | PASSING | Full vertical slice: authenticated create → SQLite persistence → audit events → Core restart → authenticated query → correct content + source reference, all against a real database. |
| 4 | Edit, delete, export memories | Phase 1 | E2E | — | NOT STARTED | Explicitly out of Phase 1A scope; only create + query exist. |
| 5 | Create reminder via text or voice | Phase 3 | E2E | — | NOT STARTED | `Reminder` contract exists; no scheduling logic. |
| 6 | Windows-created reminder notifies on Android | Phase 4/5 | E2E | — | NOT STARTED | Depends on Android app and sync transport, neither exists. |
| 7 | Open approved app/file/folder/URL with confirmation | Phase 3 | E2E | — | NOT STARTED | `tools/`, `policy/` unimplemented. |
| 8 | Every executed/denied/failed tool action appears in activity history | Phase 3 | Integration | `tests/integration/test_v1_audit_events_api.py`, `tests/integration/test_memory_audit_transaction.py` | PLANNED | The audit mechanism itself is now proven twice over — a full contract→SQLite→API round trip, and atomicity with the action it records — for memory actions. Tool-specific audit events do not exist because `tools/` does not exist; the same pattern is expected to extend cleanly in Phase 3. |
| 9 | Memory syncs between paired devices while online | Phase 5 | E2E | — | NOT STARTED | `sync/` unimplemented. |
| 10 | Offline changes reconcile on reconnection | Phase 5 | E2E | — | NOT STARTED | |
| 11 | Memory conflict preserved and surfaced, not overwritten | Phase 5 | Integration/E2E | — | NOT STARTED | `SyncEvent.entity_version` field exists to support this later. |
| 12 | No consequential external operation without approval; unsupported in V1 | All phases (architectural) | Security | `tests/security/test_no_tool_endpoint.py` | NOT STARTED | Now backed by a real (if narrow) test: no route matching tool/action/execute/command exists, and the four `/v1/*` routes are enumerated exhaustively. Still not a tested *approval gate* — there is no consequential action to gate yet. Re-verify meaningfully once Phase 3 policy/tools exist. |
| 13 | Raw microphone audio not stored by default | Phase 2 | Security | — | NOT STARTED | Vacuously true — no audio capture code exists yet. Same caveat as #12. |
| 14 | Active-window context disabled by default, toggle visible | Phase 7 per roadmap §15; listed as a V1 test in §14 | Security/UI | — | NOT STARTED | **PRD internal tension**, carried over from Phase 0, unresolved: §14 lists this as a V1 acceptance test but §15's roadmap places "opt-in Windows context" in Phase 7. Target-phase column follows the roadmap. |
| 15 | Offline: browse/search local memory/history, create local reminder | Phase 1/3 | E2E | — | NOT STARTED | The underlying capability — memory query with zero network dependency — is now real (`GET /v1/memories` never calls a provider), but no UI or "offline" condition is actually exercised; reminder creation is still absent. |
| 16 | Cloud provider failure reported honestly, no false completion claim | Phase 1+ | Unit | `tests/unit/test_typed_interaction_service.py::test_handle_typed_message_falls_back_when_provider_unavailable` | PASSING | `TypedInteractionService` catches `ProviderError` and returns "Model reasoning is currently unavailable; your request was received." — never a false success claim — and, separately, confirms a `remember:` command still saves the memory even when the provider is down. |
| 17 | Restart preserves confirmed local data and unsynced queue | Phase 1 (data)/5 (queue) | Integration/E2E | `tests/e2e/test_phase1a_typed_memory_vertical_slice.py`, `tests/integration/test_core_lifecycle.py::test_primary_device_id_stable_across_restart` | PASSING (data-preservation portion only) | Now proven at the application level (a real memory, created through the API, survives a full Core restart), not just the raw-SQLite level. The "unsynced queue" portion is still NOT STARTED — no queue exists. |
| 18 | Unpair Android, future sync stops | Phase 5 | E2E | — | NOT STARTED | |

## Infrastructure proofs (not PRD acceptance tests, but load-bearing for the above)

| Property | Test ID | Status |
|---|---|---|
| New DB → migrations apply → expected schema version | `tests/integration/test_storage_bootstrap.py::test_initialize_database_creates_expected_schema` | PASSING |
| Restart → migrations remain idempotently applied | `tests/integration/test_storage_bootstrap.py::test_restart_is_idempotent` | PASSING |
| WAL mode enabled | `tests/integration/test_storage_bootstrap.py::test_initialize_database_enables_wal_mode` | PASSING |
| Foreign keys enforced | `tests/integration/test_storage_bootstrap.py::test_foreign_keys_are_enforced_not_just_enabled` | PASSING |
| Core startup/shutdown smoke | `tests/integration/test_main_smoke.py` | PASSING |
| Loopback-only enforcement | `tests/security/test_loopback_enforcement.py` | PASSING |
| Secret redaction in logs | `tests/unit/test_logging_redaction.py` | PASSING |
| Audit event rejects secret metadata | `tests/unit/test_audit_events.py::test_audit_event_rejects_api_key_in_metadata` | PASSING |
| Every `/v1/*` route requires local authentication | `tests/security/test_v1_auth_required.py` | PASSING |
| Local auth token is stable across restart, never logged/returned | `tests/security/test_token_not_leaked.py`, `tests/e2e/test_phase1a_typed_memory_vertical_slice.py` | PASSING |
| Memory row + its audit events commit or roll back together | `tests/integration/test_memory_audit_transaction.py` | PASSING |
| Memory content containing SQL-injection-shaped text is inert | `tests/security/test_memory_input_injection_safety.py` | PASSING |
| Every error response (401/400/404/500) is stack-trace-free and path-free | `tests/security/test_no_stack_trace_leak.py` | PASSING |
