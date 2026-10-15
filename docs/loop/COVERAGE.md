# REVA 2.0 coverage audit (Phase A)

Audit date 2026-10-15 (updated after B0, B1a-d, B2a-c; main at 0c39678). Source: `07_TRACEABILITY/v2_requirements.csv` (207 rows) and `tests/evidence/ledger.csv`. DONE = a ledger PASS row exists (open hardware rows noted). Nothing is DONE from code presence alone.

Totals (200 of the 207 rows matched by pattern): DONE 76, PARTIAL 48, NOT STARTED 75, DEFERRED 1

Loop slices: B0-B4 Windows, C1-C3 phone, D1-D6 domains, E1-E4, F0-F3. "-" = nothing left.

## Gaps folded into slices

- Spec slice S10 rows had no home in the loop (AR-LANG-009/011/012/013, FR-LNG-003/004, FR-DOM-004/005, AR-DOM-005, FR-MEM-*): templates + number check + domain voice entry/answers go to B3, spoken rewrite/chunking to B1.2, grounded Memory answers to D1.
- AR-AGT-010 action ledger: built with the Activity page in B3.
- AR-SYS-002/003/004, AR-CORE-005, AR-DATA-009: audit items added to B4.
- AR-REL-002: confirm CI 5/5 on main in the first PR.
- Ledger FAIL/NEEDS_HARDWARE rows carried: AR-VA-021 (first-audio FAIL superseded by S06-first-audio-muted PASS; speaker run and STT CER open), SYNC-1e hardware.

## Rows

