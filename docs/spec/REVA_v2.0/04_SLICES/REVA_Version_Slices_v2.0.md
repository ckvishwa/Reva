# REVA — Version Slices in Order v2.0

**Document ID:** REVA-SLICES-002 · **Version:** 2.0.2 · **Date:** 2026-10-12
Every slice is one shippable, tested increment with its own version tag. A slice starts only when the previous slice's exit check is green and recorded in the evidence ledger. Gates close phases. Avatar asset slices (A1–A4) and voice asset slices (V1–V4) run in parallel.

## Overview

| Order | Slice | Version tag | Phase | Gate |
|---|---|---|---|---|
| 1 | S00 Snapshot and archive | — | 0 Clean & merge | |
| 2 | S01 Wake-word fail-closed (P0-01) | — | 0 | |
| 3 | S02 Shutdown lifecycle proof (P0-02) | — | 0 | |
| 4 | S03 Repo restructure, CI, env guard, spec fix | v2.0.0-alpha.0 | 0 | **G0 / P0** |
| 5 | S04 Domain Kernel spike (Finance, Win + Android) | v2.0.0-alpha.1 | 1 Windows alpha | |
| 6 | S05 Provider registry + manifest-verified TTS (Revi or Kokoro) | v2.0.0-alpha.2 | 1 | |
| 7 | S06 Session + Corx turn engine + dialogue state | v2.0.0-alpha.3 | 1 | |
| 8 | S07 Real voice loop on hardware | v2.0.0-alpha.4 | 1 | |
| 9 | S08 Avatar in WebView2 + lip sync | v2.0.0-alpha.5 | 1 | |
| 10 | S09 NLU fast path + resolution ladder + authorize() + Notepad verified action | v2.0.0-alpha.6 | 1 | |
| 11 | S10 Memory + Finance core in Kernel, NLG templates + number check | v2.0.0-alpha.7 | 1 | **G1 / R1** |
| 12 | S11 Android shell + Kernel binding + offline Memory/Finance | v2.0.0-alpha.8 | 2 Android paired | |
| 13 | S12 Android voice + avatar | v2.0.0-alpha.9 | 2 | |
| 14 | S13 Pairing gateway, QR, revoke | v2.0.0-alpha.10 | 2 | |
| 15 | S14 LAN sync for Memory + Finance | v2.0.0-alpha.11 | 2 | |
| 16 | S15 Phone → PC action with PC approval | v2.0.0-alpha.12 | 2 | **G2 / R2** |
| 17 | S16 Finance full + Today v1 | v2.0.0-alpha.13 | 3 Domains | |
| 18 | S17 Health + Health Connect + safety eval | v2.0.0-alpha.14 | 3 | |
| 19 | S18 Coach + Personal | v2.0.0-alpha.15 | 3 | |
| 20 | S19 Learn + Career + Cyber | v2.0.0-alpha.16 | 3 | |
| 21 | S20 Privacy switches, export/delete, import | v2.0.0-alpha.17 | 3 | **G3** |
| 22 | S21 Standalone Android brain + offline-lite | v2.0.0-beta.1 | 4 Standalone & relay | |
| 23 | S22 Encrypted relay + adversarial gate | v2.0.0-beta.2 | 4 | |
| 24 | S23 Windows UIA inspect/click | v2.0.0-beta.3 | 4 | |
| 25 | S24 Reliability, performance, battery | v2.0.0-beta.4 | 4 | **G4 / R3** |
| 26 | S25 Windows installer + signing | v2.0.0-rc.1 | 5 Release | |
| 27 | S26 Android signed APK/AAB + Play declarations | v2.0.0-rc.2 | 5 | |
| 28 | S27 Security, accessibility, docs, final evidence | v2.0.0 | 5 | **G5 / R4** |
| ∥ | A1 Avatar concept + base mesh | — | parallel | |
| ∥ | A2 Rig + expressions | — | parallel | |
| ∥ | A3 Textures, MToon, VRM export | — | parallel | |
| ∥ | A4 VRMA clips + swap-in | asset v1.0 | parallel, before G2 | |
| ∥ | V1 Voice workspace merge + manifest provenance | — | parallel, before S05 | |
| ∥ | V2 Bakeoff close-out (English + Telugu, license check) | — | parallel, before S05 | |
| ∥ | V3 Revi model export + provider + voice gate | voice revi-1.0 | parallel, with S05 | |
| ∥ | V4 Revi default + Android playback path | voice revi-1.0 | parallel, before G1 | |

