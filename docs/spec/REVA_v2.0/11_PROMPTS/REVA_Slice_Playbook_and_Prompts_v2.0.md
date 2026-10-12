# REVA — Slice Playbook and Claude Code Prompts v2.0

**Document ID:** REVA-PLAYBOOK-002 · **Version:** 2.0.3 · **Date:** 2026-10-12
How we build REVA 2.0: what each slice implements, why it comes where it does, how it is built, the first tasks, and a ready-to-paste Claude Code prompt. Slice details and requirement IDs: `04_SLICES/REVA_Version_Slices_v2.0.md`.

---

## 1. What "v1 / v2" means here

| Term | Meaning |
|---|---|
| **REVA 2.0** | The product we are building. Every slice ships a tag on the way to `v2.0.0`: `alpha.N` (Windows → Android → domains), `beta.N` (standalone + hardening), `rc.N` (packaging), then `2.0.0`. |
| **Spec v2.0.x** | This document pack. v1.1 is the archived original. |
| **Feature v1 → v2** | Inside 2.0, some features ship a simple first version and a better second one later. They are listed below so nobody over-builds early. |

| Feature | First version (when) | Second version (when) | Why split |
|---|---|---|---|
| Lip sync | Loudness (RMS) of played audio (S08) | Visemes from the synthesized audio (S24) | RMS is a day of work and is honest; visemes need timing data |
| Entity matching | Exact / alias / fuzzy; vector runs in shadow (S09) | Vector auto-resolve after calibration (S24) | A wrong silent match is worse than a question |
| Reasoning | Ollama on PC, rules for common commands (S07/S09) | Hosted model opt-in, Android standalone (S21) | Local first; privacy and cost |
| TTS | Kokoro baseline, Revi when it passes the gate (S05/V3) | Revi default + streamed to phone (V4/S15) | Ship a working voice before the perfect one |
| Sync | LAN direct (S14) | Encrypted relay (S22) | Relay needs adversarial review |
| Language | English (R1) | Telugu + code-mixed (S24) | English eval exists; Telugu needs its own |
| UI automation | App open/close allowlist (S09) | UIA inspect/click (S23) | Read-only and allowlisted first |
| Agent plan length | Max 2 steps | 3+ steps (Future) | Each extra step multiplies failure modes |

---

## 2. Build order and why

The rule behind the order: **safety → foundation that everything depends on → one real end-to-end loop → widen**. Each slice is the smallest thing that can be proven with real evidence.

| # | Slice | Tag | What we build | Why at this point |
|---|---|---|---|---|
| — | **V1** Voice workspace cleanup | — | Assets moved, manifest, envs frozen | Already half done; finishing it removes clutter before the repo is restructured |
| 1 | **S00** Snapshot | — | Tags, bundles, baseline record | Nothing may be lost; every later change is reversible from here |
| 2 | **S01** Wake-word fail-closed | — | Commit the security fix alone | Known security hole in HEAD; smallest possible fix first |
| 3 | **S02** Shutdown proof | — | Owned vs external Core shutdown with PID proof | Every voice/avatar slice spawns processes; orphans must be impossible first |
| 4 | **S03** Restructure + CI | **alpha.0** | `core/ kernel/ windows/ android/ avatar/ contracts/`, CI lanes, env guard, ledger | Every later slice writes into this layout; doing it later means moving more code |
| 5 | **S04** Kernel spike | alpha.1 | Rust Finance domain, SQLCipher, Python + Kotlin bindings | Riskiest unknown (Android NDK + SQLCipher). If it fails, ADR-027 fallback changes many slices — learn it on day one |
| — | **V2** Bakeoff close-out | — | Written engine decision for Revi (EN + TE, license) | S05 needs to know which engine to wrap |
| 6 | **S05** TTS providers | alpha.2 | Provider registry, Kokoro + Revi providers, manifest-verified loading | Output first: you can hear REVA before it can listen; easiest audible proof |
| — | **V3** Revi export + voice gate | revi-1.0 | Final model files, hashes, gate report | Turns the trained voice into a shippable asset |
| 7 | **S06** Session + Corx turn engine | alpha.3 | State machine, turn_epoch, VAD/endpointing, normalizer, dialogue state, timings | The skeleton every voice turn runs through; Lakewood patterns land here |
| 8 | **S07** Real voice loop | alpha.4 | Mic → STT → Ollama → TTS → speaker on hardware | First true end-to-end proof; everything after builds on a working loop |
| 9 | **S08** Avatar | alpha.5 | VRM in WebView2, state + lip sync | Needs real session states and real audio from S06/S07 to be honest |
| 10 | **S09** NLU + authorize + action | alpha.6 | Rules, resolution ladder, `authorize()`, policy, Notepad verified | Actions only after the loop works; authorization before any write |
| 11 | **S10** Memory + Finance + NLG | **alpha.7 = R1** | Kernel domains on Windows, templates, number check | First domains on top of a safe action path; closes the Windows alpha |
| 12–16 | S11–S15 Android paired | alpha.8–12 = R2 | Shell + Kernel, voice + avatar, pairing, LAN sync, phone→PC action | Phone reuses Kernel, contracts, avatar, authorizer already proven on Windows |
| 17–21 | S16–S20 Domains | alpha.13–17 | Finance full, Health, Coach, Personal, Learn, Career, Cyber, privacy | Same Kernel pattern repeated per domain once the pattern is proven |
| 22–25 | S21–S24 Standalone + relay | beta.1–4 = R3 | Phone alone, relay, UIA, perf, Telugu | Independence and hardening after features exist |
| 26–28 | S25–S27 Release | rc.1 → **2.0.0** | Installer, signed Android, security review | Packaging last, once behavior is stable |
| ∥ | A1–A4 Avatar model | asset 1.0 | Blender → VRM | Runs in parallel; placeholder VRM unblocks S08 |
| ∥ | V4 Revi default | revi-1.0 | Revi default + Android playback | Before G1 recording |

