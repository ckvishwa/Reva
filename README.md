# REVA

REVA is a private, local-first personal intelligence for one Windows
user, with a future Android companion. It remembers what the user
explicitly asks it to remember, helps continue work, and performs a
small set of safe, allowlisted desktop actions — never more than the
user has approved.

Product source of truth: [`docs/product/reva-v1-prd.md`](docs/product/reva-v1-prd.md).

## What REVA is

- Windows-first, Python-first, local-first, single-user.
- Explicit-memory-first: nothing durable is saved without a clear user
  action.
- Voice-first, not voice-only — every voice action has a visible
  text/UI alternative (voice not yet implemented).
- SQLite-based for durable local state; a cloud LLM is used only
  through an explicit, replaceable provider interface.
- A modular monolith: REVA Core is the stable center; clients,
  providers, and integrations are replaceable edges.

## What REVA is not

- Not SaaS, not cloud-first, not multi-user.
- Not an always-listening microphone or passive surveillance tool.
- Not a generic autonomous agent, browser automation engine, or shell
  command executor.
- Not a plugin marketplace, generic integration platform, or
  microservice system.

See `docs/product/reva-v1-prd.md` §6 for the complete non-goals list.

## Current status: Phase 1A — Typed Chat + Explicit Memory Vertical Slice

Phase 0 (foundation) is done, and Phase 1A proves the first real
product slice end to end:

> authenticated typed request → explicit memory creation → SQLite
> persistence → source-aware retrieval → audit trail → restart recovery

Concretely: a local Bearer-token-authenticated API
(`POST /v1/messages`, `POST /v1/memories`, `GET /v1/memories`,
`GET /v1/audit-events`) backed by real SQLite repositories, a
deterministic (non-cloud) typed-message acknowledgement, and an
explicit `remember:` command. **Voice, reminders, tool execution,
Android, real LLM/cloud provider integration, and any desktop/Android
UI still do not exist.** See `docs/architecture/data-flow.md` for an
exact IMPLEMENTED-vs-PLANNED breakdown,
`docs/testing/acceptance-matrix.md` for how every PRD acceptance test
maps to that status, and `docs/plans/phase-1a-typed-memory.md` for
what this phase specifically added.

## Architecture

```text
Windows Desktop UI (PySide6)              [PLANNED]
                │
   authenticated localhost API/IPC         [IMPLEMENTED — Bearer-token
                │                            auth on every /v1/* route]
REVA Core (Python)
  api · orchestration · storage · audit · shared · config · security  [IMPLEMENTED]
  memory · voice · tools · policy · reminders · sync                  [PLANNED]
                │
SQLite + WAL (authoritative) + future local vector index
                │
PLANNED: authenticated HTTPS/WebSocket
                │
Android Companion (Flutter)               [PLANNED]
```

Full detail: `docs/architecture/system-overview.md`,
`docs/architecture/module-boundaries.md`.

## Local-first philosophy

The local SQLite database is the single source of truth. REVA has no
public internet endpoint. Any cloud processing goes through an
explicit, replaceable provider interface — never a hidden default. See
ADR-015 (`docs/adr/ADR-015-local-first-authority-model.md`).

## Repository layout

```text
reva_core/        REVA Core: api, orchestration, storage, audit, shared,
                   config (implemented); memory, voice, tools, policy,
                   sync, reminders (PLANNED — see each dir's README.md)
desktop/           Windows PySide6 client — PLANNED
android/           Flutter companion — PLANNED
tests/             unit, integration, contract, security, e2e, fixtures
docs/              architecture, adr, security, testing, product,
                   development, plans
scripts/           dev helper scripts (e.g. verify_bootstrap.py)
.github/workflows/ CI
```

## Windows setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m reva_core
```

Full instructions, including `--serve` mode, calling the authenticated
`/v1/*` API, and troubleshooting: `docs/development/setup.md`.

## Tests

```powershell
pytest                                   # everything
pytest --cov=reva_core --cov-report=html # with coverage
ruff format --check . ; ruff check . ; mypy reva_core
```

Full instructions: `docs/development/testing.md`.

## Security philosophy

- REVA Core is never publicly exposed; network listeners bind to
  loopback only, enforced by config validation
  (`tests/security/test_loopback_enforcement.py`).
- Every `/v1/*` route requires local Bearer-token authentication,
  compared in constant time (`reva_core/api/auth.py`); a failed
  attempt is audited and always returns a generic 401.
- No arbitrary shell/command execution exists or is planned; only
  narrow, allowlisted actions (ADR-008, ADR-012).
- Secrets are typed (`SecretStr`) and redacted from logs and audit
  events by a single shared key list (`reva_core/shared/redaction.py`).
- Durable memory requires explicit user intent — never inferred and
  saved silently (ADR-006); Phase 1A's only memory-creation entry
  points are a dedicated API call and a literal `remember:` prefix.

Full detail: `docs/security/threat-model.md`,
`docs/security/security-invariants.md`,
`docs/security/trust-boundaries.md`.

## Roadmap

Phase 0 foundation (done) → **Phase 1A typed chat + explicit memory
(current)** → Phase 1B desktop UI → Phase 2 voice loop → Phase 3 safe
desktop help → Phase 4 Android companion → Phase 5 reliable sync →
Phase 6 first external integrations → Phase 7 context and proactive
assistance → Phase 8 controlled plans. Full detail:
`docs/product/reva-v1-prd.md` §15, `docs/plans/phase-1a-typed-memory.md`.

## Documentation index

- Product: `docs/product/reva-v1-prd.md`
- Architecture: `docs/architecture/`
- ADRs: `docs/adr/`
- Security: `docs/security/`
- Testing: `docs/testing/`
- Development: `docs/development/`