---

## Phase 0 — Clean and merge

### S00 Snapshot and archive
- **Scope:** record git status/HEAD/toolchains/test counts; tag `archive/pre-merge-2026-10-11` on every branch; bundles off-drive; locate surviving AuraO copies.
- **Reqs:** AR-REL-001, ARD-800 §2 steps 1, 3.
- **Exit:** snapshot file committed in `docs/archive/`; bundles verified with `git bundle verify`.

### S01 Wake-word fail-closed
- **Scope:** commit resolver fix + tests only (missing, invalid, mismatched, matching hash, empty dictionary).
- **Reqs:** AR-WIN-001, FR-019, AC-001.
- **Exit:** `dotnet test` green; `git show HEAD:` shows the guard; recorder not armed in negative tests.

### S02 Shutdown lifecycle proof
- **Scope:** move dirty shutdown edits to `archive/shutdown-wip`; implement owned vs external Core shutdown with PID evidence.
- **Reqs:** AR-WIN-002, AR-072, AC-010.
- **Exit:** 10 open/close cycles, PID diffs recorded, no orphan, external Core survives.

### S03 Repo restructure, CI, env guard, spec fix → **v2.0.0-alpha.0**
- **Scope:** move to `core/ kernel/ windows/ android/ avatar/ contracts/`; CI lanes skeleton; pytest env guard; this pack into `docs/ard/`, v1 into `docs/archive/`; delete `wip/slice-8a-draft`.
- **Reqs:** AR-CORE-004, AR-REL-002, AR-SYS-001.
- **Exit / G0:** clean status; Python and .NET suites at or above the 326/334 baseline; wake-word fix in HEAD.

## Phase 1 — Windows alpha (R1)

### S04 Domain Kernel spike → alpha.1
- **Scope:** `kernel/` crate with Finance (account, transaction, category) using the harvested SQLCipher/Credential Manager code; `KeyProvider` trait; UniFFI Python + Kotlin bindings; Android cross-build arm64-v8a + x86_64; conformance tests run 3 ways.
- **Reqs:** AR-DOM-001–004, AR-DOM-014, ADR-027/028.
- **Exit:** same suite green natively, via Python, via Kotlin on an emulator. **If SQLCipher on NDK fails:** execute ADR-027 fallback and record it.

### S05 Provider registry + manifest-verified TTS → alpha.2
- **Scope:** provider registry; TTS providers for Kokoro `af_heart` and Revi (engine from V2) with speak/stop/health; voices load only when the manifest hash matches; speaker mute. Revi becomes default only when V3's voice gate passes.
- **Reqs:** AR-CORE-003, AR-VA-008, AR-VA-020, AR-VA-021, FR-004, FR-LNG-005, ADR-025, ADR-040.
- **Exit:** real synthesis audible for both voices; interrupt with no overlap; zero orphan processes after kill; tampered model refused.

### S06 Session + Corx turn engine + dialogue state → alpha.3
- **Scope:** state machine, `turn_epoch`, deadlines, `/v1/voice/sessions` + WebSocket events, typed errors; Corx VAD/endpointing (~280 ms, pauses as follow-up turns); acknowledge-first; normalizer (money, numbers, dates, durations); dialogue state tracker with persistence; per-stage timings.
- **Reqs:** AR-CORE-001/002/005/006, AR-VA-004/019/022, AR-LANG-002/005/010, ADR-037.
- **Exit:** late-response injection, timeout, normalization, anaphora and restart-resume fixtures green; timings in every trace.

### S07 Real voice loop → alpha.4
- **Scope:** WASAPI capture → VAD → faster-whisper with vocabulary prompt → Ollama (model from eval) → Revi or Kokoro → speaker; push-to-talk hotkey; WER and latency re-benchmarked on the desk mic; TurnEvent recording.
- **Reqs:** FR-001–FR-010, AR-WIN-003/004/010/015, AR-AGT-013, AR-LANG-001/014.
- **Exit:** 3 recorded hardware runs; MET-02 measured; Stop and device-unplug behave.