**Next three actions:** finish V1 → S00 → S01.

---

## 3. Session preamble — paste at the start of every Claude Code session

```text
You are working on REVA 2.0 in D:\Projects\Reva.
Specs: docs/spec/REVA_v2.0/ (README, PRD, ARDs 000–800 + 450, ADRs, slices, contracts, prompts).
Read docs/spec/REVA_v2.0/04_SLICES/REVA_Version_Slices_v2.0.md for the slice named below, and the ARDs it cites.

Rules (non-negotiable):
1. Work only on the named slice. Before editing, list the files you plan to create/modify and why. Minimal diffs.
2. Never run git reset, git clean, git push --force, or delete untracked files. Do not stage or commit files unrelated to this slice; leave unrelated dirty work exactly as it is.
3. Tests never touch real user data: use temp dirs for REVA_DATA_DIR; never point at any production database.
4. No secrets in code, config, logs or test output. Keys go to Windows Credential Manager / DPAPI (Android Keystore on phone).
5. No new services, brokers or databases beyond what the ARDs specify. No money-movement or medical-advice capability, ever.
6. A model may propose; only deterministic policy authorizes; only executors act; REVA reports success only from executor/Kernel evidence.
7. Evidence: run the real tests and paste real output. Anything needing my hardware (mic, speaker, phone, GPU) is marked NEEDS_HARDWARE with exact steps for me to run; never report a skipped or mocked test as PASS.
8. Add one row per verified requirement to tests/evidence/ledger.csv (req_id, test_id, commit, device, provider/model versions, date, result, artifact).
9. Stop and ask me if: a test would touch real data, a security check fails open, the spec is ambiguous in a way that changes architecture, or the slice needs something the spec forbids.

Finish with this report:
- Summary (2–4 lines)
- Files changed
- Commands run + results (real output, trimmed)
- Requirements covered → evidence rows added
- NEEDS_HARDWARE steps for me
- Not done / risks
- Ready for next slice? (yes/no + why)
Commit with message: "<SLICE-ID>: <short summary>" and tag only if the slice says so.
```

---

## 4. Slice cards — Phase 0 and V1 (start here)

### Before S00 — put the specs where Claude Code can read them

```powershell
Expand-Archive -Path .\REVA_v2.0.3_Spec_Pack.zip -DestinationPath D:\Projects\Reva\docs\spec
# result: D:\Projects\Reva\docs\spec\REVA_v2.0\README.md
```
Leave it untracked until S03 commits it. Then open Claude Code in `D:\Projects\Reva`, paste the preamble (§3), then the slice prompt.

