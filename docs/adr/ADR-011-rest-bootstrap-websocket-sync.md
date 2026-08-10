# ADR-011: REST Bootstrap Plus WebSocket Future Realtime Sync

**Status:** Accepted (transport not yet implemented — Phase 5)

## Context

Sync needs authenticated HTTPS for pairing, registration, reconciliation,
and backfill, and authenticated WebSocket transport for future
near-real-time updates (PRD §8.7).

## Decision

Device pairing, registration, and bulk reconciliation/backfill use
authenticated REST over HTTPS. Once paired and caught up, near-real-time
propagation (PRD §13 target: under 5 seconds while both nodes are
active) uses an authenticated WebSocket connection. REST remains the
fallback/bootstrap path if the WebSocket connection is unavailable.

## Alternatives considered

- **WebSocket-only, including pairing** — rejected; pairing and bulk
  backfill are inherently request/response and benefit from HTTP's
  simpler retry/idempotency semantics; forcing them onto a persistent
  socket adds complexity with no benefit.
- **A custom binary RPC protocol** — rejected by the product
  constraints ("no custom RPC systems"); REST+WebSocket are well
  understood, have mature Python and Flutter client support, and need
  no custom wire-format work.
- **Polling only (no WebSocket)** — rejected; cannot realistically meet
  the sub-5-second propagation target without excessive poll frequency.

## Consequences

- Two transport code paths to secure and test once implemented, not
  one — accepted complexity given the differing use cases.
- Stable event IDs, device IDs, entity versions, timestamps, and
  operation type (PRD §8.7) are the payload shape for both transports,
  so switching between them mid-reconciliation is safe.

## Security implications

Both transports require authentication; neither is a bare unauthenticated
socket. Device pairing tokens are the credential and must never be
logged in plaintext (`shared/redaction.py` already treats
`pairing_token` as sensitive).