### S08 Avatar → alpha.5
- **Scope:** `avatar/` package with placeholder VRM; WebView2 host; `avatar.state` from session; RMS lip sync; avatar off/reduced motion.
- **Reqs:** FR-AV-001–006, AR-WIN-005/006/007, AR-VA-009–012.
- **Exit:** offline load; lip-sync offset ≤ 100 ms p95; interrupt ≤ 300 ms p95; GPU under budget.

### S09 NLU fast path + authorize + verified action → alpha.6
- **Scope:** rule fast path; entity resolution ladder (vector shadow-only); planner fallback; pure `authorize()` returning `AuthorizationDecision`; capability registry v2; policy broker; grants; approval UI; executor evidence; "open Notepad, type text, verify".
- **Reqs:** AR-AGT-001–006/011/012/014/015, AR-WIN-008/009, AR-LANG-003/004/006/007/008/018, FR-LNG-001/002.
- **Exit:** false-success 0/100; forged/replayed grants denied; physical Notepad E2E recorded.

### S10 Memory + Finance core on Windows → alpha.7 · **G1 / R1**
- **Scope:** Memory domain in Kernel with approval, citations, abstention, hybrid retrieval; harvested benchmark; Finance screens; voice "I spent…" with confirmation; NLG templates for every outcome, grounded answers, number/claim check, spoken rewrite and chunking; Memory and Finance pages in WinUI.
- **Reqs:** AR-DOM-005, FR-MEM-001/002, FR-FIN-001, FR-DOM-001–005 (Windows), AR-LANG-009/011/012/013, FR-LNG-003/004.
- **Exit / G1:** ARD-100 §6 gate on hardware, 3 recorded runs; benchmark ≥ 9/10.

## Phase 2 — Android paired (R2)

### S11 Android shell + Kernel → alpha.8
- **Scope:** Compose app (Talk, Memory, Finance, Settings), minSdk 31/target 36; Kernel `.so`; Keystore key; offline Memory + Finance.
- **Reqs:** AR-AND-009/010/017/018, FR-051 (part).
- **Exit:** airplane-mode domain suite green on phone + emulator.

### S12 Android voice + avatar → alpha.9
- **Scope:** foreground voice service, permission flows, on-device STT check, TTS via `AudioTrack` envelope, avatar WebView.
- **Reqs:** AR-AND-001–005, FR-002, FR-011–013, FR-AV-007, AR-LANG-015.
- **Exit:** permission deny/revoke matrix; avatar offline; interrupt timing on phone.

### S13 Pairing → alpha.10
- **Scope:** gateway on PC, QR + fingerprint + signed challenge, device grants, revoke.
- **Reqs:** AR-DATA-001–006, AR-AND-007.
- **Exit:** MITM, replay, expired-code, revoked-device tests green.

### S14 LAN sync → alpha.11
- **Scope:** outbox, signed events, apply, tombstones, cursors for Memory + Finance.
- **Reqs:** AR-DATA-010/011/015, AR-DOM-008, FR-SYN-001.
- **Exit:** replay/reorder/offline-delete suites; AC-008, AC-018.

### S15 Phone → PC action → alpha.12 · **G2 / R2**
- **Scope:** phone voice → PC Core → phone TTS; "open Calculator on PC" with PC approval for T2.
- **Reqs:** AR-AND-008, AR-AGT-007/016, AC-009.
- **Exit / G2:** ARD-200 §6 gate on a physical phone.

## Phase 3 — Domains on both devices

### S16 Finance full + Today → alpha.13
- **Scope:** budgets, bills, recurring, net worth, CSV/OFX import; Today v1 on both apps.
- **Reqs:** FR-FIN-002/003, FR-TDY-001, AR-DOM-012/013.
- **Exit:** import fixtures; AC-022, AC-023.

### S17 Health → alpha.14
- **Scope:** Health domain; manual entry; Health Connect read-only (Android); safety routing + eval.
- **Reqs:** FR-HLT-001–003, AR-AND-013, AR-DOM-007, NFR-021.
- **Exit:** AC-020, AC-021; safety eval 100% on urgent set.

### S18 Coach + Personal → alpha.15
- **Reqs:** FR-COA-001, FR-PER-001.
- **Exit:** domain suites on both devices; journal local-only default verified.

### S19 Learn + Career + Cyber → alpha.16
- **Reqs:** FR-LRN-001, FR-CAR-001, FR-CYB-001.
- **Exit:** domain suites on both devices.