### V1 — Finish the voice workspace cleanup (no Claude Code needed)

- **What:** move voice assets to `F:\reva-assets`, copy code to the repo, freeze envs, build the manifest.
- **Why first:** half done already; the repo restructure (S03) should not inherit stray copied files with unknown status.
- **How:** run the fixed script **as a file**, never pasted:

```powershell
cd D:\Projects\Reva
Unblock-File .\Merge-RevaVoiceWorkspace.ps1
# close VS Code / terminals / Explorer windows that have F:\Voice FOR Reva open
pwsh -ExecutionPolicy Bypass -File .\Merge-RevaVoiceWorkspace.ps1           # dry run, read the plan CSV
pwsh -ExecutionPolicy Bypass -File .\Merge-RevaVoiceWorkspace.ps1 -Apply    # resumes; skips finished steps
```

- **Done when:** the script says the source folder is empty (or only FAILED items you understand), `F:\reva-assets\assets.manifest.json` exists, and you have filled `source`, `license`, `provenance_status` for the Revi dataset, synthetic set, style bank and checkpoints.
- **Note:** the earlier pasted run already copied ~190 code files into the repo. The re-run marks identical ones `ALREADY_DONE`. They stay untracked until S03 decides where they live.

### S00 — Snapshot and archive

- **What:** a recorded, recoverable starting point.
- **Why:** v1 rule: nothing unrelated may be lost; tags and bundles make every later change reversible.
- **How:** read-only inspection + tags + bundles; no code changes.
- **Start tasks:** `git status`, branch list, HEAD, toolchain versions, run current Python and .NET suites; tag all branches; bundle; write `docs/archive/baseline-2026-10.md`.

```text
SLICE S00 — Snapshot and archive. No version tag.
Goal: record the exact starting state and make it recoverable. Change no code.
Do:
1. Record: git status (full), current branch, HEAD sha, all local branches with last commit, stash list, dotnet --info (short), python --version, Rust/cargo version if present.
2. Run the existing Python test suite and the .NET test suite exactly as the repo documents; record pass/fail/skip counts. Baseline from the Oct 11 audit: Python 326 passed / 2 skipped, .NET 334 passed.
3. Create lightweight tags archive/pre-merge-2026-10-11/<branch> for every local branch (do not move or delete branches).
4. Create a bundle: git bundle create ..\reva-archive-2026-10-11.bundle --all, then git bundle verify it. Tell me its path so I can copy it off this drive.
5. Write docs/archive/baseline-2026-10.md with everything above, including the list of untracked files (note: tools/voice-lab/ and tests/voice-evals/ contain untracked files from the voice workspace merge — list them, do not touch them).
Do not commit anything except docs/archive/baseline-2026-10.md (commit only that file).
Done when: tags exist, bundle verifies, baseline file committed, test counts recorded (even if different from the audit — report differences).
```

### S01 — Wake-word fail-closed

- **What:** commit the resolver fix and its tests alone.
- **Why:** a security bug in HEAD; smallest fix, isolated commit, before anything touches audio.
- **How:** inspect the dirty working-tree fix; keep only resolver + its tests; extend negative tests.
- **Start tasks:** `git diff` of `WakeWordKeywordResolver.cs` and its test file; confirm behavior; add missing cases.

```text
SLICE S01 — Wake-word fail-closed (P0-01). No version tag.
Requirements: AR-WIN-001, FR-019, AC-001.
Files (from the audit; verify paths): desktop/src/Reva.Desktop/Services/WakeWordKeywordResolver.cs and desktop/tests/Reva.Desktop.Tests/Unit/WakeWordKeywordResolverTests.cs.
Do:
1. Show me the current uncommitted diff for those two files only.
2. Ensure: every enabled .ppn requires an expected SHA-256; blank or missing manifest => failure even when the file exists; mismatched hash => failure; the recorder is never armed on failure.
3. Tests (positive and negative): missing hash, empty manifest dictionary, invalid hash format, mismatched hash, matching hash, file missing. Add an assertion that the recorder-arming path is not called on any failure.
4. Run the full .NET suite.
5. Stage ONLY those two files; commit "S01: wake-word resolver fails closed". Show git show HEAD --stat and confirm MainWindow.xaml.cs and other dirty files are still uncommitted and unchanged.
Do not touch shutdown code or any other dirty file.
```

