# REVA — Execution Plan, QA Charter and Build/Release Gates

**Date:** 2026-10-11 | **Team assumption:** 1 developer/founder + 1 automation QA engineer | **Status:** implementation plan, not completed work.

## 1. Operating rules

1. Work from `D:\Projects\Reva`, not the deleted AuraO codebase.
2. Before coding, inspect actual branch/HEAD/status. The October 11 audit shows `feature/windows-app-command-routing` at `6004fed`, with dirty resolver, shutdown and doc edits. **Do not assume today’s working tree has not changed.**
3. Do not run commands using real user recordings/data or modify `REVA_DATA_DIR`; tests use temp directories.
4. Do not merge `wip/slice-8a-draft`; the audit explicitly labels it untested/do-not-merge.
5. Each feature has a PRD ID, ARD ID, accepted ADR, minimal diff, automated test, runtime proof (where needed), rollout flag and rollback instruction.
6. No AI model may execute shell or bypass deterministic tools/policy. Never expand privileges for demo convenience.
7. No platform service can claim device support without testing on that device/API version.
8. Two review passes per feature: developer code/self-test; QA independent reproducibility and regression.

## 2. Recommended work board

| Lane | Owner | Definition |
|---|---|---|
| Ready | Founder | scoped ticket with IDs, acceptance, expected paths, non-goals |
| In development | Founder | implementation + focused unit/integration tests |
| QA ready | Founder → QA | commit or exact diff; fixture/run instructions; no secrets |
| In QA | QA engineer | negative + positive + edge/hardware smoke; defect ticket |
| Fix/retest | Founder + QA | targeted regression + affected integration suite |
| Release gated | Both | change log, artifact evidence, rollback and risk assessment |
| Done | QA signoff | test results traceable to commit; docs updated |

## 3. Immediate P0 work — do this before building voice or Android

**P0-01 — Fail-closed wake-word integrity**
- Requirements: FR-019, AR-016, AR-030; existing security audit P0.
- Files (audit): `desktop/src/Reva.Desktop/Services/WakeWordKeywordResolver.cs`, `desktop/tests/Reva.Desktop.Tests/Unit/WakeWordKeywordResolverTests.cs`.
- Change: require expected SHA-256 for every enabled `.ppn` phrase and return failure for blank/absent manifest even when file exists. Ensure this prevents recorder arming.
- Exclude: `MainWindow.xaml.cs` shutdown edits, other dirty files, unrelated plan docs.
- Dev acceptance: `dotnet test desktop\Reva.Desktop.sln --configuration Release` passes; inspect `git show HEAD:...WakeWordKeywordResolver.cs` after commit.
- QA acceptance: missing hash, invalid hash, mismatched hash, correctly matching hash, empty dictionary; positive + negative tests.

**P0-02 — Shutdown lifecycle on physical Windows runtime**
- Requirements: FR-059, AR-007, AR-072.
- Change: no blind adoption of `Environment.Exit(0)` until lifecycle test and process ownership evidence.
- Dev acceptance: close application; record desktop PID and Core PID before/after; owned Core exits, external Core remains; no exception/hang.
- QA acceptance: 10 short open-close cycles; stale/no-Core conditions; cancellation and file handle cleanup.

**P0-03 — Baseline snapshot**
- Record current `git status`, `git log -1`, `dotnet --info`, Python version, full unit commands and hashes of changed files. Avoid reset/clean.
- Preserve independent proof of `326 passed, 2 skipped` Python and `334 passed` .NET from shared audit, then update with fresh numbers only after rerun.

## 4. Sprints with deliverables (target durations, revise based on measured blockers)

| Sprint | Goal | Founder delivers | QA delivers | Release gate |
|---|---|---|---|---|
| S0 (days 1–2) | stabilize existing REVA | scoped wake fix + shutdown instrumentation | unit regression, real close/PID proof | G0 |
| S1 (days 3–5) | Windows audible loop | provider contract; TTS enabled with mute and fallback; session state machine | voice fixtures and missing-provider tests | no fake speech success |
| S2 (days 6–10) | natural Windows conversation | mic→STT→LLM→TTS, interruption, error recovery, latency logs | 100-turn eval, real mic and barge-in | R1 |
| S3 (days 11–15) | Android standalone voice UI | Kotlin Compose, local STT/TTS, typed history, permission flows | emulator and real phone matrix | internal APK installs |
| S4 (days 16–20) | secure Android pairing | gateway with TLS/auth, QR pairing, revoke, connection indicator | wrong-peer, revocation, replay, MITM negative | narrow gateway approved |
| S5 (days 21–30) | Android-to-PC cross-device loop | remote voice event flow, safe PC Calculator action, idempotency | phone→PC E2E and network drops | R2 |
| S6 (days 31–45) | full beta data+standalone | provider no-PC mode, memory CRUD/sync+tombstones, Android offline | no-PC, offline conflict and permissions suites | R3 |
| S7 (not date-guaranteed) | release engineering | Windows installer, signed Android builds, upgrade path, docs | clean installations, security review, performance, accessibility | R4 |