### S20 Privacy, export, delete, import → alpha.17 · **G3**
- **Scope:** per-domain switches; consent filter; export/delete everywhere; import for all domains.
- **Reqs:** FR-DOM-006–009, AR-CORE-010, AR-DOM-009/010, AR-DATA-012.
- **Exit / G3:** 8/8 domains offline on both devices (MET-15); network capture clean (AC-019); J-13, J-14.

## Phase 4 — Standalone and relay (R3)

### S21 Standalone Android brain → beta.1
- **Scope:** local brain with hosted provider (opt-in, disclosed), offline-lite mode, mode indicator.
- **Reqs:** AR-AND-011/012, FR-AI-024, AR-AGT-008, ADR-030.
- **Exit:** no-PC E2E; AC-006, AC-014.

### S22 Relay → beta.2
- **Scope:** group key at pairing; device-side encryption; Supabase mailbox; adversarial review.
- **Reqs:** AR-DATA-007/008/013/014, FR-SYN-002, ADR-031.
- **Exit:** relay dump shows ciphertext only; adversarial review passed, or relay stays disabled and the slice records it.

### S23 Windows UIA → beta.3
- **Scope:** inspect window, click named control, set text; redaction; secure desktop fail-closed.
- **Reqs:** FR-AI-011/012/014, AR-WIN-011/016.
- **Exit:** stale/focus/DPI/locked-desktop tests; physical E2E.

### S24 Reliability and performance → beta.4 · **G4 / R3**
- **Scope:** failure injection, latency budgets, battery/thermal, viseme lip sync.
- **Reqs:** AR-REL-006/007, AR-AND-015, AR-VA-013–015, FR-AV-008, AR-LANG-016/017, FR-LNG-006.
- **Exit / G4:** reports recorded; MET-16 sync correctness.

## Phase 5 — Release (R4)

### S25 Windows installer → rc.1
- **Reqs:** AR-WIN-013/014, AR-REL-004/005/009, FR-057, AC-012.
- **Exit:** clean VM install/upgrade/uninstall with no repo or `.venv`.

### S26 Android release → rc.2
- **Reqs:** AR-AND-016, FR-058, AC-013; Play health-apps declaration.
- **Exit:** signed APK installs/upgrades keeping data; AAB validated.

### S27 Final → **v2.0.0 · G5 / R4**
- **Reqs:** AR-DATA-016/017/020, AR-REL-008/010, AR-AGT-010/020–022, NFR-010, NFR-016.
- **Exit:** security signoff; accessibility smoke; evidence ledger complete for every MUST.

## Parallel — Avatar asset (Blender)

| Slice | Scope | Exit |
|---|---|---|
| A1 | Original character concept, adult proportions, base mesh ≤ 50k tris | Turnaround renders approved |
| A2 | VRM humanoid rig; mouth `aa ih ou ee oh`; blinks; 5 emotions | Expressions preview in three-vrm |
| A3 | Textures ≤ 2048 px, MToon, VRM 1.0 export (Git LFS) | Loads offline in `avatar/` test page |
| A4 | VRMA clips: idle, listening, thinking, talking, approval, error; swap placeholder | AR-VA-010 re-run passes; ready before G2 |

## Parallel — Voice assets (Revi)

| Slice | Scope | Exit |
|---|---|---|
| V1 | Run `10_TOOLS/Merge-RevaVoiceWorkspace.ps1` (dry run, review plan, then `-Apply`); fill `source`, `license`, `provenance_status` for every manifest entry; delete `_to-delete\` after the repo builds | Source folder empty; manifest validates; no entry left TODO for Revi assets; named-person files only in `_excluded\` |
| V2 | Close the bakeoff: compare Chatterbox, XTTS-v2, IndexTTS2 (and Kokoro baseline) on English and Telugu scripts for quality, latency, interrupt, CPU/GPU need and **license for this use** | `docs/voice/bakeoff-decision.md` names the Revi engine and the Telugu verdict |
| V3 | Export the final Revi model + reference/style files; add to manifest with hashes; write the provider adapter; run the voice gate | AR-VA-020 and AR-VA-021 pass; voice revi-1.0 tagged |
| V4 | Make Revi default (FR-LNG-005); Android: stream Revi audio from the PC when paired, Android TTS when standalone unless the engine runs on-device | Settings voice switch works; G1 recording uses Revi |

