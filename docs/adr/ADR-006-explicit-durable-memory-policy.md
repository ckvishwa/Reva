# ADR-006: Explicit-Only Durable Memory

**Status:** Accepted (memory feature not yet implemented — Phase 1)

## Context

REVA is explicit-memory-first (PRD §3): durable memory requires clear
user intent ("remember this," saving a note, approving a capture). It
must never silently create permanent sensitive inferences (PRD §8.3).

## Decision

No code path may write to the `memories` table without an explicit,
attributable user action. When `memory/` is implemented, every write
must carry a `MemorySourceReference` proving where the content came
from, and there is no "implicit memory" or "auto-save" pathway.

## Alternatives considered

- **Automatic memory extraction from every conversation** — common in
  generic assistant products, but directly contradicts the PRD's
  explicit-memory-first principle and the non-goal against passive
  surveillance-like collection.
- **A confidence-threshold auto-save** ("save if the model is fairly
  sure this matters") — rejected for the same reason; any threshold
  still means REVA decided, not the user.

## Consequences

- Every future write path into `memories` must be traceable to a
  specific user action, which the `MemorySourceReference` contract
  already models (`shared/contracts/memory.py`).
- Acceptance test #3 (PRD §14) — "a user can explicitly save a memory
  and retrieve it accurately with source information" — is the
  behavioral contract this ADR protects.

## Security implications

Bounds the blast radius of a prompt-injection attempt: even if a
malicious input convinces a future LLM response to claim something
should be "remembered," no code path exists that persists memory
without a distinct, explicit user action separate from LLM output.