These estimates are planning targets and depend heavily on actual provider behavior, smartphone availability, and packaging constraints. No deadline overrides a security gate.

## 5. Test pyramid and responsibility

**Developer-owned automated tests:**
- Python pytest unit/security/contract/integration/E2E and synthetic audio fixtures; run existing suites first.
- .NET unit tests for lifecycle, wake-word resolution, approvals and UI view models; reuse real E2E scripts.
- Android Kotlin unit tests for Compose state, permission gate, provider selection and service lifecycle.
- Schema/OpenAPI contract tests for Windows/Android and Core event compatibility.

**QA-owned automation and adversarial scenarios:**
- 100 voice recordings with expected transcripts/action classifications; fixtures must be consented/synthetic and legally usable. Include silence, noise, accents, long speech, interrupted TTS, double talk, no mic, network drop, provider timeout.
- Simulated invalid tool proposals, injection, stale approvals and duplicated packets.
- UI automation on Windows and Android; manual hardware-only scenarios clearly marked separately.
- No-PC standalone APK tests and paired PC action tests; key revocation and permission refusal.
- Regression dashboard per branch/commit with failure reproduction steps and per-suite duration.

**Joint release validation:** real mic/speaker, Android battery/thermal, Windows clean-machine packaging, signed APK/AAB upgrades, memory export and full local deletion, data-plane opt-out verification, security review.

## 6. Cross-platform hardware/device test matrix

| Test class | Windows | Android | Expected outcome |
|---|---|---|---|
| Clean start without model | no local Ollama | no provider/PC | explicit unavailable not fake answer |
| Microphone permission denied | device unavailable | revoke RECORD_AUDIO | typed fallback works |
| Live mic STT | built-in & USB/Bluetooth if available | one real phone minimum | transcript quality recorded |
| TTS speaker interruption | Windows playback | Android TTS | obsolete epoch audio stops |
| Connectivity | disable NIC / unplug | airplane mode / Wi-Fi off | no phantom tool success |
| Resource exhaustion | slow model / busy CPU | thermal/battery saver | bounded queue and error |
| Security | unauthorized API request | rogue paired device | deny + audit |
| Shutdown | close WinUI | force-stop / background | no orphan mic, owned Core exits |
| Sync | offline edit then reconnect | offline edit then reconnect | deterministic merge/tombstone |
| Distribution | clean VM | signed APK on real device | launch/uninstall/upgrade |

**Android API coverage:** test at least one modern physical Android phone and representative emulator configurations, especially Android 12/13/14/15/16 microphone service behavior where test environments allow. Do not claim all OEM behaviors are covered by emulator tests.

## 7. Voice evaluation contract

Each voice fixture should store non-sensitive metadata:

```json
{
  "fixture_id": "V-001",
  "source": "synthetic_or_consented",
  "language": "en-US",
  "condition": "quiet",
  "expected_final_transcript": "Open calculator",
  "expected_intent": "windows.app.open",
  "expected_action_tier": "T1",
  "expected_policy": "allowed_if_target_available",
  "expected_speech": "verified_outcome_only",
  "should_execute": true
}
```

Add other categories: hesitation, restart, disfluency, sarcasm, “do not open Chrome”, “close …” spoken-only approval, background TV dialogue, two speakers, unknown app, noisy device loss, short trigger phrase. Record waveform IDs separately; no confidential clips in Git.

**Measurements:** endpoint delay, transcript error rate/intent accuracy, time to first audio, interrupt-to-silence, successful audio end, tool success/fail correctness, CPU/memory/battery. Separate mocked, opt-in real-model and real-hardware results.

## 8. Release blockers and stop conditions

- Red current tests or unknown dirty migrations.
- Wake-word integrity fail-open persists in HEAD.
- Mobile can trigger sensitive PC action without target confirmation.
- Deleted memory returns after offline sync.
- No actual audible reply on target device for claimed voice release.
- Android captures microphone outside allowed user-visible state.
- Android APK cannot operate at all when PC absent despite claiming standalone mode.
- Installer requires a source checkout/virtualenv on user machine.
- Provider cost cannot be measured or capped for public-user sessions.
- Failed tool call is announced as successful action.

