# ADR-001: Python 3.12+ for REVA Core

**Status:** Accepted

## Context

REVA Core needs one language for orchestration, storage access, and
provider integration that is Windows-first, has a mature async story,
and does not require the team to context-switch languages for the
backbone of the system.

## Decision

REVA Core is written in Python, targeting 3.12+.

## Alternatives considered

- **C#/.NET** — excellent Windows integration, but the team's stated
  direction is Python-first and it fragments the stack from any future
  local ML tooling.
- **Node/TypeScript** — good async model, weaker fit for future local
  embeddings/ML work and SQLite ecosystem maturity is comparable, not
  better.
- **Rust** — best raw performance and safety, but slows iteration speed
  far more than Phase 0-3 needs justify.

## Consequences

- Access to `sqlite3` (stdlib), a large PyPI ecosystem, and Pydantic v2
  for contracts.
- Async I/O (provider calls) uses `async`/`await`; storage stays
  synchronous (`sqlite3` has no first-class async driver worth adding
  as a dependency at this stage).
- 3.12 minimum gets structural typing improvements and performance
  gains without requiring bleeding-edge features.

## Security implications

None directly; Python's dependency surface means supply-chain hygiene
(pinned versions, minimal dependency count) matters more than in a
statically-linked binary — addressed by keeping Phase 0 dependencies
deliberately small.
