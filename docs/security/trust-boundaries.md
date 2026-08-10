# Trust Boundaries

```text
┌─────────────────────────────────────────────────────────────────┐
│ Local Windows machine (single user)                              │
│                                                                   │
│  ┌───────────────────┐        loopback HTTP        ┌──────────┐ │
│  │ Desktop UI process │ ───────────────────────────▶│ REVA Core│ │
│  │ (PLANNED, PySide6) │◀─────────────────────────── │ process  │ │
│  └───────────────────┘                              └────┬─────┘ │
│                                                           │       │
│                                                     sqlite3 (in-  │
│                                                     process, no   │
│                                                     network hop)  │
│                                                           │       │
│                                                     ┌─────▼─────┐ │
│                                                     │ reva.db    │ │
│                                                     │ (WAL mode) │ │
│                                                     └────────────┘ │
└─────────────────────────────────────────────────────────────────┘
        │ authenticated HTTPS/WebSocket (PLANNED, Phase 5)
        ▼
┌─────────────────────────┐
│ Paired Android device    │  ── separate trust domain ──
│ (PLANNED, Flutter)       │
│ encrypted local cache    │
└─────────────────────────┘

        ▲ explicit, replaceable provider call (async, request/response)
        │ (models/ Protocols — no vendor SDK type crosses this line)
        │
┌─────────────────────────┐
│ Cloud LLM / STT / TTS /   │  ── external trust domain ──
│ embedding provider        │  (no real adapter implemented — Phase 0)
│ (PLANNED real adapters)   │
└─────────────────────────┘
```

## Boundaries and what crosses them

| Boundary | What crosses it | Trust change |
|---|---|---|
| Desktop UI ↔ REVA Core | HTTP requests/responses over loopback (PLANNED: auth token) | UI trusts Core to enforce policy; Core must not trust the UI to have already done so |
| REVA Core ↔ SQLite | Parameterized SQL via `storage/repositories/` | In-process; no network trust boundary, but a code-ownership boundary (only `storage/` may execute SQL) |
| REVA Core ↔ provider | `models/` Protocol request/response contracts | Core sends only what a request needs (e.g. a prompt), never a raw credential the provider didn't issue itself; provider responses are validated Pydantic models, not trusted blobs executed or evaled |
| REVA Core ↔ Android (PLANNED) | Authenticated HTTPS/WebSocket, `SyncEvent` payloads | Separate trust domain; Android is a companion, not an extension of Core's authority (ADR-010) |

## What must never cross a boundary

- Raw secrets (`api_key`, `access_token`, `pairing_token`, etc.) never
  cross into logs or audit events (enforced: `shared/redaction.py`,
  `audit/events.py`).
- Vendor SDK exception/response types never cross from `models/` into
  `orchestration/` — they are normalized to `ProviderError` first
  (ADR-005).
- SQL never crosses out of `storage/` into any other module
  (`docs/architecture/module-boundaries.md`).
- Durable memory writes never cross from a provider or integration
  directly into `storage/` — they must pass through `memory/`'s
  explicit-intent check first (ADR-006, PLANNED).