## 9. Pilot/customer validation plan

**Week 1 (parallel with technical work):** 10 user interviews, 15–20 minutes each. Ask: What task do you speak into phone but finish on Windows? Which 3 actions do you repeat daily? What broke when you used Gemini/ChatGPT/device assistant? Would you permit paired PC control? What would make you stop using it? What is the financial/time value of a completed task?

**Weeks 2–3:** recruit five high-frequency Windows+Android users; watch each attempt an uncoached workflow. Do not count scripted internal demos as retention. Track task success, voluntary return, permission refusal, privacy concerns and failure recovery.

**Commercial checkpoint:** Build product before payments, but not before problem evidence. If users mainly want generic voice Q&A, do not compete by adding dozens of interchangeable voices; pivot to actionable desktop companion niche or portfolio-only.

## 10. Next 24 hours — instructions for two-person team

**Developer**
1. Make a read-only repo/branch/dirty-file inventory.
2. Isolate and commit wake-word fail-closed fix only after appropriate tests pass.
3. Capture a real shutdown trace, including owned and external process behavior.
4. Create issue cards for S1 voice state machine, cancellation, provider selection, speech playback.

**QA engineer**
1. Convert PRD `AC-001`, `AC-002`, `AC-003`, `AC-005`, `AC-009`, `AC-010`, `AC-011` into executable test skeletons.
2. Build a synthetic 20-clip initial STT/VAD/eval set with expected outcomes and audio privacy checklist.
3. Document target Windows and Android hardware/OS versions actually available to test.
4. Implement reporting template: `test_id, SHA, platform, fixture, expected, actual, artifact, verdict`.

**Definition of DONE today:** wake-word fix and evidence land cleanly *or* an explicit blocker with a reproducible test. No Android scaffolding is needed before S1 is working unless the team can run truly parallel isolated lanes.

## 11. One copyable agent handoff prompt

```text
You are REVA's implementation lead. Read in order:
01_REVA_MASTER_PRD.md
02_REVA_MASTER_ARD.md
03_REVA_ADR_DECISIONS.md
04_REVA_REQUIREMENTS_TRACEABILITY.md
05_REVA_EXECUTION_AND_QA.md

Before writing code: inspect the actual current repository, Git branch/HEAD, dirty files, existing tests, existing APIs and latest user-provided audit. Never claim a proposed feature exists merely because it is described in these docs.

Implement exactly the smallest unblocked ticket for the active release gate, beginning with P0-01 wake-word fail-closed hashing. Preserve unrelated dirty edits; do not reset or clean. Do not broaden the requested scope. Add positive/negative tests. Run the relevant suites in isolated test data directories. Report: changed files, requirement IDs, test commands/results, runtime verification, uncertainties, Git commit, and single next ticket. Do not merge `wip/slice-8a-draft` or enable unrestricted shell, cloud transmission, or Android background capture.
```


## 12. AI/ML agent vertical slice and QA ownership (extension v1.1)

- **Developer:** preserve the audited REVA branch, finish safety/lifecycle P0, implement `PlannerDecision` schema validator, real model selection, `CapabilityRegistry`, `PolicyBroker`, `WindowsUiInspector`, `WindowsActionExecutor`, `ActionVerifier` behind existing FastAPI/WinUI boundary. No new generic shell tool.
- **Tester:** build a 200-turn intent/schema corpus, 100 negative unauthorized commands, 20 supported Notepad app/UI fixture runs, three real GUI/physical sessions, then voice end-to-end and interruption tests. Compare actual device trace to spoken claim.
- **First new visible success:** “Open Notepad, type Meeting notes, verify text” in one trace, with graceful failure when UIA cannot target the field. This is a planning target, not a reported completed feature.
- **Android follows:** Kotlin APK voice and Intent launch; prove permission/lifecycle behavior, and only later screen actions under store-policy-reviewed scopes.
- **No-go:** model claims outcome without native evidence, unscoped screen capture, privileged UI bypass, generic `execute_os_command`, Android autonomous AccessibilityService workflow for general-purpose Play-distributed assistant.

**Specification files:** `06_REVA_AI_ML_ACTION_AGENT_PRD_ARD.md`, `07_REVA_NATIVE_AGENT_V1.proto`, and `08_REVA_PLANNER_DECISION.schema.json`. Reference `04_REVA_REQUIREMENTS_TRACEABILITY.md` section F for the individual QA obligation for each new numbered requirement.
