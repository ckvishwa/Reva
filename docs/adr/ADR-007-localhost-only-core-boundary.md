# ADR-007: Localhost-Only Core Boundary

**Status:** Accepted

## Context

REVA Core must never be publicly exposed (PRD §9, non-goal list). It
needs an API boundary for the desktop UI (and, later, indirectly for
Android through a different transport), but that boundary must not be
reachable from the network.

## Decision

`reva_core/config/settings.py::load_settings` rejects any `api_host`
that is not `127.0.0.1`, `::1`, or `localhost`, raising
`ConfigurationError`. The FastAPI app (`reva_core/api/app.py`) is only
ever run bound to whatever host `Settings` provides — there is no code
path that binds `0.0.0.0` or any other interface.

## Alternatives considered

- **Document the loopback requirement without enforcing it** — rejected;
  a documented-only invariant is not testable and would not survive a
  careless future config change.
- **Bind all interfaces and rely on a host firewall** — rejected; it
  makes REVA's safety depend on external OS configuration the product
  cannot verify, contradicting "Core is never publicly exposed" as a
  property of REVA itself.

## Consequences

- `tests/security/test_loopback_enforcement.py` fails CI if this
  invariant regresses.
- A future domain route (Phase 1+) must add localhost authentication on
  top of this network-level restriction — loopback-only prevents
  remote network access, it does not prevent another *local* process
  from calling the API, which is a distinct threat (see threat model,
  "malicious local process").

## Security implications

This is security invariant #1 and #2
(`docs/security/security-invariants.md`). Loopback binding is a
necessary but not sufficient control; local authentication is the
Phase 1 companion control once a route exists worth protecting.
