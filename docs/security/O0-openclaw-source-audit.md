# REVA O0 — OpenClaw pinned-source and security audit

**Date:** 2026-10-16  
**Scope:** O0 audit and O1 entry gate; no OpenClaw installation, production integration, credential provisioning, or REVA runtime changes.  
**REVA baseline:** `main` merge `fcd328b26059eb5ea133c137dd83b2b41c6a640e`; post-merge CI run [38861940686](https://github.com/ckvishwa/Reva/actions/runs/38861940686) passed seven jobs. C1c/C2a/C2b/C2c are integrated; physical device acceptance is still `NEEDS_HARDWARE`.  
**Pinned OpenClaw source:** `openclaw/openclaw@af50fbd9e9bcc8bc879f3b5525ce2210b3244d15` ([commit](https://github.com/openclaw/openclaw/commit/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15)); a source pin is **not** a verified binary/dependency lock or deployed version.  
**O0 status:** `IMPLEMENTED-UNVERIFIED / HOLD`. **O1 runtime activation: BLOCKED** until the negative security gates below are demonstrated on the intended isolated host.

## 1. Intent and boundaries

We are assessing an **optional external OpenClaw sidecar**, not importing OpenClaw agent execution semantics into REVA. Desired deployment: owner opt-in, default OFF, isolated process/container/OS identity, `127.0.0.1`-only Gateway, authentication, least-privilege tool policy and sandbox, no host execution. Untrusted OpenClaw text may become **proposals**, not authority. Every OS/Kernel action remains behind REVA's versioned capability registry, deterministic `authorize()`, target-device click approval where required, signed scoped grants, idempotent native executor, and evidence-based completion. REVA's prohibited T3 operations remain prohibited.

Reference: [REVA ARD-600](../../docs/spec/REVA_v2.0/02_ARD/ARD-600_AI_Agent_and_Actions_v2.0.md) (AR-AGT-001 through AR-AGT-018). O0 creates no device/node pairing, disables no REVA safeguards, and sends no user domain data to OpenClaw.

## 2. Source-and-license audit (pinned commit)

| Control | Static finding | Status |
| --- | --- | --- |
| Repository license | Root [LICENSE](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/LICENSE) declares MIT. Include license notice if subsequently copying substantial code; no copying in O0. | Verified from pinned source |
| Included third-party notices | [THIRD_PARTY_NOTICES.md](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/THIRD_PARTY_NOTICES.md) identifies SQLite public-domain material, Pi family MIT, and Octicons MIT. Notices are **not** a complete transitive license inventory. | Partial |
| Dependency provenance | Repo contains `pnpm-lock.yaml` and `package.json`; no offline lockfile integrity check, SBOM, package-signature review, vulnerability inventory or installation was executed here. | Not verified |
| Release/artifact attestation | Commit pinned; downloadable releases/containers and dependencies not proven byte-identical to that commit. | Not verified |
| OpenClaw security model | [SECURITY.md](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/SECURITY.md) says shared-agent sessions are **not isolation boundaries**; a gateway is for one trusted operator boundary. | Verified from pinned source |

No claim of supply-chain clearance or production readiness is made from static source review.

## 3. Gateway, auth, pairing, session and execution assessment

| Surface | Pinned upstream evidence | REVA disposition |
| --- | --- | --- |
| Gateway network | [Gateway config](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/config-gateway.md): `gateway.bind=loopback`, `gateway.auth.mode=token`. | Use explicit loopback and strong secret; verify bound socket at runtime; no LAN/Tailscale/public listener. |
| Authentication | [Protocol auth](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/protocol/auth.md): shared token/device identity and operator scopes. [Security policy](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/SECURITY.md) documents shared-secret bearer endpoints as powerful operator surfaces. | Never provide REVA grants/tokens to OpenClaw; sidecar credentials must have no REVA write authority. |
| Pairing | [Node pairing](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/pairing.md) has device pairing and separate node capability approval, with `system.run` risk. | No OpenClaw node pairing or command exposure in O1; REVA's own paired-device trust stays independent. |
| Session/events | [Gateway protocol](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/protocol.md) uses scoped WebSocket roles and RPC/events including run/session lifecycle. | Treat all messages/events as untrusted; bind run IDs, expiry, cancellation, request ownership; do not trust narrated success as evidence. |
| Tool policy | [Tool policy](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/config-tools/tool-policy.md) uses profiles plus allow/deny layers. Deny wins; `exec` also permits filesystem changes regardless of disabled file-edit tools. | Hard-deny `exec`, `process`, `code_execution`, `group:runtime`, `group:fs`, `gateway`, `cron`, plugins/skill installs, browser/control and node execution. |
| Sandbox | [Sandboxing](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/sandboxing.md): ordinary agent sandboxing is OFF by default; Gateway itself remains on host. | Default configuration is not acceptable. Require hardened sandbox/OS isolation **in addition to** global tool denies, then verify effective policy and no host exec. |
| Escape hatch | [Elevated + policy](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/sandbox-vs-tool-policy-vs-elevated.md). | Explicitly disable elevated, bash, node `system.run`, unrestricted plugins and host-browser control; prove denial with negative tests. |
| Hardened example | [Hardened baseline](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/security/hardened-baseline.md) includes loopback, token auth, runtime/fs/tool denies, exec-deny, elevated off. | Reference starting point, **not** evidence that an actual instance meets this policy. |

**Critical finding OC-O0-01:** The upstream default is capable of executing on the host if no sandbox is active, and the Gateway remains on the host even with sandboxing. A `sandbox=all` setting alone is not a proof of no host execution; unrestricted provider tools, elevated or node operations can undermine the goal. Until an installed, isolated instance passes active negative checks, fail closed at REVA's integration boundary.

## 4. Threat model

| Threat | Required control / negative test |
| --- | --- |
| Malicious prompt/tool output proposes shell, file delete or arbitrary RPC | Unknown/restricted capability denied before native broker; no `system.run`, `exec`, shell, file writes or plugin execution |
| Compromised sidecar or stolen Gateway token | Separate OS/container identity, local ACLs, short-lived credentials, no REVA grants or secrets; no lateral device access |
| Host escape through tool, elevated, plugin or browser | Explicit denies and isolated sandbox; runtime attempted execution must be denied, monitored and leave host unchanged |
| Paired-node command expansion | No OpenClaw nodes paired; deny node command surface; verify no `system.run` |
| Forged completion or duplicate sidecar events | REVA grants and signed executor receipts only, stable idempotency keys, replay rejection, no completion inferred from text |
| Sensitive finance/memory/health leak | No domain data forwarded in O1; eventual broader scope only with opt-in and separate privacy/network capture gates |
| Port exposure, CSRF or external client | `127.0.0.1` socket only, non-empty strong token, authenticated WS, origin checks, no published container ports, firewall check |
| Build-time compromise | Reproducible pinned artifact, SBOM/dependency notices, no automatic plugin/package installs, security scan before O1 |

## 5. Feature-fit matrix: ADAPT, don't clone

| OpenClaw capability | REVA O1 allowance |
| --- | --- |
| Gateway session/run events | Consider **read-only, untrusted** status/results with strict origin binding; no automatic cross-session access |
| Structured planning/proposals | Potentially adapt via a narrow schema into REVA's planner decision validation, with `authorize()` re-check and signed broker |
| Capability/node discovery | Documentation only; do not import OpenClaw scopes into REVA registry |
| Cron, plugins, arbitrary shell, browser control, skill installer | Excluded |
| Host/node execution, elevated, gateway mutation, filesystem tools | Excluded |
| Narrated "done" and suggested approvals | Never trusted; only REVA native evidence is authoritative |
| Android and Windows transport | Continue REVA's existing phone-to-PC implementation; do not add an independent executable path |

## 6. O0 runtime acceptance checklist (NOT RUN)

These steps require a separately isolated local OpenClaw installation after source/lockfile review. **Do not install or launch OpenClaw on the owner's production REVA host until the isolation design is approved.**

1. Verify resolved artifact hash/commit, Node/package versions, complete dependency/SBOM license and advisory scan. If not verifiable, STOP.
2. Configure explicit loopback+token; apply [upstream hardened baseline](https://github.com/openclaw/openclaw/blob/af50fbd9e9bcc8bc879f3b5525ce2210b3244d15/docs/gateway/security/hardened-baseline.md) with even narrower tool and node access; default OFF in REVA.
3. Prove the listener binds only loopback, has working token rejection/rotation, and cannot be reached externally.
4. Run `openclaw security audit` and `openclaw sandbox explain --json`; archive redacted output with the exact version and applied config.
5. Negative-test every shell/runtime/FS/browser/plugin/elevated/node command from available interfaces. Expect denial; prove the host file/process/device remains untouched.
6. Negative-test mismatched device identities, token replay, event spoofing, cancellation, timeouts, cross-session requests, and attempts to reach REVA protected API routes. Expect denial.
7. Record each test ID, input, observed result, logs, hash, environment and reviewer in the REVA evidence ledger. Do not mark PASS based on config alone.
8. Obtain explicit owner acceptance of a passing O0 report before activating O1. Keep all physical REVA `NEEDS_HARDWARE` rows open; they are separate from this gate.

## 7. O1 implementation contract (PLANNED, NOT STARTED)

**Minimal vertical slice:** a `REVA_OPENCLAW_ENABLED=false`-by-default sidecar adapter that accepts only loopback-scoped, read-only structured agent/session observations and never installs, spawns, controls or grants execution authority to OpenClaw. No production credentials embedded. A compatibility adapter may optionally convert an external suggestion into a **non-executing** `PlannerDecision` proposal, then send it through existing REVA schema validation and `authorize()`. No direct REVA native-executor call is permitted. The first PR must include tests for disabled-by-default, unauthenticated gateway rejected, denied shell/T3, malformed and replayed event, unapproved T2, source-status-not-evidence, cancellation and no network traffic when disabled. Any mutation-bearing feature remains out of O1.

**Entry gates:** O0 active negative tests pass; dependencies and licenses checked; explicit approval to connect a sandboxed instance; hardware work remains separately tracked. Until then, do not add `openclaw` dependencies, install Node, provision tokens, start an OpenClaw process, or alter `reva_core`, Kernel, desktop or Android for O1.

**Decision (superseded in part, 2026-10-16 — see §8):** ~~HOLD O1~~. Static upstream audit began and identified default host-execution risk. Runtime verification could not be executed from a remote GitHub-only audit and has not been represented as successful.

## 8. Owner-authorized sandbox decision and O1 adapter (2026-10-16)

**Owner decision (ADR-041):** the owner explicitly accepts the risk of `agents.defaults.sandbox.mode="off"` for the local OpenClaw instance on this trusted, single-user host, overriding the §3/§6 requirement that O1 wait on a demonstrated isolated-sandbox instance. **This authorization changes one thing only** — the sandbox-mode blocking criterion. Every other O0 finding and gate stands: OC-O0-01's underlying risk (unrestricted provider tools, elevated or node operations can execute on the host when sandbox is off) is now accepted by the owner rather than mitigated by sandboxing, so REVA's own boundary carries the full weight of defense in depth:

- OpenClaw's own tool policy must still hard-deny `exec`, `process`, `code_execution`, `group:runtime`, `group:fs`, `gateway`, `cron`, plugin/skill installs, browser/control and node execution — unchanged from §3. REVA cannot verify or enforce this from its own process boundary; it is the owner's responsibility when configuring the local OpenClaw instance, same as before.
- REVA's own adapter (`reva_core/providers/openclaw.py`) connects with the narrowest operator scopes (`operator.read`, `operator.talk` — never `operator.write/admin/approvals/pairing`), never trusts OpenClaw's text as evidence of anything happening, and routes every executable proposal through the unchanged `authorize()`/signed-grant/`Broker`/native-executor path — no second executor was created.
- `Proposal.hosted_origin=True` on every OpenClaw-sourced proposal means it needs the same per-domain consent a hosted cloud model's proposal needs, and `openclaw_allowed_scopes` (empty by default) means enabling the integration alone grants it zero capability — nothing finance/health/memory/personal/device-scoped executes until the owner explicitly lists scopes.
- The runtime negative-test checklist in §6 was **not** executed against a real OpenClaw instance in this pass (no isolated host was set up; Node/npm are present on this machine but a real install was deliberately not attempted here — see §9). The 25 automated tests in `tests/unit/test_openclaw.py` exercise the real adapter and a protocol-faithful fake Gateway server (not a mock of REVA's own client) covering: disabled by default, sandbox-off recorded, authenticated/unauthenticated connection, request/response lifecycle, malformed responses, agent-error/aborted states, timeout + best-effort abort, cancellation, the same run id proposed twice collapsing to one action, unapproved T2 not granted, a forbidden capability refused, zero default scope refusing an otherwise-fine capability, free-form narration proposing nothing, a forged "I already did it" reply never read as evidence, gateway-unavailable, and the auth token never appearing outside the connect frame.

**Still open / NEEDS_RUNTIME:** everything in §6 that requires an actual running OpenClaw instance — the dependency/SBOM/advisory scan, the hardened-baseline config applied to a real process, `openclaw security audit`/`sandbox explain --json` output, and the negative tests run against that real process (shell/exec/plugin/node denial, token replay, cross-session access, reaching REVA's protected routes). These are not fabricated as passing. Physical-hardware REVA rows remain `NEEDS_HARDWARE`, unaffected and unchanged by this section.

## 9. Why a real OpenClaw install was not attempted in this pass

Node v24.13.1 and npm 11.8.0 are present on this host; `pnpm` is not. Installing and running the real OpenClaw Gateway here would mean doing so directly on the owner's production REVA host, which §6 of this document explicitly says not to do before the isolation design is approved and the dependency/SBOM scan is run — the owner's §8 authorization was scoped to the sandbox-mode setting, not to skipping that separate install-time gate. Real coverage of REVA's own adapter code came instead from a genuine local WebSocket server speaking the pinned protocol (`tests/unit/test_openclaw.py`), which is sufficient to verify REVA's boundary logic but is **not** a substitute for the runtime checklist in §6 against the actual third-party binary.
