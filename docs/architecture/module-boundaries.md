# Module Boundaries

Allowed dependency direction (top depends on bottom, never the reverse):

```text
UI/API
  ↓
Orchestration
  ↓
Domain semantics: memory, policy, reminders
  ↓
Ports and typed interfaces (models/ Protocols, repository interfaces)
  ↓
Storage, providers, and tools
```

Cross-cutting, reachable from any layer: `shared/` (contracts, ids,
time, errors, redaction, logging), `config/`, `audit/`, `security/`.

## Ownership table

| Module | Owns | Forbidden | Status (through Phase 1A) |
|---|---|---|---|
| `api/` | Transport translation, validation, serialization, auth boundary | SQL, domain rules, provider logic, policy decisions | IMPLEMENTED (`/health`, `/version`, `/v1/messages`, `/v1/memories`, `/v1/audit-events`) |
| `orchestration/` | Use-case coordination, Core lifecycle | SQL, vendor SDK calls, policy bypass | IMPLEMENTED (lifecycle + `TypedInteractionService`: typed-message ack, explicit memory create, keyword query) |
| `memory/` | Memory semantics, retention rules, retrieval coordination | SQLite queries, vector-provider implementation | PLANNED (Phase 1A implements the same behavior inline in `orchestration/typed_interaction.py` — narrow enough not to justify a separate module yet; revisit if it grows) |
| `storage/` | SQLite lifecycle, transactions, migrations, repositories | Deciding whether a memory should exist or an action is permitted | IMPLEMENTED (repositories: audit, device, conversation, message, memory) |
| `models/` | Provider contracts, provider result contracts, future adapters | Orchestration logic | IMPLEMENTED (Protocols; `FakeLLMProvider` is real Phase 1A runtime code, no real cloud adapters) |
| `security/` | Local Core API authentication token lifecycle | SQL, HTTP, domain logic | IMPLEMENTED (`security/local_token.py`) |
| `tools/` | Narrow allowlisted action implementations | Permission decisions | PLANNED (Phase 3) |
| `policy/` | Authorization, approval requirements, risk decisions | Sitting anywhere but between orchestration and tools | PLANNED (Phase 3) |
| `audit/` | Safe structured audit events | Passwords, keys, access tokens, pairing secrets, raw microphone data | IMPLEMENTED (6 Phase 1A audit actions, all persisted) |
| `voice/` | Voice lifecycle coordination | Direct vendor STT/TTS SDK calls | PLANNED (Phase 2) |
| `reminders/` | Reminder scheduling, notification dispatch coordination | — | PLANNED (Phase 3) |
| `sync/` | Future device sync semantics | — | PLANNED (Phase 5) |
| `shared/` | Contracts, IDs, time, errors, redaction, logging | Domain business logic | IMPLEMENTED |
| `config/` | Typed configuration, safe defaults, loopback enforcement | Secrets in plaintext, business logic | IMPLEMENTED |

**Note on `memory/`:** Phase 1A's explicit-memory create/query logic
lives directly in `TypedInteractionService` rather than a separate
`memory/` module. This was a deliberate scope call — the logic is
~60 lines and splitting it into its own module now would be
speculative structure ahead of a second consumer. If a second
orchestration use case needs the same memory semantics (e.g. a future
voice path), extract `memory/` at that point rather than before.

## Why `models/` is not domain contracts

`models/` is scoped narrowly to *provider* contracts (LLM/embedding/STT/TTS
request-response shapes and the Protocols providers implement). Domain
entities (`Conversation`, `Memory`, `Reminder`, `ToolRequest`,
`Permission`, `SyncEvent`) live in `shared/contracts/` because they are
referenced across multiple future modules (`memory/`, `policy/`,
`tools/`, `sync/`) — putting them in any one of those modules would
make the others depend on a module they must not own logic in.
`AuditEvent` is the one domain contract that lives outside
`shared/contracts/`, inside `audit/`, because the required module
boundaries explicitly assign audit record ownership to `audit/`.

## Circular dependency prevention

- `storage/` never imports `orchestration/`, `memory/`, `policy/`, or
  `api/`.
- `models/` never imports `orchestration/` or `storage/`.
- `audit/` imports `shared/` only; `storage/repositories/audit_repository.py`
  imports `audit/` (to know the contract) but `audit/` does not import
  `storage/` back — the dependency is one-directional.
- `shared/` imports nothing from any other `reva_core` subpackage.

This is enforced by convention and code review today; if the module
count grows, an import-linter rule set is the natural next step
(not adopted in Phase 0 — one more dependency for a problem that does
not exist yet at this size).
