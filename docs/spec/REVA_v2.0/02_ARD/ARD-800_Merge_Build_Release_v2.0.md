# ARD-800 — Merge, Build and Release v2.0

**Document ID:** REVA-ARD-800 · **Version:** 2.0.1 · **Date:** 2026-10-11 · **Status:** Proposed
**Replaces:** `05_REVA_EXECUTION_AND_QA.md` (archived), ARD v1 §12, §14. **Decisions:** ADR-016, ADR-017, ADR-023.

## 1. Repository layout

```text
Reva/
  core/          Python Core (ARD-300)
  kernel/        Rust Domain Kernel + generated bindings (ARD-700)
  windows/       WinUI 3 app + Windows adapters (ARD-100)
  android/       Kotlin/Compose app (ARD-200)
  avatar/        three.js + VRM web package (ARD-400)
  contracts/     JSON Schema, OpenAPI, capability registry; generated C#/Kotlin/Python types
  assets/avatar/ .blend + .vrm (Git LFS)
  tests/         unit, contract, cross-binding, security, voice-evals, domain-evals, e2e, benchmarks
  docs/ard/      this pack; docs/archive/ v1 pack
  packaging/     windows/, android/
```

## 2. Merge and cleanup procedure

1. Snapshot: tag every branch `archive/pre-merge-2026-10-11`; `git bundle create … --all` for Reva and any surviving AuraO copy; store off the dev drive.
2. Reva dirty tree: commit the wake-word fix and its test alone (P0-01). Move shutdown edits to `archive/shutdown-wip`. Move plan docs to `docs/archive/`. Nothing reset or discarded.
3. Delete `wip/slice-8a-draft` (v1: do-not-merge) after step 1.
4. Harvest from AuraO (only from copies that exist; v1 execution doc calls the local copy deleted — check GitHub history and PR #8): Memory Engine benchmark + approval/abstention rules; Kokoro voice protocol + orphan tests; finance SQLCipher/Credential Manager Rust code → Kernel seed; WDIO E2E scenarios; test env guard; domain logic for Coach, Career, Finance, Gym (→ Health), Cyber, Personal, Learn. Re-implement in Rust/Python/Kotlin; no TypeScript copied.
5. Archive the AuraO GitHub repo (read-only); delete local copies only after step 4 is merged and green.
6. Cloud: read-only check then backed-up delete of `test-user-engine` rows in Aura-Prod; rotate the service-role key used by the old Python finance worker; revoke the invalid Anthropic key from all `.env`; remove the weak-state Google OAuth callback.
7. Machine: remove the stray `com.aura.assistant.finance` Credential Manager entry once confirmed unused.
8. Spec pack: `08` schema renamed to `08_REVA_PLANNER_DECISION.schema.json` (done in `09_ARCHIVE_v1`); duplicate `__1_` pack file removed.

## 3. CI

| Lane | Checks |
|---|---|
| Core | pytest, ruff, mypy, env guard, contract generation diff |
| Kernel | `cargo test`, clippy, fmt; Android cross-build (arm64-v8a, x86_64); conformance through Python and Kotlin bindings; no-network dependency check |
| Windows | `dotnet build/test`, WinUI unit tests, FlaUI smoke (self-hosted Windows runner) |
| Android | Gradle lint, unit tests, Compose UI tests on emulator API 31 and 36, manifest policy check |
| Avatar | build, size budget, offline-load test |
| Security | secret scan, dependency audit, SBOM, registry absence test (no money movement) |
| Contracts | JSON Schema/OpenAPI breaking-change check |

## 4. Test pyramid and evidence

- **Unit / contract / cross-binding** on every push.
- **Integration:** Core + Kernel + fake providers; sync replay; consent filter network capture.
- **E2E Windows:** FlaUI drives the real built app; PID orphan checks after every spec (lessons from the AuraO WDIO harness: wait for real webview readiness, diff PIDs, never trust closeWindow alone).
- **E2E Android:** Compose tests + one physical-phone run per gate.
- **Hardware:** real mic/speaker voice runs per gate; recorded.
- **Evals:** intent/tool eval, false-success corpus, domain answer accuracy, health safety, WER, latency, lip-sync offset.

## 5. Evidence ledger

Every VERIFIED status needs a ledger row: requirement ID, test ID, commit SHA, device/OS, provider + model versions, date, result, artifact link. CSV in `tests/evidence/ledger.csv`. Skipped hardware tests are recorded as SKIPPED, never PASSED.

## 6. Requirements

| ID | Stage | Requirement | Verification | Replaces |
|---|---|---|---|---|
| AR-REL-001 | P0 | Baseline snapshot recorded before changes (status, HEAD, toolchains, test counts) | Snapshot file | P0-03 |
| AR-REL-002 | R1 | CI lanes above green on main | CI | ARD v1 §12 |
| AR-REL-003 | R1 | Evidence ledger exists; VERIFIED only with a ledger row | Ledger audit | PRD §16 |
| AR-REL-004 | R4 | Windows packaging includes Core interpreter, Kernel, models guidance | Clean VM | AR-078 |
| AR-REL-005 | R4 | Signed artifacts, checksums, SBOM | Release CI | AR-079, NFR-011 |
| AR-REL-006 | R4 | Reliability: disconnect, service kill, permission loss, sleep, stale actions | Failure-injection report | AR-081 |
| AR-REL-007 | R3 | Latency budgets recorded per device/provider | Perf artifact | AR-076 |
| AR-REL-008 | R4 | Performance, memory, CPU, battery, thermal profiled on documented devices | Profile report | NFR-010 |
| AR-REL-009 | R4 | Upgrade migrates all stores without data loss; rollback compatibility declared | Snapshot migration | AR-013 |
| AR-REL-010 | R4 | Accessibility smoke on both apps (keyboard, Narrator, TalkBack) | Checklist | FR-050 |

## 7. Stop conditions (v1 kept)

Stop and escalate if: a test touches real user data; a security check fails open; a hardware claim lacks a recording; a slice needs a new service; a requirement would need money movement or medical advice.