### S02 — Shutdown lifecycle proof

- **What:** owned Core exits with the app; external Core survives; PID proof.
- **Why:** voice, avatar and TTS add child processes; orphan-free shutdown must be solid before them.
- **How:** move existing dirty shutdown edits to an archive branch; implement cleanly; prove on real Windows.

```text
SLICE S02 — Shutdown lifecycle proof (P0-02). No version tag.
Requirements: AR-WIN-002, AR-072, AC-010.
Do:
1. Preserve the uncommitted shutdown edits: create branch archive/shutdown-wip from the current HEAD, commit only the shutdown-related dirty files there, switch back. Show me both branches' status. Nothing else moves.
2. Implement owned-vs-external Core lifecycle in the desktop app: the app records whether it started the Core (owned) or attached to a healthy existing one (external). On window close and tray quit (same code path): owned Core is asked to exit, then killed after a bounded timeout; external Core is never touched. No blind Environment.Exit(0).
3. Unit tests for the decision logic (owned/external/no Core/stale PID).
4. Write scripts/dev/shutdown-proof.ps1: launches the built app N times (default 10), records desktop PID and Core PID before/after close, and reports any surviving owned Core process; second mode starts an external Core first and verifies it survives.
5. NEEDS_HARDWARE: give me the exact command to run the proof script on my machine and what output means pass.
Commit "S02: owned vs external Core shutdown with PID proof".
```

### S03 — Restructure, CI, env guard, ledger → tag `v2.0.0-alpha.0` (Gate G0)

- **What:** the v2 repo layout, CI skeleton, test-data guard, evidence ledger, specs in the repo.
- **Why:** every later slice writes into this layout.
- **How:** `git mv` in small steps, fixing paths after each, tests green after each move.

```text
SLICE S03 — Repo restructure, CI, env guard, ledger. Tag v2.0.0-alpha.0 at the end (Gate G0).
Requirements: AR-SYS-001, AR-CORE-004, AR-REL-001/002/003.
Target layout (ARD-800 §1): core/ (Python Core, from reva_core), windows/ (WinUI app, from desktop/), android/ (empty + README), kernel/ (empty + README), avatar/ (empty + README), contracts/ (copy of docs/spec/REVA_v2.0/08_CONTRACTS), assets/avatar/ (Git LFS attributes only), tests/, tools/, docs/, packaging/.
Do, one move per commit, tests green after each:
1. Propose the exact move map (old path -> new path) and the files whose paths must change (sln/csproj, pyproject, imports, CI, scripts). Wait for my OK.
2. git mv the Core; fix imports/pyproject; run Python tests. Commit.
3. git mv the desktop app; fix sln/csproj/scripts; run .NET tests. Commit.
4. Create the empty dirs with READMEs; .gitattributes for *.vrm, *.blend, *.onnx, *.pth, *.safetensors as LFS; .gitignore for envs, model files, assets.
5. Env guard: pytest fixture/conftest that fails if REVA_DATA_DIR is not under a temp dir or if any DATABASE_URL-like setting points to a non-local host; add tests proving it (including a spawned child process).
6. tests/evidence/ledger.csv with the header from ARD-800 §5; add rows for S01/S02 evidence.
7. CI skeleton (.github/workflows): Python lane (pytest, ruff, mypy), .NET lane (build/test, windows runner), contracts lane (validate every JSON schema). Kernel/Android lanes as placeholders that pass with a notice.
8. Move the untracked voice files: tools/voice-lab/** and tests/voice-evals/** stay where they are; add them to git only if they contain no secrets, no absolute personal paths and no audio; list anything excluded.
9. Commit docs/spec/REVA_v2.0 (the spec pack) and docs/archive/v1.
10. Gate G0 check: clean git status (except files I chose to keep untracked), Python and .NET suites at or above the S00 baseline, wake-word fix in HEAD. Tag v2.0.0-alpha.0.
```

---

## 5. Slice cards — Phase 1 (Windows alpha, R1)

### S04 — Domain Kernel spike → `alpha.1`

