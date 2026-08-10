# ADR-014: Modular Monolith

**Status:** Accepted

## Context

REVA Core needs internal separation of concerns (orchestration, memory,
storage, policy, audit, providers) without the operational overhead of
running and coordinating multiple services for a single-user desktop
app.

## Decision

REVA Core is one Python process, one deployable unit, with strict
in-process module boundaries enforced by convention and code review
(`docs/architecture/module-boundaries.md`), not by network calls
between services.

## Alternatives considered

- **Microservices** — explicitly excluded by the product constraints;
  a single-user local app gains nothing from network-separated
  services and loses simplicity, startup time, and idle resource
  footprint (PRD §13 targets under 500MB idle memory, under 2% idle
  CPU — hard to hit with multiple service processes and their own
  runtimes).
- **A single undifferentiated script with no internal boundaries** —
  rejected; would make the "clients/providers are replaceable edges,
  Core is the stable center" principle unenforceable in practice.

## Consequences

- Module boundaries are a discipline the team must maintain through
  review, not something a service mesh or network boundary enforces
  for free. Accepted tradeoff for Phase 0-3 scale.
- If a genuine need for process isolation emerges (e.g. a provider
  adapter that must run untrusted code), that is a new ADR, not a
  silent architecture drift.

## Security implications

A single process means a compromise of REVA Core compromises the whole
process — mitigated by the loopback-only network boundary (ADR-007),
the allowlisted tool model (ADR-008), and no-arbitrary-execution
guarantee (ADR-012), rather than by process isolation.
