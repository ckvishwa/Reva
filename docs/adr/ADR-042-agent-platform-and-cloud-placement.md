# ADR-042: REVA agent platform and cloud placement

**Status:** Accepted product direction; implementation in progress (2026-10-16).
**Decision owner:** REVA owner, who explicitly requested shell, browser, plugins, nodes, and
OpenClaw-style cloud placement implemented in REVA's own stack.

## Decision

REVA will provide one agent runtime and one versioned execution contract across local Core,
paired devices, and optional cloud workers. OpenClaw is an architecture reference, not a required
runtime or source-code dependency. Windows and Android remain native REVA clients; the Rust Domain
Kernel remains authoritative for each device's local domain data.

The REVA Gateway owns authenticated sessions, channel routing, agent turns, tool policy, approval
state, cancellation, and execution records. A tool can run on the Gateway, an authenticated paired
node, or an isolated worker. Placement changes where the tool runs, not who may authorize it.
Every executable call carries a Broker-issued signed grant bound to capability, canonical arguments,
actor, target, expiry, and an idempotency key. A handler's claim alone is only `observed`; a
separate evidence verifier is required before `verified` can be reported.

The platform includes shell/process execution, browser control, plugins, device-node capabilities,
scheduled work, and optional hosted Gateway/worker placement. Each is exposed through an explicit
capability and approval policy. Shell and browser are product scope, replacing the prohibitions in
ADR-012 and the earlier 2.0 PRD. Unattended unrestricted access is not the default: permissions are
bound to the requester, target, session, and concrete operation.

## Boundaries

1. **Client to Gateway:** authenticated, encrypted transport; explicit client role and scope;
   bounded requests, replay protection, revocation, and reconnect semantics.
2. **Agent to policy:** model output can propose a tool call but cannot sign a grant, approve itself,
   choose a lower tier, or declare success.
3. **Gateway to executor:** the executor verifies the signed grant and target locally before acting.
   Shell, browser, plugin, and node handlers share this admission step.
4. **Gateway to model provider:** hosted model use is opt-in, disclosed, and filtered by domain consent.
   Cloud workers do not receive model-provider credentials.
5. **Gateway to node/worker:** paired hardware and disposable workers have separate identities and
   capability sets. A worker receives only the data required for its admitted session. Offboarding
   revokes its credentials and reconciles or discards unfinished work explicitly.
6. **Domain data:** each device's Kernel stays usable offline. Hosting the Gateway does not silently
   transfer Finance, Health, Memory, or Personal data to that host.

## Components and initial code

- `reva_core.execution.host.ToolHost` is the first shared executor boundary. It checks registration,
  argument schema, target, signed grant, expiry, and replay before calling a handler. The handler
  does not get to verify its own result.
- Existing `reva_core.policy.Broker` remains the authorization authority. Its signed grant and
  action ledger are reused; tool handlers never call `authorize()` themselves.
- The existing pairing Gateway and Android client are the starting point for node identity and
  transport. The protocol will be versioned before adding new remote methods.
- Shell, browser, plugins, channels, scheduler, and cloud-worker placement will each be separate
  registered capability families on this same boundary.

## Threats and acceptance

- A forged, expired, replayed, wrong-target, or modified grant must fail before a handler runs.
- A plugin cannot add a capability or request a permission without an owner-visible registration
  step; disabling it removes its handlers and outstanding grants cease to execute.
- Shell commands and browser actions run in a declared environment with bounded time, output, and
  filesystem/network reach. Approval shows the concrete operation and target.
- A node disconnect, worker loss, or Gateway restart must never turn an unknown result into success
  or replay an interrupted action automatically.
- Cloud placement must preserve provider credentials at the Gateway, support credential revocation,
  and leave the offline Kernel usable.

## Migration and rollback

The existing OpenClaw sidecar experiment remains separate and default-off while REVA's own runtime
is built. This ADR does not activate any new handler or cloud endpoint by itself. Each capability
family ships behind an explicit configuration switch and can be disabled without migrating domain
data. No production database migration is part of the initial `ToolHost` slice.

## Alternatives

- **Use OpenClaw as REVA's permanent agent runtime:** rejected by the owner in favor of REVA's own
  implementation and language.
- **Keep only narrow named desktop actions:** superseded by the requested full agent platform.
- **Run every tool in the Gateway process:** rejected for device-local actions and isolated workers.

## Proof required before release

Tests for signed grant admission, negative authorization, replay, target binding, evidence, browser
and shell confinement, plugin removal, node revocation, worker recovery, cloud data disclosure, and
physical-device behavior. Any hardware-only result is recorded as `NEEDS_HARDWARE` until exercised.