| ID | Stage | Spec slice | Status | Loop slice | Evidence / gap |
|---|---|---|---|---|---|
| AR-SYS-001 | P0 | S03 | DONE | - | INT-1-python/dotnet suites green on integration/alpha-2; S03 baseline |
| AR-SYS-002 | R1 | S03 | PARTIAL | B4 | Core: tests/security/test_domains_boundary.py; no guard yet for desktop/android import graph |
| AR-SYS-003 | R1 | S06 | PARTIAL | B4 | session-event schema + S06 events carry ids; audit every cross-process message |
| AR-SYS-004 | R1 | S03 | PARTIAL | B4 | CI contracts lane checks the copy; generated C#/Kotlin types not verified |
| AR-SYS-005 | R2 | S14 | DONE | - | sync_peers.rs + tests/gateway: signed batches only, no direct writes (AR-DATA-006/015) |
| AR-SYS-006 | R1 | S06 | PARTIAL | B1 | S06-stage-timings, session ids; UI->executor->audit chain lands with B3 |
| AR-WIN-001 | P0 | S01 | DONE | - | ledger PASS; wake-word-with-mic row NEEDS_HARDWARE (B1.6) |
| AR-WIN-002 | P0 | S02 | DONE | - | ledger PASS; wake-word-with-mic row NEEDS_HARDWARE (B1.6) |
| AR-WIN-003 | R1 | S07 | PARTIAL | B1 | Finance VM only (ledger row); audio/avatar work lands B1/B2 |
| AR-WIN-004 | R1 | S07 | DONE | - | B1b/B2c tests; hardware row AR-WIN-004-hardware open |
| AR-WIN-005 | R1 | S08 | PARTIAL | B2 | local flush on PTT press + epoch cut tested; 300 ms p95 on speakers open (hardware) |
| AR-WIN-006 | R1 | S08 | DONE | - | B2b browser tests + B2c host policy; real launch ready |
| AR-WIN-007 | R1 | S08 | PARTIAL | B2 | 60 fps cap + pause when hidden tested; <15% GPU on reference laptop open (hardware) |
| AR-WIN-008 | R1 | S09 | DONE | - | B3c-executor-refuses-bad-grants; B3c-grant-verify-cross-language (same 14 vectors in Python and C#) |
| AR-WIN-009 | R1 | S09 | DONE | - | B3c-false-success-0-of-100; B3c-reply-from-executor; hardware rows B3c-hw-* still NEEDS_HARDWARE |
| AR-WIN-010 | R1 | S07 | DONE | - | Ctrl+Space hook ignores injected keys; hardware row open |
| AR-WIN-011 | R2 | S23 | NOT STARTED | E3 | UIA |
| AR-WIN-012 | R1 | S10 | PARTIAL | D1-D5 | Finance page via Core API only; other domain pages in D |
| AR-WIN-013 | R4 | S25 | NOT STARTED | F1 | installer |
| AR-WIN-014 | R4 | S25 | NOT STARTED | F1 | installer |
| AR-WIN-015 | R1 | S07 | DONE | - | mic/speaker mute, device select, device loss -> idle; unplug test open (hardware) |
| AR-WIN-016 | R2 | S23 | NOT STARTED | E3 | UIA |
| AR-AND-001 | R2 | S12 | PARTIAL | C1 | C1a: deny, deny-forever, revoke-mid-session and background tests with fakes (VoiceControllerTest); real dialog on a phone is NEEDS_HARDWARE (C1-hw-*) |
| AR-AND-002 | R2 | S12 | PARTIAL | C1 | C1a: microphone foreground service, private, started only from the tap, Stop action (ManifestTest); API 31-36 emulators and a phone not run |
| AR-AND-003 | R2 | S12 | PARTIAL | C1 | C1a: availability policy and disclosed fallback tested with a capability mock; on-device recognition on a phone not run |
| AR-AND-004 | R2 | S12 | PARTIAL | C1 | C1a/b: recognizer, service, speaker released on every ending (fake leak tests); WebView destroyed on leaving Talk; real TTS/WebView leak profile on a phone is NEEDS_HARDWARE |
| AR-AND-005 | R2 | S12 | PARTIAL | C1 | C1b: avatar loads offline in a locked-down WebView (verified on an API 36 emulator: ready report, rendered pose, no network); mouth from played-audio envelope tested on the JVM; interrupt timing and airplane-mode launch on a phone are NEEDS_HARDWARE |
| AR-AND-006 | R2 | S12 | PARTIAL | C2 | AND-1-manifest PASS for current manifest; re-verify after C2 intents |
| AR-AND-007 | R2 | S13 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-008 | R2 | S15 | PARTIAL | C2 | C2a/b/c-1: PC side, desktop pickup and the phone sender done (signed requests, same-id retry, evidence-only success, phone cannot approve); phone-side actions (alarm/reminder/calendar/share/open) and hardware rows pending |
| AR-AND-009 | R2 | S11 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-010 | R2 | S11 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-011 | R3 | S21 | NOT STARTED | C3 | standalone/offline-lite |
| AR-AND-012 | R3 | S21 | NOT STARTED | C3 | standalone/offline-lite |
| AR-AND-013 | R3 | S17 | NOT STARTED | D3 | Health Connect |
| AR-AND-014 | R3 | S21 | NOT STARTED | C3/D6 | delete after reconnect in every domain |
| AR-AND-015 | R3 | S24 | NOT STARTED | C3/E4 | battery/thermal |
| AR-AND-016 | R4 | S26 | PARTIAL | F2 | debug APK only; signed APK/AAB in F2 |
| AR-AND-017 | R2 | S11 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-018 | R2 | S11 | PARTIAL | C1 | C1a: StrictMode (debug) and no blocking in the controller; jank trace on a phone is NEEDS_HARDWARE |
| AR-CORE-001 | R1 | S06 | PARTIAL | B1 | TTS and STT/model stages cancelled by epoch in the pipeline; tool stage arrives with S09 |
| AR-CORE-002 | R1 | S06 | PARTIAL | B1 | stage timings exist; separate deadlines per stage to confirm in B1 |
| AR-CORE-003 | R1 | S05 | PARTIAL | B1 | registry + Kokoro + opt-in Anthropic provider; selection by capability for all kinds continues |
| AR-CORE-004 | P0 | S03 | DONE | - | S03 env guard; AR-DATA-005/006; AR-CORE-009 ledger row |
| AR-CORE-005 | R1 | S06 | PARTIAL | B4 | session/turn ids on session events; correlation on all events audited in B4 |
| AR-CORE-006 | R1 | S06 | DONE | - | B4-schema-major; supported/unsupported version API regressions |
| AR-CORE-007 | R2 | S13 | DONE | - | S03 env guard; AR-DATA-005/006; AR-CORE-009 ledger row |
| AR-CORE-008 | R3 | S20 | PARTIAL | B4 | B4-config-precedence tests: defaults/file/env/arguments; vault precedence works with injected stores, not yet injected by production startup |
| AR-CORE-009 | R1 | S06 | DONE | - | S03 env guard; AR-DATA-005/006; AR-CORE-009 ledger row |
| AR-CORE-010 | R1 | S20 | PARTIAL | G4 | filter exists and is tested at the SDK boundary; no domain context is passed to the cloud path yet, so it is enforced only when the context builder lands (G4). The spoken transcript is sent whenever cloud is on (disclosed) |
| AR-CORE-011 | R4 | S27 | DONE | - | B4-migrations-reversible; snapshot retention, safety rollback copy, atomic script/version row and forced-failure restore tests |
| AR-CORE-012 | R1 | S06 | DONE | - | B4-bounded-queues; saturation/expiry and API chunked-size regressions; docs/architecture/bounded-queues.md |
| AR-CORE-013 | R4 | S27 | DONE | - | B4-telemetry; off/redacted/removable tests including concurrent writer/delete and deletion failure |
| AR-VA-001 | R1 | S07 | DONE | - | NAudio capture/playback behind interfaces |
| AR-VA-002 | R1 | S07 | DONE | - | bounded buffers, overlong utterances discarded whole |
| AR-VA-003 | R1 | S07 | DONE | - | one mic owner via arbiter |
| AR-VA-004 | R1 | S06 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-VA-005 | R1 | S07 | DONE | - | only final transcript reaches the router |
| AR-VA-006 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-007 | R1 | S07 | PARTIAL | B1 | fixture clips for CI; physical-mic suite via STT benchmark tool (hardware) |
| AR-VA-008 | R1 | S05 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-VA-009 | R1 | S08 | DONE | - | avatar mirrors host state incl. approval |
| AR-VA-010 | R1 | S08 | PARTIAL | B2 | offset estimator + delay setting built; 100 ms p95 on speakers open (hardware) |
| AR-VA-011 | R1 | S08 | DONE | - | mood engine + page + host enforce verified_outcome+action_id |
| AR-VA-012 | R1 | S08 | DONE | - | Settings > Avatar: off, reduced motion, quality |
| AR-VA-013 | R3 | S24 | NOT STARTED | E4 |  |
| AR-VA-014 | R3 | S24 | NOT STARTED | E4 |  |
| AR-VA-015 | R3 | S24 | NOT STARTED | E4 |  |
| AR-VA-016 | R4 | S27 | PARTIAL | E4 | stage timings for stt/model/tool/tts/ack exist; speech-end and first-sample points pending |
| AR-VA-017 | R4 | S27 | NOT STARTED | E4 |  |
| AR-VA-018 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-019 | R1 | S06 | PARTIAL | B1 | session events carry timings; cancel id and sequence to confirm |
| AR-VA-020 | R1 | S05 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-VA-021 | R1 | S05 | PARTIAL | B1 | first audio 430 ms muted PASS; speaker run, STT CER open (hardware) |
| AR-VA-022 | R1 | S06 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-LANG-001 | R1 | S07 | DONE | - | final transcripts only |
| AR-LANG-002 | R1 | S06 | DONE | - | S06-normalizer (114 tests), S06-ack-first |
| AR-LANG-003 | R1 | S09 | DONE | - | B3b-rule-fast-path; B3d adds assistant.stop/repeat/undo rules |
| AR-LANG-004 | R1 | S09 | DONE | - | B3b-entity-ladder (vector rung shadow-only) |
| AR-LANG-005 | R1 | S06 | DONE | - | reference() and accept_proposal() wired through the router; at-rest DPAPI (B0) |
| AR-LANG-006 | R1 | S09 | NOT STARTED | planner | planner is not on main |
| AR-LANG-007 | R1 | S09 | DONE | - | B3a-authorize-pure; C1c: Kotlin authorize() equals the Python one on 1006 generated cases |
| AR-LANG-008 | R1 | S09 | DONE | - | tests/unit/test_policy_authorize.py::test_leftover_content_words_block_the_action; test_normalizer filler fixtures |
| AR-LANG-009 | R1 | S10 | PARTIAL | D1 | action outcome templates by status done (B3c-reply-from-executor); per-intent x status coverage test for the other domains with each domain |
| AR-LANG-010 | R1 | S06 | DONE | - | S06-normalizer (114 tests), S06-ack-first |
| AR-LANG-011 | R1 | S10 | NOT STARTED | D1 | gap (spec S10): grounded answers folded into D1 Memory |
| AR-LANG-012 | R1 | S10 | NOT STARTED | B3 | gap (spec S10): templates + number check folded into B3 |
| AR-LANG-013 | R1 | S10 | NOT STARTED | B1 | gap (spec S10): spoken rewrite + chunking with turn_epoch folded into B1.2 |
| AR-LANG-014 | R1 | S07 | DONE | - | redacted TurnEvent recording + failed-turn fixtures |
| AR-LANG-015 | R2 | S12 | PARTIAL | C3 | C1b/c: mood rules, capability registry and rule fast path (non-app rules) shared with the PC and checked by fixtures the Python code writes (664 mood, 1006 authorize, 75 rule cases); normalizer (money, dates) and the app-name ladder are not ported: needed for phone expense entry in C3 |
| AR-LANG-016 | R3 | S24 | NOT STARTED | E2 |  |
| AR-LANG-017 | R3 | S24 | NOT STARTED | E4 |  |
| AR-LANG-018 | R1 | S09 | DONE | - | B3b-forbidden-refusals |
| AR-DATA-001 | R2 | S13 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-002 | R2 | S13 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-003 | R2 | S13 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-004 | R2 | S13 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-005 | R2 | S13 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-006 | R2 | S13 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-007 | R3 | S22 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-008 | R3 | S22 | NOT STARTED | E1 | relay |
| AR-DATA-009 | R4 | S27 | NOT STARTED | B4 | security logs with requesting device |
| AR-DATA-010 | R2 | S14 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-011 | R2 | S14 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-012 | R3 | S20 | PARTIAL | D6 | Finance switch enforced send+receive (AR-DATA-003); all domains in D6 |
| AR-DATA-013 | R3 | S22 | NOT STARTED | E1 | relay |
| AR-DATA-014 | R3 | S22 | NOT STARTED | E1 | relay |
| AR-DATA-015 | R2 | S14 | DONE | - | tests/gateway, sync_peers.rs (ledger); scopes extend in C2/D6 |
| AR-DATA-016 | R4 | S27 | NOT STARTED | D6 | wipe/export all domains |
| AR-DATA-017 | R4 | S27 | NOT STARTED | D6 | wipe/export all domains |
| AR-DATA-018 | R1 | S07 | DONE | - | temp audio deleted after use; scratch swept at start |
| AR-DATA-019 | R1 | S07 | DONE | - | no raw audio in logs |
| AR-DATA-020 | R4 | S27 | NOT STARTED | F3 |  |
| AR-AGT-001 | R1 | S09 | DONE | - | B3a-registry-absence; unknown and forbidden capabilities refused by authorize() |
| AR-AGT-002 | R1 | S09 | DONE | - | B3a-authorize-pure (4000 random proposals never crash) |
| AR-AGT-003 | R1 | S09 | DONE | - | tier read only from the registry; a Proposal carries no tier (B3a-authorize-pure) |
| AR-AGT-004 | R1 | S09 | DONE | - | B3a-signed-grants, B3a-t2-click-only: replay and substitution refused |
| AR-AGT-005 | R1 | S09 | DONE | - | B3c-open-needs-window, B3c-close-verified-when-gone, B3c-expense-confirm-card (kernel_event) |
| AR-AGT-006 | R1 | S09 | DONE | - | B3a-t2-click-only: speech-only, stale and substituted approvals refused |
| AR-AGT-007 | R2 | S15 | NOT STARTED | C2 |  |
| AR-AGT-008 | R2 | S21 | NOT STARTED | C2 |  |
| AR-AGT-009 | R1 | S09 | NOT STARTED | planner | planner loop exists only on wip/planner-reasoning, not on main |
| AR-AGT-010 | R4 | S27 | PARTIAL | F3 | B3a-ledger-append-only + B3c-activity-page; reconciliation hardening in F3 |
| AR-AGT-011 | R1 | S09 | NOT STARTED | planner | planner is not on main |
| AR-AGT-012 | R1 | S09 | DONE | - | B3b-rule-fast-path |
| AR-AGT-013 | R1 | S07 | DONE | - | 20-prompt eval on 3 local models; qwen2.5:3b chosen |
| AR-AGT-014 | R1 | S09 | DONE | - | B3a-false-success; B3c-reply-from-executor: model text never reaches an outcome |
| AR-AGT-015 | R1 | S09 | NOT STARTED | planner | untrusted-text delimiting and injection corpus arrive with the planner |
| AR-AGT-016 | R2 | S15 | PARTIAL | C2 | Windows executor validates grants (B3c); Android executor in C2 |
| AR-AGT-017 | R2 | S15 | NOT STARTED | B3 | executor grant binding (Windows) in B3; remote in C2 |
| AR-AGT-018 | R2 | S15 | PARTIAL | C3 | B3a-registry-absence covers both Python copies; Android registry copy in C3 |
| AR-AGT-019 | R3 | S21 | NOT STARTED | D1 |  |
| AR-AGT-020 | R4 | S27 | NOT STARTED | F3 | benchmarks; fixtures separated |
| AR-AGT-021 | R4 | S27 | NOT STARTED | F3 | benchmarks; fixtures separated |
| AR-AGT-022 | R4 | S27 | NOT STARTED | B4 | versioned artifacts |
| AR-DOM-001 | R1 | S04 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-DOM-002 | R1 | S04 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-DOM-003 | R1 | S04 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-DOM-004 | R1 | S04 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-DOM-005 | R1 | S10 | NOT STARTED | D1 | Memory benchmark |
| AR-DOM-006 | R2 | S14 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-DOM-007 | R2 | S17 | NOT STARTED | D3 |  |
| AR-DOM-008 | R2 | S14 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-DOM-009 | R3 | S20 | NOT STARTED | B4/D6 | consent filter + network capture |
| AR-DOM-010 | R3 | S20 | PARTIAL | D2/D6 | Finance only PASS; other domains in D |
| AR-DOM-011 | R4 | S27 | PARTIAL | D6/F3 | desktop p95 PASS; phone NEEDS_HARDWARE |
| AR-DOM-012 | R3 | S16 | PARTIAL | D2/D6 | Finance only PASS; other domains in D |
| AR-DOM-013 | R3 | S16 | PARTIAL | D2/D6 | Finance only PASS; other domains in D |
| AR-DOM-014 | R1 | S04 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-DOM-015 | R2 | S14 | DONE | - | ledger PASS (Finance; conformance Rust/Python/Kotlin) |
| AR-REL-001 | P0 | S00 | DONE | - | docs/archive S00; tests/evidence/ledger.csv |
| AR-REL-002 | R1 | S03 | PARTIAL | B0 | CI lanes exist; confirm 5/5 green on main in first PR |
| AR-REL-003 | R1 | S03 | DONE | - | docs/archive S00; tests/evidence/ledger.csv |
| AR-REL-004 | R4 | S25 | NOT STARTED | F1 |  |
| AR-REL-005 | R4 | S25 | NOT STARTED | F1 |  |
| AR-REL-006 | R4 | S24 | NOT STARTED | E4 |  |
| AR-REL-007 | R3 | S24 | PARTIAL | E4 | S06 muted timings; per device/provider table pending |
| AR-REL-008 | R4 | S27 | NOT STARTED | E4/F3 |  |
| AR-REL-009 | R4 | S25 | NOT STARTED | F1 |  |
| AR-REL-010 | R4 | S27 | PARTIAL | F3 | FIN-2-narrator NEEDS_HARDWARE; other pages pending |
| FR-AV-001 | R1 | S08 | DONE | - | avatar on Talk screen (placeholder VRM; Blender model F0) |
| FR-AV-002 | R1 | S08 | DONE | - | six poses mirror state |
| FR-AV-003 | R1 | S08 | DONE | - | mouth from the audio actually played |
| FR-AV-004 | R1 | S08 | DONE | - | interrupt closes mouth and audio together |
| FR-AV-005 | R1 | S08 | DONE | - | verified_outcome rule |
| FR-AV-006 | R1 | S08 | DONE | - | off / reduced motion |
| FR-AV-007 | R2 | S12 | PARTIAL | C1 | C1b: same avatar package and mood rules on Android; emulator shows the pose; phone airplane-mode launch is NEEDS_HARDWARE |
| FR-AV-008 | R3 | S24 | NOT STARTED | E4 |  |
| FR-DOM-001 | R1 (Win) / R2 (Android) | S10 | PARTIAL | D1-D6 | Finance PASS on both devices; other 7 domains pending |
| FR-DOM-002 | R1/R2 | S10 | PARTIAL | D1-D6 | Finance PASS on both devices; other 7 domains pending |
| FR-DOM-003 | R1 | S10 | PARTIAL | D1-D6 | Finance PASS on both devices; other 7 domains pending |
| FR-DOM-004 | R1 | S10 | PARTIAL | D1 | Finance voice expense with confirm card (B3c); other domains later; hardware row B3c-hw-voice-expense-both-devices open |
| FR-DOM-005 | R1 | S10 | NOT STARTED | B3 | gap (spec S10): voice entry + confirmation + answers with numbers (Finance first) |
| FR-DOM-006 | R3 | S20 | NOT STARTED | B4/D6 |  |
| FR-DOM-007 | R3 | S20 | PARTIAL | D6 | Finance export/import PASS; other domains pending |
| FR-DOM-008 | R3 | S20 | PARTIAL | D6 | Finance export/import PASS; other domains pending |
| FR-DOM-009 | R3 | S20 | PARTIAL | D1-D6 | Finance PASS on both devices; other 7 domains pending |
| FR-MEM-001 | R1 | S10 | NOT STARTED | D1 |  |
| FR-MEM-002 | R1 | S10 | NOT STARTED | D1 |  |
| FR-FIN-001 | R1 | S10 | PARTIAL | B3 | manual entry both devices PASS; voice entry in B3 |
| FR-FIN-002 | R3 | S16 | NOT STARTED | D2 |  |
| FR-FIN-003 | R3 | S16 | PARTIAL | D2 | CSV import + dedupe PASS (AR-DOM-012); OFX + per-bank mappings pending |
| FR-FIN-004 | all | S16 | DONE | - | AR-DOM-006 registry/source scan; re-checked in B3 |
| FR-HLT-001 | R3 | S17 | NOT STARTED | D3 |  |
| FR-HLT-002 | R3 | S17 | NOT STARTED | D3 |  |
| FR-HLT-003 | all | S17 | NOT STARTED | D3 |  |
| FR-COA-001 | R3 | S18 | NOT STARTED | D4 |  |
| FR-CAR-001 | R3 | S19 | NOT STARTED | D5 |  |
| FR-LRN-001 | R3 | S19 | NOT STARTED | D5 |  |
| FR-CYB-001 | R3 | S19 | NOT STARTED | D5 |  |
| FR-PER-001 | R3 | S18 | NOT STARTED | D4 |  |
| FR-TDY-001 | R3 | S16 | PARTIAL | B4/D2 | Finance-only Today PASS; all enabled domains in B4/D2 |
| FR-SYN-001 | R2 | S14 | PARTIAL | D1-D5 | Finance LAN sync PASS (SYNC-1, phone PASS); other domains as added |
| FR-SYN-002 | R3 | S22 | NOT STARTED | E1 |  |
| FR-LNG-001 | R1 | S09 | PARTIAL | D1 | open/close app, add expense, remember, recall, today, stop/repeat/undo; workout and reminder phrases arrive with D3/D4 |
| FR-LNG-002 | R1 | S09 | PARTIAL | D1 | apps ask (Did you mean...); category/person/item asks arrive with their domains |
| FR-LNG-003 | R1 | S10 | PARTIAL | B1/B3 | dialogue state PASS (S06); wiring in B1.3 |
| FR-LNG-004 | R1 | S10 | NOT STARTED | B3 |  |
| FR-LNG-005 | R1 | S05 | DEFERRED | - | Revi voice blocked (CLAUDE.md); Kokoro af_heart is the voice; no second voice to switch to |
| FR-LNG-006 | R3 | S24 | NOT STARTED | E2 |  |
| NFR-017 | R1 | S04 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
| NFR-018 | R1 | S04 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
| NFR-019 | R1 | S08 | PARTIAL | B2 | never blocks UI thread, 60 fps cap, paused when hidden; GPU profile open (hardware) |
| NFR-020 | R4 | S27 | PARTIAL | F3 | see AR-DOM-011 |
| NFR-021 | R3 | S17 | NOT STARTED | D3/B3 | Health eval D3; Finance number accuracy B3 |
| NFR-022 | R3 | S14 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
| NFR-023 | R1 | S11 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