- **What:** `kernel/` Rust crate with the Finance domain (account, transaction, category), SQLCipher file, `KeyProvider`, event log + outbox, UniFFI bindings for Python and Kotlin, Android cross-build.
- **Why now:** the biggest technical unknown. If SQLCipher on the Android NDK fails, ADR-027's fallback reshapes S10–S20.
- **How:** start from the AuraO finance code if it still exists (PR #8 on GitHub); otherwise write fresh from ARD-700 §2.

```text
SLICE S04 — Domain Kernel spike. Tag v2.0.0-alpha.1.
Read: ARD-700 (all), ADR-027/028/029, contracts/domain-event.schema.json.
Requirements: AR-DOM-001/002/003/004/014, NFR-017/018.
Build kernel/ (crate reva-kernel, cdylib + lib):
1. store/: open SQLCipher DB per domain via rusqlite (bundled SQLCipher, vendored OpenSSL); KeyProvider trait (host supplies key); typed errors Locked/WrongKey/Corrupt/MigrationFailed; migrations with schema_migrations + backup before destructive steps. If github.com/ckvishwa/AuraO PR #8 (src-tauri/src/finance/database.rs, migration.rs, secrets.rs, errors.rs) is reachable, adapt it; say what you reused.
2. events/: event envelope matching contracts/domain-event.schema.json (signature field may be a placeholder in this slice — note it), append-only log, outbox, projection rebuild.
3. domains/finance: commands add_account, add_transaction, delete_transaction (tombstone); queries spend_by_category(period), list_transactions.
4. UniFFI API from ARD-700 §2.1 (open_domain, command, query, pending_events, apply_events).
5. Conformance tests in kernel/tests run natively; a Python test calls the same scenarios through the generated Python binding; a Kotlin test (JVM is fine for this slice) calls them through the Kotlin binding.
6. Android cross-build for aarch64-linux-android and x86_64-linux-android (cargo-ndk). Report exactly what worked. If SQLCipher/OpenSSL fails on the NDK after a reasonable attempt, STOP and report the error so we can decide on the ADR-027 fallback.
7. No network crates in the dependency tree (add a check).
Done when: the same conformance suite passes 3 ways, Android .so files build (or a clear failure report), recovery tests pass (wrong key, missing key, corrupt file, fresh install).
```

### V2 — Bakeoff close-out (you + Claude Code in `tools/voice-lab`)

- **What:** one written decision: which engine runs Revi, English and Telugu verdicts, license.
- **Why now:** S05 needs the engine; licenses decide what can ship.

```text
SLICE V2 — Revi bakeoff close-out. No version tag.
Inputs: F:\reva-assets\runs\revi-model-bakeoff, revi-*-study folders, tools/voice-lab/ scripts, assets.manifest.json.
Do:
1. Summarize every engine tried (Chatterbox, Chatterbox v3, XTTS-v2, IndexTTS2, Kokoro baseline) from the run outputs: what was trained or conditioned, on which data, settings used.
2. Build one eval script (tools/voice-lab/eval/) that, for each candidate and for English and Telugu sentence sets: measures time to first audio and real-time factor on this PC (CPU and GPU if present), runs the audio back through faster-whisper and computes character error rate, and writes a CSV. Do not move or modify any asset files.
3. For each engine, record its code license and model-weights license and whether it permits my intended use; mark unknowns.
4. Write docs/voice/bakeoff-decision.md: chosen Revi engine, Telugu verdict, fallback, open questions. I make the final call.
NEEDS_HARDWARE: the eval run and my blind listening ranking.
```

### S05 — TTS providers, manifest-verified → `alpha.2`

```text
SLICE S05 — Provider registry + manifest-verified TTS. Tag v2.0.0-alpha.2.
Read: ARD-300 §5, ARD-400 §2 and AR-VA-008/020/021, ADR-025/038/040, docs/voice/bakeoff-decision.md.
Requirements: AR-CORE-003, AR-VA-008, AR-VA-020, AR-VA-021, FR-004, FR-LNG-005.
Do:
1. core/reva_core/providers/: registry with capability-driven selection and a fake provider for tests.
2. TtsProvider interface: speak(text, turn_epoch) -> stream/chunks, stop(), health(). Kokoro af_heart provider. Revi provider for the engine chosen in V2, running as a supervised subprocess if heavy (JSON over stdin/stdout, same protocol as the old Kokoro voice host: speak/stop/health, interrupt without overlap, natural-completion event, zero orphans).
3. Loading guard: a voice loads only if its files' SHA-256 match assets.manifest.json (path from config, outside the repo) and provenance_status is not TODO/excluded; otherwise refuse and fall back to Kokoro with a logged reason.
4. Speaker mute; settings to pick the voice.
5. Tests: provider contract with fake; tampered/missing/unlisted model refused; interrupt; orphan check (real-process test gated behind an env flag).
6. Voice-gate script producing the AR-VA-021 report (first-audio, interrupt, CER round-trip, orphan check); the owner rating is mine.
NEEDS_HARDWARE: run the gate on my PC for Kokoro and Revi.
```

### V3 — Revi export and voice gate

```text
SLICE V3 — Revi model export. Tag the asset revi-1.0 in assets.manifest.json (not a git tag).
Do: export the final Revi checkpoint and its reference/style files into F:\reva-assets\models\tts\revi\1.0\ (copy, never move the originals); add entries with SHA-256 to the manifest (engine, version, language, source, license, provenance_status); run the S05 voice gate against revi-1.0 and save the report to docs/voice/revi-1.0-gate.md.
Pass = AR-VA-021 thresholds met. If latency fails, report which stage is slow and options (GPU, chunking, smaller model).
```

### S06 — Session + Corx turn engine + dialogue state → `alpha.3`

- **What:** the turn skeleton: state machine, `turn_epoch`, deadlines, WebSocket events, Corx VAD/endpointing, acknowledge-first, normalizer, dialogue state, per-stage timings.
- **Why now:** STT, the planner, TTS and the avatar all plug into this; Lakewood patterns land here.
- **How:** port Corx if it's cleanly separable (as a package), otherwise copy-adapt into `core/reva_core/voice/` with its tests; no restaurant code.

```text
SLICE S06 — Session coordinator + Corx turn engine + dialogue state. Tag v2.0.0-alpha.3.
Read: ARD-300 §3–4, ARD-400 §1, ARD-450 §3.1/3.4/4.2, ADR-037, contracts/session-event.schema.json and nlu-frame.schema.json.
Requirements: AR-CORE-001/002/005/006, AR-VA-004/019/022, AR-LANG-002/005/010.
Source to reuse: my Lakewood repo's Corx engine (VAD + endpointing, ~280 ms end-of-speech, pause-driven follow-up turns, ack-first). First, inspect it and tell me whether it is separable from order logic; propose package vs port. Never import menu, pricing, POS, telephony, Twilio or any keys.
Build:
1. SessionCoordinator state machine (ARD-300 §3) with turn_epoch; late results from older epochs are dropped everywhere.
2. Deadlines per stage (VAD/STT, model, tool, TTS) with typed errors.
3. /v1/voice/sessions (POST/DELETE) and /v1/voice/sessions/{id}/events WebSocket emitting session-event.schema.json events.
4. Endpointing from Corx, tuned on fixture clips (pre-recorded, no live mic in CI).
5. Normalizer (money, numbers, dates, times, durations; ambiguity preserved) → NluFrame.
6. Dialogue state tracker persisted after each accepted proposal; anaphora for "it/that/the last one"; undo pointer.
7. Acknowledge-first: template ack when reasoning > 700 ms; cancelled on barge-in; never phrased as success.
8. Per-stage timings in every trace.
Tests: late-response injection, timeouts, normalization fixtures, anaphora fixtures, restart-resume, ack timing.
```

### S07 — Real voice loop → `alpha.4`

```text
SLICE S07 — Real voice loop on hardware. Tag v2.0.0-alpha.4.
Requirements: FR-001–FR-010, AR-WIN-003/004/010/015, AR-AGT-013, AR-LANG-001/014.
Build: WASAPI capture in the WinUI app (device select, mute, device-loss to safe idle) → audio frames to Core → Corx endpointing → faster-whisper with a words-only vocabulary prompt (app names, finance categories) → Ollama (model chosen by a small tool-call eval you write; report it) → TTS (Revi if gated, else Kokoro) → playback with turn_epoch flush; push-to-talk global hotkey; TurnEvent recording (local, redacted).
Benchmark STT on my desk mic: WER per model size (tiny/base/small) on a 50-sentence script; pick by WER + latency; record in docs/voice/stt-benchmark.md. Lakewood numbers were 8 kHz phone audio — do not reuse them.
NEEDS_HARDWARE: 3 recorded end-to-end runs; MET-02 timing; Stop and unplug behavior.
```

### S08 — Avatar → `alpha.5`

```text
SLICE S08 — Avatar in WebView2. Tag v2.0.0-alpha.5.
Read: ARD-400 §3–4, ADR-024, contracts/avatar-events.schema.json.
Requirements: FR-AV-001–006, AR-WIN-005/006/007, AR-VA-009–012, NFR-019.
Build avatar/ (one web package, bundled locally, exact versions, no CDN): three.js + @pixiv/three-vrm, loads assets/avatar/placeholder.vrm (a license-clear sample — tell me which and its license), idle/listening/thinking/speaking/approval/error poses, mouth from avatar.mouth RMS events, expressions only with cause=verified_outcome, settings (off, reduced motion, quality), FPS cap 60, pause when hidden. Host in WinUI WebView2 via virtual host mapping; block all navigation and network. Session state → avatar.state; playback RMS (~60 Hz) → avatar.mouth with turn_epoch; stale epochs dropped.
Tests: schema validation of every event; offline load; listening pose only when capture reports mic open; lip-sync offset measurement script (target ≤ 100 ms p95); interrupt ≤ 300 ms p95.
NEEDS_HARDWARE: GPU/FPS profile 10 min; offset measurement.
```

### S09 — NLU fast path + authorize + verified action → `alpha.6`

```text
SLICE S09 — NLU fast path, resolution ladder, authorize(), policy, Notepad verified. Tag v2.0.0-alpha.6.
Read: ARD-450 §3.2/3.3/3.5/3.6, ARD-600 (all), contracts/capability-registry.v2.json, authorization-decision.schema.json, planner-decision.schema.json; Lakewood authorize_cart_mutation design (pure, no LLM, no writes, stable reason codes).
Requirements: AR-AGT-001–006/011/012/014/015, AR-WIN-008/009, AR-LANG-003/004/006/007/008/018, FR-LNG-001/002.
Build: rule fast path (regex + spaCy Matcher) for the ARD-450 intent list with positive/negative fixtures; resolution ladder exact → alias → lexical → fuzzy (RapidFuzz) → vector (shadow-only, logs scores + margin) → ask; planner fallback validated against the schema; pure authorize() returning AuthorizationDecision; policy broker computing tiers from the registry; signed grants bound to action, args, target, expiry, idempotency key; WinUI approval dialog for T2; executor evidence; "open Notepad, type 'Meeting notes', verify the text is there".
Tests: forbidden-capability refusal, forged/replayed/substituted grants, tampered tier, filler vs content words, false-success corpus 0/100, registry absence test in CI.
NEEDS_HARDWARE: physical Notepad E2E recording.
```

### S10 — Memory + Finance on Windows + NLG → `alpha.7` (Gate G1 / R1)

```text
SLICE S10 — Memory + Finance core in Kernel, Windows screens, NLG. Tag v2.0.0-alpha.7 after Gate G1.
Read: ARD-700 §3–6, ARD-450 §4, ARD-100 §3/§6.
Requirements: AR-DOM-005, FR-MEM-001/002, FR-FIN-001, FR-DOM-001–005 (Windows), AR-LANG-009/011/012/013, FR-LNG-003/004.
Build: Memory domain in the Kernel (candidates + approval, citations, abstention, hybrid FTS + Ollama embeddings with lexical fallback); port the old Memory Engine benchmark (if recoverable) to tests/benchmarks and require ≥ 9/10; Finance screens in WinUI over Core APIs (/v1/domains/...); voice "I spent 12 dollars on lunch" → NluFrame → proposal → authorize → confirm card → Kernel commit → template "Saved."; NLG templates for every intent × outcome; grounded answers with citations; number/claim check with one retry then template fallback; spoken rewrite + sentence chunking with turn_epoch.
Gate G1 (NEEDS_HARDWARE, 3 recorded runs): ARD-100 §6 — Notepad by voice, Revi/Kokoro answer with avatar lip sync, interrupt stops audio + mouth together, expense by voice saved and visible in Finance.
```

---

## 6. Slice cards — later phases (compact prompts)

Use the preamble + the slice's section in `04_SLICES`. One-line intent per slice:

| Slice | Tag | Prompt core |
|---|---|---|
| S11 | alpha.8 | "Create android/ Kotlin + Compose app (minSdk 31, target 36), screens Talk/Memory/Finance/Settings, load Kernel .so via Kotlin bindings with Keystore KeyProvider, domain files in noBackupFilesDir, airplane-mode domain suite. Reqs AR-AND-009/010/017/018, NFR-023." |
| S12 | alpha.9 | "Android voice: microphone foreground service from user tap, permission flows, on-device STT availability check with disclosed fallback, TTS synth-to-file + AudioTrack envelope, same avatar/ package in WebView via WebViewAssetLoader, shared language artifacts. Reqs AR-AND-001–005, AR-LANG-015, FR-AV-007." |
| S13 | alpha.10 | "Pairing gateway on Windows (separate narrow API, TLS, device keys), QR + fingerprint + signed challenge, scoped grants, atomic revocation. Reqs AR-DATA-001–006, AR-AND-007." |
| S14 | alpha.11 | "LAN sync for Memory + Finance: signed events, outbox, idempotent apply, tombstones, cursors, conflict records for amounts. Reqs AR-DATA-010/011/015, AR-DOM-008, FR-SYN-001; AC-008, AC-018." |
| S15 | alpha.12 (G2) | "Phone voice → PC Core → phone audio (Revi streamed if enabled); 'open Calculator on PC' requiring PC approval for T2. Gate G2 per ARD-200 §6 on a physical phone." |
| S16 | alpha.13 | "Finance full: budgets, bills + reminders, recurring, net worth, CSV/OFX import with row reports, Today v1 on both apps. Reqs FR-FIN-002/003, FR-TDY-001, AR-DOM-012/013." |
| S17 | alpha.14 | "Health domain + manual entry + Health Connect read-only import + safety routing and eval (no diagnosis/dosing). Reqs FR-HLT-001–003, AR-AND-013, AR-DOM-007, NFR-021." |
| S18 | alpha.15 | "Coach (goals, habits, check-ins, weekly review) + Personal (journal local-only default, people, reminders) on both apps." |
| S19 | alpha.16 | "Learn (decks, quiz, streak, cert progress), Career (pipeline), Cyber (notes, inventory; no scanning tools) on both apps." |
| S20 | alpha.17 (G3) | "Per-domain privacy switches, consent filter with network-capture tests, export/delete/import for every domain. Gate G3: 8/8 domains offline on both devices." |
| S21 | beta.1 | "Android local brain standalone: hosted provider opt-in with disclosure, offline-lite, mode indicator. Reqs AR-AND-011/012." |
| S22 | beta.2 | "Relay: group key at pairing, device-side encryption, Supabase mailbox storing ciphertext only, adversarial review; no E2EE label until passed." |
| S23 | beta.3 | "Windows UIA inspect/click/set-text with fresh snapshots, redaction, secure-desktop fail-closed. Reqs AR-WIN-011/016, FR-AI-011/012/014." |
| S24 | beta.4 (G4) | "Failure injection, latency budgets, battery/thermal, viseme lip sync, Telugu NLU/NLG + Telugu voice eval, vector auto-resolve calibration gate." |
| S25 | rc.1 | "Windows installer bundling .NET, Windows App SDK, Python runtime, Kernel; signing; clean-VM install/upgrade/uninstall." |
| S26 | rc.2 | "Signed APK + AAB, upgrade keeps data, Play health-apps declaration prepared." |
| S27 | 2.0.0 (G5) | "Security signoff (MASVS, transport, policy, secrets, privacy), accessibility smoke, evidence ledger complete for every MUST; tag v2.0.0." |
| V4 | revi-1.0 | "Make Revi the default voice (Settings switch); Android plays Revi streamed from the PC when paired, Android TTS when standalone." |
| A1–A4 | asset 1.0 | Blender work (yours): concept + base mesh ≤ 50k tris → rig + expressions → textures/MToon/VRM export → VRMA clips; then "swap placeholder.vrm for reva-1.0.vrm and re-run S08 avatar tests". |
