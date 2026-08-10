# ADR-010: Android as a Companion Device Node

**Status:** Accepted (no Android code exists yet — Phase 4)

## Context

REVA V1 includes an Android companion (PRD §1, §7). It must not become
a second full copy of REVA Core's business logic, and Windows remains
the primary node while available (PRD §8.7).

## Decision

Android is a companion device node: it holds an encrypted local cache
of Core-approved data (conversations, explicit memories, reminders,
selected settings, safe audit summaries) and a thin client for chat,
voice capture, quick capture, and reminder notifications. It never
owns policy, durable-memory semantics, audit policy, or provider
business logic (PRD §8.1) — those stay on whichever node currently owns
Core.

## Alternatives considered

- **A second REVA Core instance on Android** — rejected; doubles the
  surface that must implement policy/memory/audit correctly and
  consistently, and directly contradicts "Windows is the primary node."
- **Android as a dumb terminal with no local cache** — rejected; PRD
  §12 requires offline behavior on Android (local changes queue until
  reconnection), which needs a real local cache, not just a live
  connection.

## Consequences

- Android's Flutter app talks to Core only through the authenticated
  transport defined in ADR-011, never by embedding Core logic.
- Conflict handling, offline queues, and reconciliation are Core's
  responsibility (`sync/`, PLANNED), not something Android decides on
  its own.

## Security implications

Keeping business logic on Core (or whichever node currently holds it)
means a compromised Android device cannot unilaterally rewrite policy
or audit history — it can only submit sync events that Core's
reconciliation logic evaluates.
