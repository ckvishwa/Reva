# REVA 2.0 coverage audit (Phase A)

Audit date 2026-10-15, main at 8f2924e. Source: `07_TRACEABILITY/v2_requirements.csv` (207 rows) and `tests/evidence/ledger.csv`. DONE = a ledger PASS row exists (open hardware rows noted). Nothing is DONE from code presence alone.

Totals: DONE 42, PARTIAL 41, NOT STARTED 123, DEFERRED 1

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
| AR-WIN-004 | R1 | S07 | NOT STARTED | B1 | NAudio capture, PTT, mute |
| AR-WIN-005 | R1 | S08 | NOT STARTED | B2 | avatar host |
| AR-WIN-006 | R1 | S08 | NOT STARTED | B2 | avatar host |
| AR-WIN-007 | R1 | S08 | NOT STARTED | B2 | avatar host |
| AR-WIN-008 | R1 | S09 | NOT STARTED | B3 | executor + grants |
| AR-WIN-009 | R1 | S09 | NOT STARTED | B3 | executor + grants |
| AR-WIN-010 | R1 | S07 | NOT STARTED | B1 | NAudio capture, PTT, mute |
| AR-WIN-011 | R2 | S23 | NOT STARTED | E3 | UIA |
| AR-WIN-012 | R1 | S10 | PARTIAL | D1-D5 | Finance page via Core API only; other domain pages in D |
| AR-WIN-013 | R4 | S25 | NOT STARTED | F1 | installer |
| AR-WIN-014 | R4 | S25 | NOT STARTED | F1 | installer |
| AR-WIN-015 | R1 | S07 | NOT STARTED | B1 | NAudio capture, PTT, mute |
| AR-WIN-016 | R2 | S23 | NOT STARTED | E3 | UIA |
| AR-AND-001 | R2 | S12 | NOT STARTED | C1 | Android voice/avatar |
| AR-AND-002 | R2 | S12 | NOT STARTED | C1 | Android voice/avatar |
| AR-AND-003 | R2 | S12 | NOT STARTED | C1 | Android voice/avatar |
| AR-AND-004 | R2 | S12 | NOT STARTED | C1 | Android voice/avatar |
| AR-AND-005 | R2 | S12 | NOT STARTED | C1 | Android voice/avatar |
| AR-AND-006 | R2 | S12 | PARTIAL | C2 | AND-1-manifest PASS for current manifest; re-verify after C2 intents |
| AR-AND-007 | R2 | S13 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-008 | R2 | S15 | NOT STARTED | C2 | phone->PC actions |
| AR-AND-009 | R2 | S11 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-010 | R2 | S11 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-011 | R3 | S21 | NOT STARTED | C3 | standalone/offline-lite |
| AR-AND-012 | R3 | S21 | NOT STARTED | C3 | standalone/offline-lite |
| AR-AND-013 | R3 | S17 | NOT STARTED | D3 | Health Connect |
| AR-AND-014 | R3 | S21 | NOT STARTED | C3/D6 | delete after reconnect in every domain |
| AR-AND-015 | R3 | S24 | NOT STARTED | C3/E4 | battery/thermal |
| AR-AND-016 | R4 | S26 | PARTIAL | F2 | debug APK only; signed APK/AAB in F2 |
| AR-AND-017 | R2 | S11 | DONE | - | AND-1-*, SYNC-1d-*, build.gradle.kts minSdk 31/target 36 |
| AR-AND-018 | R2 | S11 | PARTIAL | C1 | AR-DOM-015-android PASS for Kernel; capture/recognition lands C1 |
| AR-CORE-001 | R1 | S06 | PARTIAL | B1 | TTS epoch per session PASS; STT/model/tool cancellation wired in B1 |
| AR-CORE-002 | R1 | S06 | PARTIAL | B1 | stage timings exist; separate deadlines per stage to confirm in B1 |
| AR-CORE-003 | R1 | S05 | PARTIAL | B1 | providers/registry.py + Kokoro; Ollama default / hosted opt-in in B1.5/B1.7 |
| AR-CORE-004 | P0 | S03 | DONE | - | S03 env guard; AR-DATA-005/006; AR-CORE-009 ledger row |
| AR-CORE-005 | R1 | S06 | PARTIAL | B4 | session/turn ids on session events; correlation on all events audited in B4 |
| AR-CORE-006 | R1 | S06 | NOT STARTED | B4 |  |
| AR-CORE-007 | R2 | S13 | DONE | - | S03 env guard; AR-DATA-005/006; AR-CORE-009 ledger row |
| AR-CORE-008 | R3 | S20 | NOT STARTED | B4 |  |
| AR-CORE-009 | R1 | S06 | DONE | - | S03 env guard; AR-DATA-005/006; AR-CORE-009 ledger row |
| AR-CORE-010 | R1 | S20 | NOT STARTED | B4 |  |
| AR-CORE-011 | R4 | S27 | NOT STARTED | B4 |  |
| AR-CORE-012 | R1 | S06 | PARTIAL | B4 | bounded queues exist in session/coordinator; saturation tests + doc missing |
| AR-CORE-013 | R4 | S27 | NOT STARTED | B4 |  |
| AR-VA-001 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-002 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-003 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-004 | R1 | S06 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-VA-005 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-006 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-007 | R1 | S07 | PARTIAL | B1 | S06 fixture clips for CI; physical-mic suite with opt-in arrives B1 |
| AR-VA-008 | R1 | S05 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-VA-009 | R1 | S08 | NOT STARTED | B2 | avatar |
| AR-VA-010 | R1 | S08 | NOT STARTED | B2 | avatar |
| AR-VA-011 | R1 | S08 | NOT STARTED | B2 | avatar |
| AR-VA-012 | R1 | S08 | NOT STARTED | B2 | avatar |
| AR-VA-013 | R3 | S24 | NOT STARTED | E4 |  |
| AR-VA-014 | R3 | S24 | NOT STARTED | E4 |  |
| AR-VA-015 | R3 | S24 | NOT STARTED | E4 |  |
| AR-VA-016 | R4 | S27 | PARTIAL | E4 | stage timings for stt/model/tool/tts/ack exist; speech-end and first-sample points pending |
| AR-VA-017 | R4 | S27 | NOT STARTED | E4 |  |
| AR-VA-018 | R1 | S07 | NOT STARTED | B1 | capture/STT path |
| AR-VA-019 | R1 | S06 | PARTIAL | B1 | session events carry timings; cancel id and sequence to confirm |
| AR-VA-020 | R1 | S05 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-VA-021 | R1 | S05 | PARTIAL | B1 | first-audio muted PASS 430 ms, stop PASS, orphans PASS; speaker run + STT CER NEEDS_HARDWARE; blind comparison NOT_APPLICABLE (B0) |
| AR-VA-022 | R1 | S06 | DONE | - | S06-per-session-epoch, VOICE-1 kokoro-real/e2e, manifest refusals, S06-stage-timings |
| AR-LANG-001 | R1 | S07 | PARTIAL | B1 | normalizer takes finals; STT path in B1 |
| AR-LANG-002 | R1 | S06 | DONE | - | S06-normalizer (114 tests), S06-ack-first |
| AR-LANG-003 | R1 | S09 | NOT STARTED | B3 | rules/ladder/authorize |
| AR-LANG-004 | R1 | S09 | NOT STARTED | B3 | rules/ladder/authorize |
| AR-LANG-005 | R1 | S06 | PARTIAL | B0/B1 | S06-dialogue-state PASS; at-rest encryption B0; reference()/accept_proposal wiring B1.3 |
| AR-LANG-006 | R1 | S09 | NOT STARTED | B3 | rules/ladder/authorize |
| AR-LANG-007 | R1 | S09 | NOT STARTED | B3 | rules/ladder/authorize |
| AR-LANG-008 | R1 | S09 | NOT STARTED | B3 | rules/ladder/authorize |
| AR-LANG-009 | R1 | S10 | NOT STARTED | B3 | gap (spec S10): templates + number check folded into B3 |
| AR-LANG-010 | R1 | S06 | DONE | - | S06-normalizer (114 tests), S06-ack-first |
| AR-LANG-011 | R1 | S10 | NOT STARTED | D1 | gap (spec S10): grounded answers folded into D1 Memory |
| AR-LANG-012 | R1 | S10 | NOT STARTED | B3 | gap (spec S10): templates + number check folded into B3 |
| AR-LANG-013 | R1 | S10 | NOT STARTED | B1 | gap (spec S10): spoken rewrite + chunking with turn_epoch folded into B1.2 |
| AR-LANG-014 | R1 | S07 | NOT STARTED | B1 | TurnEvent recording |
| AR-LANG-015 | R2 | S12 | NOT STARTED | C1/C3 | shared artifacts on Android |
| AR-LANG-016 | R3 | S24 | NOT STARTED | E2 |  |
| AR-LANG-017 | R3 | S24 | NOT STARTED | E4 |  |
| AR-LANG-018 | R1 | S09 | NOT STARTED | B3 | rules/ladder/authorize |
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
| AR-DATA-018 | R1 | S07 | NOT STARTED | B1 | temp audio lifetime, no raw mic bytes in logs |
| AR-DATA-019 | R1 | S07 | NOT STARTED | B1 | temp audio lifetime, no raw mic bytes in logs |
| AR-DATA-020 | R4 | S27 | NOT STARTED | F3 |  |
| AR-AGT-001 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-002 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-003 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-004 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-005 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-006 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-007 | R2 | S15 | NOT STARTED | C2 |  |
| AR-AGT-008 | R2 | S21 | NOT STARTED | C2 |  |
| AR-AGT-009 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-010 | R4 | S27 | NOT STARTED | B3 | gap: action ledger built with the Activity page in B3; hardened in F3 |
| AR-AGT-011 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-012 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-013 | R1 | S07 | NOT STARTED | B1 | Ollama model eval |
| AR-AGT-014 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-015 | R1 | S09 | NOT STARTED | B3 | policy/executor; reva_core/policy and tools hold READMEs only |
| AR-AGT-016 | R2 | S15 | NOT STARTED | B3 | executor grant binding (Windows) in B3; remote in C2 |
| AR-AGT-017 | R2 | S15 | NOT STARTED | B3 | executor grant binding (Windows) in B3; remote in C2 |
| AR-AGT-018 | R2 | S15 | PARTIAL | B3 | Kernel registry has no money movement (AR-DOM-006); registry absence test over every registry in B3 |
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
| FR-AV-001 | R1 | S08 | NOT STARTED | B2 |  |
| FR-AV-002 | R1 | S08 | NOT STARTED | B2 |  |
| FR-AV-003 | R1 | S08 | NOT STARTED | B2 |  |
| FR-AV-004 | R1 | S08 | NOT STARTED | B2 |  |
| FR-AV-005 | R1 | S08 | NOT STARTED | B2 |  |
| FR-AV-006 | R1 | S08 | NOT STARTED | B2 |  |
| FR-AV-007 | R2 | S12 | NOT STARTED | C1 |  |
| FR-AV-008 | R3 | S24 | NOT STARTED | E4 |  |
| FR-DOM-001 | R1 (Win) / R2 (Android) | S10 | PARTIAL | D1-D6 | Finance PASS on both devices; other 7 domains pending |
| FR-DOM-002 | R1/R2 | S10 | PARTIAL | D1-D6 | Finance PASS on both devices; other 7 domains pending |
| FR-DOM-003 | R1 | S10 | PARTIAL | D1-D6 | Finance PASS on both devices; other 7 domains pending |
| FR-DOM-004 | R1 | S10 | NOT STARTED | B3 | gap (spec S10): voice entry + confirmation + answers with numbers (Finance first) |
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
| FR-LNG-001 | R1 | S09 | NOT STARTED | B3 |  |
| FR-LNG-002 | R1 | S09 | NOT STARTED | B3 |  |
| FR-LNG-003 | R1 | S10 | PARTIAL | B1/B3 | dialogue state PASS (S06); wiring in B1.3 |
| FR-LNG-004 | R1 | S10 | NOT STARTED | B3 |  |
| FR-LNG-005 | R1 | S05 | DEFERRED | - | Revi voice blocked (CLAUDE.md); Kokoro af_heart is the voice; no second voice to switch to |
| FR-LNG-006 | R3 | S24 | NOT STARTED | E2 |  |
| NFR-017 | R1 | S04 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
| NFR-018 | R1 | S04 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
| NFR-019 | R1 | S08 | NOT STARTED | B2 |  |
| NFR-020 | R4 | S27 | PARTIAL | F3 | see AR-DOM-011 |
| NFR-021 | R3 | S17 | NOT STARTED | D3/B3 | Health eval D3; Finance number accuracy B3 |
| NFR-022 | R3 | S14 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
| NFR-023 | R1 | S11 | DONE | - | AR-DOM-002, conformance Rust/Python/Kotlin, AR-DATA-011, AND-1-manifest |
