# MASTER LOOP progress

## Phase C live checkpoint (2026-10-16)

- Fresh `origin/main` is `fcd328b26059eb5ea133c137dd83b2b41c6a640e` (PR #27 recovery merge). PRs #22–#27 have merged, bringing C1b/C1c and C2a/C2b/C2c into `main`; main CI run `38861940686` passed. C2c's real-Kernel validation is recorded in `docs/security/C2c-review.md` and the ledger; physical phone/PC checks remain `NEEDS_HARDWARE`. PR #29 is an unrelated OpenClaw sidecar and stays outside this Phase C loop.
- C3a worktree `D:\Projects\Reva-c3-phase`, branch `feat/c3a-android-local-brain`, starts at that main SHA. Local brain now answers Today from the Rust Kernel-backed repository, runs shared policy before any query, uses an explicit offline planner registry, and returns typed failure/unknown for timeout, cancellation, missing provider or exception. Full Android JVM suite: 316 passed, 0 failed, 0 skipped; 9 focused new tests. Contracts: 9 schemas checked, 0 problems. C3a PR/CI/merge pending. C3b/c, G2 software matrix, APK, hardware checklist and Phase C report remain open. No Phase D work begun.
- Next: review C3a diff, commit/push/open PR, obtain all code CI lanes, merge and update this checkpoint; then C3b modes and hosted consent, C3c privacy/performance/packaging, G2 and report. Never label hardware complete without observed physical evidence.

## Phase C recovery checkpoint (2026-10-15)

- Clean integration worktree: `D:\Projects\Reva-c-phase`, branch `feat/c1b-phase-c-integration`, created at `origin/main` `f1ff301c73804ff936e587c2c79a37c8402a1790` (PR #21 C1a merge). `D:\Projects\Reva` on `fixing-things` has unrelated uncommitted work and must stay untouched.
- Fetched remote refs. C1b `2f0dc23` is unmerged; C1c `2deb3e2` contains C1b and is unmerged. C2a `b569192` is PR #22, open and mergeable; its CI run `38817535253` passed at that head. C2b `1d55f1b` contains C2a and has no PR. C2c `6c76f93` contains C1c; PR #23 is open and conflicting. No C3 remote branch was found. All five source worktrees were clean at audit.
- Minimum integration order: apply C1b to merged C1a, then C1c's unique change; reconcile C2a against the new main, then C2b; reconcile C2c's two commits against both lines; implement C3a/b/c. Retain valid ledger rows on both sides of each merge.
- First integration step completed: cherry-picked C1b onto merged C1a without textual conflicts. No physical hardware test has been newly performed in this recovery pass.
- C1b integration cherry-pick `7d15a23` and review fix `2089aff` are pushed as [PR #24](https://github.com/ckvishwa/Reva/pull/24). Fresh local checks: Android JVM 206 passed, API 36 bridge regression 1 passed after a red run, avatar unit 36 and browser 9 passed, Python mood fixture 2 passed, contracts 9 schemas passed; evidence ledger has 231 parseable rows. See `docs/security/C1b-review.md`. PR CI and merge are pending; physical checks remain `NEEDS_HARDWARE`.
- C1b worktree/branch: `D:\Projects\Reva-c-phase`, `feat/c1b-phase-c-integration`; PR #24 is pending required checks and merge.
- C1c integration worktree: `D:\Projects\Reva-c1c-phase`, branch `feat/c1c-phase-c-integration`, based on C1b PR head `4aa8a8d`. Cherry-picked C1c unique commit as `ba9e9b2`; the only conflict was the ledger append, resolved by preserving C1b and C1c rows (236 valid CSV rows). Decimal approval hash parity was fixed in `cb88300` after a failing test. Fresh local checks: Android JVM 227 passed, Python fixture 4 passed, contracts 9 schemas, changed Python tooling Ruff clean. [PR #25](https://github.com/ckvishwa/Reva/pull/25) targets the C1b integration branch; CI and both merges are pending. No new physical hardware evidence was observed.
- C1b PR #24 CI run `38825716100`: contracts, desktop, avatar, Kernel and Android cross-build passed as of this checkpoint; Python and Android unit remained pending. The configured `claude-review` action run `38825716206` failed twice with `is_error:true` and hidden SDK output, with no code finding in the exposed log. Next: inspect the remaining code lanes, diagnose/retry the review blocker within the three-attempt limit, then merge C1b and retarget C1c only after required checks are green.
- C2a recovery (2026-10-15): `D:\Projects\Reva-c2a` now merges C1c `144ed67` as `2c08237`, with all 242 prior ledger rows preserved. The unchanged Rust Kernel source allowed generated Python bindings from the verified C1b build to be copied into ignored local build output; gateway/security/contract tests then ran without skips (289 passed, four pre-existing deprecation warnings). A red-green regression test exposed that rapidly completed phone actions evaded the eight-open-request cap; the gateway now limits each device to 20 new requests per rolling 60 seconds, while known-id retries and another phone remain available. PR #22 still targets `main` at old head `b569192`; push/retarget and CI remain pending. C1b PR #24 and C1c PR #25 code CI run IDs `38827151686` and `38827207970` each have six lanes passed and Python in progress as of this note; their separate `claude-review` action fails with no code finding in exposed logs.
- C2a PR #22 now targets the C1c integration branch at `0a74bfc`; code CI run `38828095865` is in progress. C2b source branch merged C2a as `dba63ea`; the ledger conflict preserved 248 distinct rows. Desktop tests: 833 passed, 0 failed, with 12 pre-existing opt-in UI skips; Python gateway/contract subset 32 passed using the unchanged generated Kernel binding. A red-green test found malformed non-object inbox items crashed parsing; a narrow guard now drops them. C2b PR, fresh CI and merge remain pending.
- C2c local merge (2026-10-16): `D:\Projects\Reva-c2c`, `feat/c2c-android-pc-requests`, merged C2b `399dc7c` as `2e64bb8` (parents `6c76f93` + `399dc7c`). All git-flagged conflicts (`RevaApp.kt`, `TalkScreen.kt`, `VoiceController.kt`, `Outcomes.kt`, `PolicyReplies.kt`, `AuthorizeParityTest.kt`, `tests/fixtures/rules-cases.json`) resolved to C2c's own tip, verified non-lossy: C2c's `pcrequests`/`phone` packages are a newer superset of C2b's android-side glue; `PcRequestTracker`, `PhoneActions`, `postReply`, `PolicyReplies(pc=, phone=)` all present post-merge. The previously-reported Android Gradle failure did not reproduce; root cause was environment, not source: the Domain Kernel's Android `.so` (arm64-v8a/x86_64) had never been cross-built in this worktree, and `-Preva.uiTests=true` was omitted, so both the Kernel-backed and Compose-UI instrumented tests failed to even launch. Built the Python/Kotlin bindings and both Android native libs after finding Strawberry Perl already installed but not first on `PATH` (needed for the vendored OpenSSL build). Full local verification at `2e64bb8` (see `docs/security/C2c-review.md`): all 10 required security invariants (pairing, revocation, no duplicate execution, expiry, replay, T2-needs-PC-click, phone-cannot-self-approve, allowlist, rate-limit-vs-retry, evidence-only completion) have existing passing tests, 0 gaps, 0 defects found. Android unit 307 passed/0 failed/0 skipped; Android instrumented (API 36 emulator) 34 passed/0 failed/2 pre-existing opt-in skipped; Python gateway+security+contract 97 passed/0 skipped (was 0 passed/47 skipped before the binding existed); full Python suite 1701 passed/20 skipped; ruff, mypy, contracts check all clean; Rust Kernel 95 passed/1 ignored, clippy clean; .NET 833 passed/0 failed, 12 pre-existing opt-in UI skips. `ruff format` was not run (nothing in this slice is newly authored by this pass). Android `lintDebug` fails on 3 pre-existing `NewApi` errors inside the generated, git-ignored `kernel/bindings/kotlin/uniffi/reva_kernel/reva_kernel.kt` (UniFFI's `Cleaner` use needs API 33, minSdk is 31) — unrelated to this merge, not fixed here. Nothing pushed; PR #23 still targets `main` (wrong base; should target `feat/c2b-desktop-phone-requests` per the stack) and remains `CONFLICTING` against it until pushed and retargeted. Physical phone+PC acceptance remains `NEEDS_HARDWARE`.

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
