# System Overview

Status of this document: describes what is **IMPLEMENTED** through
Phase 1A and what is **PLANNED** for later phases. See
`docs/product/reva-v1-prd.md` for the product source of truth and
`data-flow.md` for a per-flow IMPLEMENTED/PLANNED breakdown.

## What REVA is

REVA is a private, local-first, single-user personal intelligence
system for one Windows PC with a future paired Android phone. It is a
Python-first modular monolith, not a distributed system, not SaaS.

## Components

```text
Windows Desktop UI (PySide6)          [PLANNED — Phase 1B+]
                │
   authenticated localhost API/IPC     [IMPLEMENTED — Bearer-token auth on
                │                       every /v1/* route; /health,/version open]
REVA Core (Python, this repository)
  api/ · orchestration/ · storage/ · audit/ · shared/ · config/   [IMPLEMENTED]
  security/ (local auth token lifecycle)                          [IMPLEMENTED]
  memory/ · voice/ · tools/ · policy/ · reminders/ · sync/         [PLANNED]
  models/ (provider Protocols; FakeLLMProvider is real Phase 1A   [IMPLEMENTED,
  runtime code, no other real providers)                           no real cloud provider]
                │
SQLite + WAL (local, authoritative)   [IMPLEMENTED — schema locked;
                │                       conversations/messages/memories/
                │                       audit_events now have real writers]
future local vector index             [PLANNED]
                │
PLANNED: authenticated HTTPS/WebSocket
                │
Android Companion (Flutter)           [PLANNED — Phase 4-5]
```

## Trust boundaries

1. **Process boundary** — REVA Core is one local OS process. Nothing
   inside it is reachable except through the API boundary or direct
   in-process calls from a UI hosted in the same trust domain.
2. **Network boundary** — REVA Core's API binds to loopback only
   (`127.0.0.1` / `::1` / `localhost`); this is enforced by
   `reva_core/config/settings.py::load_settings`, not just documented
   (see `docs/security/security-invariants.md` #2). Loopback binding
   stops *remote* access; local authentication stops *unauthorized
   local* access — the two controls address different threats (see
   threat model #1 and #6).
3. **Local authentication boundary** — every `/v1/*` route requires
   `Authorization: Bearer <token>`, checked with `hmac.compare_digest`
   (`reva_core/api/auth.py`). `/health` and `/version` stay open
   because they carry no user data, secrets, or sensitive state.
4. **Storage boundary** — SQLite is the only authoritative store REVA
   Core writes to. No other process is expected to write to the same
   database file.
5. **Future device boundary** — a paired Android device is a separate
   trust domain that reaches Core only over an authenticated transport
   REVA does not yet implement (Phase 5).

## Core ownership

REVA Core owns orchestration, memory semantics, retrieval coordination,
provider routing, voice lifecycle coordination, the tool registry,
policy/permissions, reminders, storage coordination, auditing, and
future sync semantics (PRD §8.1, §10). Clients, providers, and
integrations are replaceable edges and must not duplicate this
business logic (`docs/architecture/module-boundaries.md`).

## Local-first behavior

- SQLite is the durable store. It ships with the local install; there
  is no server-side counterpart in V1.
- Any cloud processing happens through an explicit, replaceable
  provider interface (`reva_core/models/`), never as a hidden default.
- REVA has no public internet endpoint (PRD §4, security invariant #1).

## Offline posture

Local UI, history, memory browse/search, reminders, and supported
local actions must remain available with no internet connection (PRD
§12). Phase 1A's typed-message path already demonstrates the pattern:
`TypedInteractionService.handle_typed_message` catches `ProviderError`
and falls back to a "reasoning unavailable" reply without failing the
request — memory creation and query never touch a provider at all.
Full offline UX (a real UI degrading gracefully) remains PLANNED.

## Provider boundaries

`reva_core/models/` defines narrow typed Protocols (`LLMProvider`,
`EmbeddingProvider`, `STTProvider`, `TTSProvider`). No vendor SDK type
crosses this boundary; no provider may mutate durable state, create
memory, or bypass orchestration/policy. `FakeLLMProvider`
(`reva_core/models/fakes.py`) is the Phase 1A default and is real
runtime code, not a test double — it is deterministic, makes no
network call, and every response it produces is documented as such.
No real cloud provider integration exists, and CI never needs a cloud
credential.

## Future Android relationship

Android is a **companion device node**, not a second copy of REVA
Core (ADR-010). It will hold an encrypted local cache of
Core-approved data and reach Core over an authenticated HTTPS/WebSocket
boundary (ADR-011). No Android code exists in this repository yet;
`android/README.md` documents the plan.
