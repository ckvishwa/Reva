# ADR-015: Local-First Authority Model

**Status:** Accepted

## Context

REVA must remain useful and correct with no internet connection (PRD
§12), and local data must not become mandatory cloud-hosted data
(future-expansion rules, PRD §16).

## Decision

The local SQLite database on the primary node (Windows, while
available) is the single source of truth for REVA's durable state. Any
future server-side or cloud component is a cache, sync target, or
processing service — never the authority a local write must check
back with before it is considered valid.

## Alternatives considered

- **Cloud-authoritative with local cache** — rejected outright by the
  product constraints (not SaaS, not cloud-first); would also break
  offline requirements (PRD §12) since every write would need to reach
  the cloud to be "real."
- **Multi-master with no designated authority** — rejected for V1's
  single-primary-node model; PRD §8.7 explicitly designates Windows as
  primary while available, which this ADR encodes as the general rule
  rather than a sync-specific detail.

## Consequences

- A future sync conflict is resolved by *preserving and surfacing*
  both versions (PRD acceptance test #11), not by cloud state silently
  winning — there is no cloud state that outranks a local write.
- Any future cloud feature (e.g. Phase 6 integrations) must be designed
  to degrade gracefully to "unavailable" rather than becoming a
  dependency the local app cannot function without.

## Security implications

Data-at-rest lives primarily on user-controlled devices, not a
third-party server, shrinking the attack surface to "steal the device"
rather than "breach a cloud provider" — this is the architectural
expression of the product's "private by design" principle.
