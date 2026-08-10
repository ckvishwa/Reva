# ADR-009: Append-Oriented Audit Events

**Status:** Accepted

## Context

Users must be able to inspect what REVA stored, retrieved, proposed,
executed, and synchronized (PRD §3, §7 Activity History). Every
executed, denied, and failed tool action must appear in activity
history (PRD §14 acceptance test #8).

## Decision

`audit_events` is append-only: `AuditRepository` implements `insert`
and `list_recent`; there is no `update` or `delete` method, and no
planned code path mutates an existing audit row. Every `AuditEvent` is
constructed from a fixed set of safe fields (category, action, outcome,
correlation ID, actor device, metadata) validated to reject sensitive
keys before it can be constructed at all.

## Alternatives considered

- **A mutable "current status" event updated in place** — rejected;
  loses the historical record of what was denied/failed along the way,
  which the acceptance test explicitly requires to be visible.
- **Logging only, no database table** — rejected; logs are not
  queryable by the future Activity History UI in the way a table is,
  and PRD §7 describes Activity History as a first-class view, not a
  log tail.

## Consequences

- `metadata` on an audit event can never silently accumulate secrets
  over time via an update path, because no update path exists.
- Deletion for user-initiated data export/delete requests (a future
  requirement) will need an explicit, audited deletion operation of its
  own — not a side effect of this ADR, tracked separately.

## Security implications

Append-only plus construction-time secret rejection means the
audit trail cannot become a secondary place secrets leak into, and
cannot be quietly rewritten to hide a denied or failed action.
