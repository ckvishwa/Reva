# MASTER LOOP progress

Resume command: "Resume MASTER LOOP from docs/loop/MASTER-LOOP-progress.md"

Last updated 2026-10-15, main at d384df2. Current phase: B closeout, then C (phone) in order C1 → C2 → C3. Order after C: D → G → E → F → H. Stop point: after C3 software, Phase C report, before D1.

| Slice | PR | Merge commit | CI lanes at merge | Findings fixed / left | Tests at merge | Open hardware rows | Pending tag | Status |
|---|---|---|---|---|---|---|---|---|
| Loop file | direct | 5c454c3 | docs only | - | - | - | - | done |
| A0 coverage audit | direct | f76be18 | docs only | - | 207 rows | - | - | done (COVERAGE.md refreshed after B2) |
| B0 housekeeping | #6 | b6198f8 | python, csharp-desktop, contracts, kernel, android pass (first run failed on ledger CSV quoting) | 1 self-review finding fixed (migration could overwrite a newer file) | Python 776 | none | none | merged |
| B1a Core voice turn pipeline | #8 | cd90d12 | all pass | self-review: endless VAD speech was unbounded, fixed | Python 824 | see B1 rows | v2.0.0-alpha.6 | merged |
| B1b Windows live voice (NAudio, PTT, Talk panel) | #9 | 9f032f0 | all pass | injected keys ignored by the hotkey, reply fetch limited to this session's audio path | dotnet 660, FlaUI 9 | AR-WIN-004/005/010/015 hardware | alpha.6 | merged |
| B1c cloud reasoning, Ollama eval, measuring tools | #10 | aaf21c1 | all pass (rerun after ledger conflict) | key echoed in a 422 body fixed (body read by hand); client closed after each call | Python 905 | STT benchmark, wake word, real cloud turn | alpha.6 | merged |
| B1d Settings page for cloud + notice | #11 | see git log | all pass | none | dotnet 674, FlaUI 10 | - | alpha.6 | merged |
| B2a mood engine, avatar-events 2.1, rate to voice | #12 | 81d5a03 | all pass (rerun after ledger conflict) | judgement calls on persona conflicts documented | Python 974 | - | alpha.7 | merged |
| B2b avatar package + avatar CI lane | #13 | see git log | all 7 pass (avatar lane fixed once: slow software WebGL on CI) | frame schedule bug (48 fps on 144 Hz) fixed | avatar unit 35, browser 9 | GPU profile, lip-sync offset, pose screenshots | alpha.7 | merged |
| B2c avatar host (WebView2), settings | #14 | 0c39678 | all pass | WebView2 failed with 0x8007007E until the app built as win-x64; browser accessibility tree off | dotnet 735, FlaUI 10 | see B2 rows | alpha.7 | merged |
| B3a/b/c S09 broker, routing, executor | #15, #16, #17 | see git log | all pass | see PR pages | see PR pages | B3c rows | alpha.8 | merged |
| B4 CORE-2 (+ B4-FIX) | #18 | d384df25c651 | all 6 pass at 518d9a43d10b (run 38790464725); main push run 38794259392 pass | streamed body limits, version validation, Activity expiry, telemetry deletion fixed | recorded: Python 1618/20 skipped, .NET 806/12 UI skips, avatar 35+9 | none new | alpha.9 PENDING | merged |
| B-reconcile | - | - | - | - | - | - | - | next |

CI run ids are on each PR page. Tags pushed since v2.0.0-alpha.2: none. Pending tags (never tagged with open hardware rows): alpha.3 to alpha.5 (older slices), alpha.6 (B1), alpha.7 (B2), then alpha.8 onward.

## Decisions taken in this loop (owner can overrule)
- Ollama local model for tool routing: `qwen2.5:3b-instruct-q4_K_M` (18/20, 0.43 s p50). `llama3.1:8b` stays the ADK chat default until measured.
- Cloud model default `claude-opus-5-5`, 8 s timeout, `claude-sonnet-5-5` suggested for faster voice. All domains default off for cloud.
- Placeholder avatar: pixiv VRM1_Constraint_Twist_Sample (VRM licence 1.0).
- App builds as `win-x64` (needed by WebView2).
- UI-automation runs set `REVA_DESKTOP_AVATAR=off`.

## Open items for the owner (not blocking)
- Hardware rows in `tests/evidence/ledger.csv` (see the Phase B checklist in `docs/loop/PHASE-B-hardware.md`).
- A custom "Hey Reva" openWakeWord model must be trained (none exists) before that engine can be compared.
- `docs/voice/mood-engine.md`: Kokoro has no pitch or softness control; only speaking rate is applied.

## Notes
- Working tree `D:\Projects\Reva` (branch `fixing-things`) holds uncommitted PIPE-1/planner work and is untouched. Loop work uses worktrees `D:\Projects\Reva-<slice>`.
- Two merge conflicts so far came from appending rows to the end of `tests/evidence/ledger.csv` in parallel branches; resolution is keeping both sets.

## Known limitations (kept explicit)
- AR-CORE-010 PARTIAL: consent filter exists; live cloud domain context not wired (G4). Spoken transcripts are sent when hosted voice processing is on.
- Vault config precedence works with injected stores; production startup injection incomplete (AR-CORE-008 PARTIAL).
- Dependency advisories (15 findings, 5 packages) and playback-watchdog cleanup warnings unresolved.
- Hardware rows open; no release tag, AWS deployment or cloud CD pipeline.

## Exact next action
Phase 2: reconcile B requirements against code and ledger (`docs/loop/B-RECONCILIATION.md`), then C1.
