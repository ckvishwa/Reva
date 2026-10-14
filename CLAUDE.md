# CLAUDE.md — REVA 2.0

REVA is a personal AI that you talk to through an animated avatar. It has a WinUI 3 Windows app and a Kotlin/Compose Android app, and each one works on its own. Eight life domains (Memory, Finance, Health, Coach, Career, Learn, Cyber, Personal) live in one shared Rust Domain Kernel. A Python Core on the PC handles voice, planning, policy and sync. Single user, local-first; any cloud use is opt-in.

## Source of truth

- Specs: `docs/spec/REVA_v2.0/` (README, CHANGELOG, SHA256SUMS, `01_PRD` … `11_PROMPTS`). Read the slice you are working on in `docs/spec/REVA_v2.0/04_SLICES/REVA_Version_Slices_v2.0.md`, then the ARDs it cites in `docs/spec/REVA_v2.0/02_ARD/`.
- Decisions: `docs/spec/REVA_v2.0/03_ADR/REVA_ADR_Register_v2.0.md` (ADR-001 to ADR-040). Contracts: `contracts/` at the repo root is a copy of `docs/spec/REVA_v2.0/08_CONTRACTS/`; keep them identical (CI checks it).
- Prompts and build order: `docs/spec/REVA_v2.0/11_PROMPTS/REVA_Slice_Playbook_and_Prompts_v2.0.md`.
- Persona: `docs/persona/REVA_Persona.md`.
- If `docs/spec/REVA_v2.0/` is missing or the paths differ (for example the old `docs/08_CONTRACTS/`), stop and tell me. Don't guess paths.

## Current state (update this section at the end of every slice)

- **VOICE-1 (branch `integrate/voice-1`, on top of `main` after alpha-2):** the voice pipeline from `feat/pipe-1-voice` (provider registry, manifest-verified Kokoro provider, `/v1/voice/sessions` + WebSocket events with `turn_epoch`) replayed onto `main`, and Kokoro made real. Kokoro-82M v1.0 `af_heart` runs in its own interpreter (`REVA_KOKORO_PYTHON`, versions in `tools/voice/kokoro-requirements.txt`) with assets under `REVA_ASSET_ROOT` (`models/tts/kokoro/1.0/`), three manifest entries recorded by `tools/voice/register_kokoro_assets.py` (subset in git: `docs/voice/kokoro-assets.manifest.json`). A real run found and fixed: Kokoro writes log lines to stdout (broke the JSON protocol); a blocked stdin pipe read hangs `import numpy` on Windows; `stop` mid-sentence made Core kill the worker (9 s reload); workers inherited Core's whole environment. Real-model tests are opt-in (`REVA_RUN_KOKORO_REAL=1`, see `docs/voice/kokoro-production.md`): 14 + 3 passed. Python 639 passed / 19 skipped (opt-in hardware) / 1 xfailed, .NET 589 passed. Security review: `docs/security/VOICE-1-review.md`. Timing (10 runs, dev PC, output muted): first audible p50 726.6 ms vs the 700 ms budget (`FAIL`, indicative), stop-to-silence p95 26 ms, 0 orphans; the speaker run, STT CER and blind comparison are `NEEDS_HARDWARE`. Not done: speaker mute does not exist in this tree; the provider epoch is global while sessions count from 0 (strict xfail, S06 must fix before wiring sessions to TTS). Default provider unchanged by decision: Kokoro; Revi/Qwen/Chatterbox stay experimental.
- **SYNC-1e (branch `feat/sync-1e-refresh`; tag `v2.0.0-alpha.3` PENDING hardware confirmation):** open screens follow the data. Root cause: PC Finance/Today and phone Today/Finance loaded only on navigation (PC: the one timer re-read only the conflict banner; phone: tab entry and the manual-sync callback). Fix: a per-domain change counter, bumped by Core after every committed write and every applied sync batch (`DomainService.note_change`, `GET /v1/domains/changes` bounded long-poll, no data in the reply), and by the phone repository (`FinanceRepository.changes`, plus `SyncEngine.onApplied`). WinUI `DomainChangeWatcher` (pool-thread long-poll, 300 ms debounce, back-off, UI-thread hand-off) reloads the open Finance page or Today card quietly; Android view models reload from the flow. Phone auto sync (`AutoSyncController`): on foreground and every 60 s while open, only when paired and the setting is on (default on; switch on Devices), one sync at a time, stops after the PC revokes the phone; "Synced just now / x min ago" on Today, Finance and Devices (PC and phone). Manifest unchanged (INTERNET + CAMERA only). Tests: Python 541 passed / 2 skipped; .NET 606 passed; real-window FlaUI test fails with the watcher off and passes with it; Android JVM 140 passed, instrumented 33 OK on API 36, `sync_e2e` PASS. Notes: `docs/architecture/domain-changes.md`, `docs/security/SYNC-1e-review.md`. Ledger `SYNC-1e-refresh-after-sync` stays FAIL until the owner confirms the real-device step (`SYNC-1e-hardware`, NEEDS_HARDWARE). Sideload APK: `D:\reva-releases\v2.0.0-alpha.3\reva-v2.0.0-alpha.3-debug.apk`.
- **v2.0.0-alpha.2 (GATE-2 closed 2026-10-14):** finance track + pairing gateway + Android sync, merged to `main` by PR #1 (merge commit `1bbeeaf`, CI green on all five lanes at head `a8f4c48`). **The physical phone test PASSED** (owner-confirmed 2026-10-14: pair, 6-digit match, offline expense on both sides, sync, revoke refused); ledger rows `SYNC-1-pair-phone` and `SYNC-1d-phone` are PASS. API 36 revoke check covered by `sync_e2e` on a cold-booted Android 16 emulator (refused 401). Devices UI smoke test: 30 of 30 consecutive runs after the gateway keep-alive fix (5 s to 30 s) and test fixes; opt-in `REVA_GATEWAY_TRACE=<file>` writes per-request timing with stable reason codes. Phone "Forget" copy now says to also click Revoke on the PC. Notes: `docs/ci/alpha-2-ci-notes.md`, 30-run log `docs/ci/devices-30-run-log.txt`.
  - **Known issue SYNC-1e (ledger `SYNC-1e-refresh-after-sync`, FAIL, not fixed in alpha.2):** after a sync the screen that is already open shows the new data only after switching tabs, on both PC and phone. Data is correct once shown. Next slice: refresh/notify the open screen when a sync applies events.
  - Sideload APK for this tag is built from the merged tree; its SHA-256 is in the release notes of the tag message and the GATE-2 report. PR #2 (VOICE-1) is open and not part of this tag. Tags `v2.0.0-alpha.0` and `v2.0.0-alpha.1` exist only in the local clone; only `v2.0.0-alpha.2` has been pushed.
- SYNC-1c (branch `feat/sync-1c-devices-ui`, based on `feat/sync-1b-gateway`): WinUI Devices page (nav item now built): gateway switch with honest state, QR (QRCoder 1.6.0, MIT) with countdown, six-digit approval, paired-phone list with confirmed revoke, polling only while open; Finance conflict banner re-reads every 10 s while open. Fixtures: `tools/desktop/generate_devices_fixtures.py`. .NET 589 passed; FlaUI smoke (opt-in) 5 passed incl. an independent C# phone. Notes: `docs/architecture/devices-page.md`, `docs/security/SYNC-1c-devices-page-review.md`. Run UI tests in their own `dotnet test` call: `REVA_CORE_PYTHON_EXE` set in the same call breaks one unit test.
- SYNC-1d (branch `feat/sync-1d-android-sync`, based on `feat/sync-1b-gateway`): Android pairing and LAN sync. Keystore P-256 device key (`KeystoreDeviceSigner`), pinned-TLS gateway client, QR scan (CameraX + ZXing, on-device), Devices screen, Finance conflict banner (keep mine / keep PC's). Manifest: exactly INTERNET + CAMERA, cleartext refused. 116 JVM tests; 26 instrumented tests pass on API 31 and 36 (airplane mode); `tools/android/sync_e2e.py` pairs with a real gateway, syncs both ways and revokes on both emulators. Notes: `docs/architecture/android-sync.md`, review `docs/security/SYNC-1d-android-review.md`. Run on a real phone over Wi-Fi on 2026-10-14: PASS (see v2.0.0-alpha.2 above).
- SYNC-1b (branch `feat/sync-1b-gateway`, based on `integration/alpha-2`): pairing gateway in `reva_core/gateway/`: opt-in TLS listener on one LAN address (off by default, Devices setting `PATCH /v1/devices/gateway`), five allowlisted POST routes, QR + one-time code + 6-digit fingerprint + approval on the PC, signed requests re-checked per request, atomic revoke, third-device key directory. Core controls under `/v1/devices/*`. Keys: Credential Manager `reva.gateway.tls` / `reva.gateway.device`. Design: `docs/architecture/pairing-gateway.md`; review: `docs/security/SYNC-1b-gateway-review.md`. No UI yet (SYNC-1c WinUI Devices page, SYNC-1d Android client). Known environment issue: on this PC asyncio event-loop creation very rarely hangs (plain Python repro), so a long pytest run may need a re-run.
- **INT-1 (branch `integration/alpha-2`, merged to `main` by PR #1 on 2026-10-14):** `main` + S00-S03 + FIN-1 + FIN-2 + AND-1 + SYNC-1a merged in that order, no textual conflicts (the four branches are one linear chain from `fixing-things`). Clean-tree results: cargo test 93 passed / 1 ignored, clippy and fmt clean; Python 409 passed / 2 skipped with ruff, ruff format, mypy and the contracts check clean; .NET 518 passed (+4 FlaUI smoke with `REVA_RUN_UI_TESTS=1`); Android 86 JVM tests; instrumented suite 18 passed + 1 opt-in skipped on API 31 and API 36 in airplane mode; Kotlin conformance 97 steps. Review and decisions: `docs/security/INT-1-finance-track-review.md`. Spec pack is 2.0.5 (ARD-700 section 2.3 implementation notes).
- SYNC-1a (branch `feat/sync-1-sync`): Kernel sync core only: P-256 device-key signed events (host implements `DeviceSigner`), peer registry with scopes and revoke, per-peer cursors, whole-batch rejection, delete always wins (AC-018). The pairing gateway, QR, Devices screens, Android sync client and conflict banners (SYNC-1b to SYNC-1d) are not built.
- AND-1 (branch `feat/and-1-android`, based on `feat/fin-2-finance-ui`): `android/` app with Today, Finance, Talk placeholder, More on the Kernel via Kotlin binding; Keystore-wrapped key in noBackupFilesDir. Build: `python tools/android/build_apk.py`. 85 JVM tests; 18 instrumented tests pass on API 31 and 36 in airplane mode. CI `android` lane is still a placeholder.

- FIN-2 (branch `feat/fin-2-finance-ui`): WinUI Finance page + Today card + nav (non-built sections say coming soon), Core support (`source` column, `conflict.resolve`, privacy store, `REVA_DOMAIN_KEYSTORE=memory` test-only). .NET 518 passed; FlaUI smoke in `desktop/tests/Reva.Desktop.UiTests` is opt-in (`REVA_RUN_UI_TESTS=1`, needs `REVA_CORE_PYTHON_EXE`). Fixtures regenerate with `tools/desktop/generate_finance_fixtures.py`.

- S03-lite is done: spec pack in `docs/spec/REVA_v2.0/`, persona in `docs/persona/`, `kernel/ android/ avatar/ contracts/` skeleton, LFS attributes, pytest env guard, evidence ledger, CI lanes (`python`, `csharp-desktop`, `contracts`, `kernel` and `android` placeholders). `reva_core/` and `desktop/` were not moved; the full `core/ windows/` restructure is still open.
- Baseline (Oct 11 audit): Python 326 passed / 2 skipped, .NET 334 passed. Clean worktree at the S03 tag (2026-10-11): Python 340 passed / 2 skipped, .NET 344 passed, `ruff format --check .`, `ruff check .`, `mypy reva_core` and the contracts check all clean.
- S00 (tags `archive/pre-merge-2026-10-11/*`, bundle, backup), S01 (wake-word resolver fails closed) and S02 (owned/external Core shutdown, 10 real cycles) are committed on `fixing-things`. Evidence: `docs/archive/`.
- Parallel work lives on branches, not in this tree: `feat/pipe-1-voice` (PIPE-1.1, PIPE-1.2; replayed onto `main` by VOICE-1. Do not push the original branch: its first commit lists private recordings by name in a public repo), `wip/planner-reasoning` (planner + cloud reasoning, one known failing test `test_forged_answer_cannot_claim_action_success`), `archive/shutdown-wip` (the `Environment.Exit` variant, not adopted). Their tests still read contracts from the old `docs/08_CONTRACTS/` path; point them at `contracts/` before merging.
- `docs/spec/REVA_v2.0/SHA256SUMS.txt` has one stale entry: `08_CONTRACTS/planner-decision.schema.json` no longer matches its recorded hash (the file equals `reva_core/planner/contracts/`). Decide which version is canonical, then fix the sum.
- V1-fix is done. Real-person (Lana) material is quarantined in `F:\reva-assets\_excluded\`, and the manifest is updated.
- **Revi voice is blocked.** It's a separate project; it stays out of REVA until its manifest provenance is filled. Kokoro `af_heart` is the voice.
- `v2.0.0-alpha.0` is tagged at the end of S03. `v2.0.0-alpha.1` was tagged on `feat/fin-1-kernel` (local only); `v2.0.0-alpha.2` is the first tag pushed to GitHub.
- Open items:
  - chatterbox-v3-src: reconcile the two halves.
  - 11 Lana-derived untracked copies remain in `tools/voice-lab/revi-prosody-study/` and `tests/voice-evals/outputs/`. Inventory: `docs/voice/lana-quarantine-inventory.md`. They are in `.git/info/exclude`; deletion awaits approval.
  - The merge script pattern misses `LDR*` names.
  - The working tree still holds uncommitted PIPE-1 and planner files that are also on the branches above.

- **FIN-1 (S04 + Finance) is built on branch `feat/fin-1-kernel`, tagged `v2.0.0-alpha.1`:** Rust Domain Kernel with the Finance domain; one 97-step conformance suite passes natively, through Python and through Kotlin (JVM); Android arm64-v8a and x86_64 libraries build (not yet run on a device); Core has a Windows Credential Manager key provider (`reva.domain.finance`), `/v1/domains/*` and `/v1/today`. Details: `kernel/README.md`, ledger rows dated 2026-10-12. It is merged on `integration/alpha-2` but not into `fixing-things`: the PIPE-1 and planner branches still need merging around it (shared files: `app.py`, `lifecycle.py`, `settings.py`, the two route-whitelist tests, `pyproject.toml`).
- FIN-1 Part C (your existing data) is discovery only: nothing imported. See the FIN-1 report: the old local `reva-finance.sqlite3` is a plaintext, near-empty profile; Aura-Prod Supabase is paused; `F:\reva-data\finance-import\` does not exist.

## Working rules (non-negotiable)

1. **One Claude Code session per working tree.** For parallel work, use `git worktree add ../Reva-<slice> -b <branch>`. If `git status` shows changes you didn't make, stop and report them. Never reformat, reorder or "fix" them.
2. Work only on the named slice. List the files you will touch before editing. Keep diffs minimal.
3. Never `git reset`, `git clean`, `git push --force`, `git checkout -- <file>` on others' work, or delete untracked files. Commit only files from your slice.
4. Run `ruff format` only on files you created or fully own in this slice. Never run it repo-wide or on shared files (`lifecycle.py`, `settings.py`, etc.).
5. Tests never touch real data. `REVA_DATA_DIR` must be a temp dir, there is no production DB, and the env guard must pass.
6. No secrets in code, config, logs or test output. Keys go in Windows Credential Manager / DPAPI, or Android Keystore on the phone.
7. Voice/model assets live in `F:\reva-assets` (read it from `REVA_ASSET_ROOT`). They load only if their SHA-256 matches `assets.manifest.json` and provenance is filled. Never use anything in `_excluded\`.
8. No new services, brokers or databases beyond the ARDs.
9. Evidence or it didn't happen. Paste real test output. Anything that needs my mic, speakers, phone or GPU is marked `NEEDS_HARDWARE` with exact steps for me. Never report a skipped or mocked test as PASS. Add rows to `tests/evidence/ledger.csv` once it exists (S03).

## Safety invariants (break one = stop and ask)

- A model may **propose**. Only the deterministic policy broker **authorizes**. Only executors **act**. REVA reports success only from executor/Kernel evidence. "Done" always comes from a template, never from model text.
- `authorize()` is pure: no model calls, no I/O, no writes, and stable reason codes.
- These capabilities do not exist and must never be added: payments, transfers, purchases, bank logins, medical diagnosis or dosing, a generic shell, file deletion, sending email.
- T2 actions need a click or tap approval on the target device. A spoken "yes" is not enough.
- The Core binds to `127.0.0.1` only. Remote devices come in only through the pairing gateway.
- Hosted (cloud) models are opt-in, disclosed, and pass the per-domain consent filter. Finance, Health, Memory and Personal default to no cloud.
- The avatar shows only true state. Listening means the mic is actually open. A positive expression attached to an action requires a verified outcome.
- Mood or persona never changes tiers, permissions, or what REVA claims happened.

## Decisions already made (don't re-ask)

- **Audio capture/playback on Windows:** NAudio (MIT) with WASAPI. Pin the version and record the license. No raw interop.
- **Corx source:** use the copy inside the git-tracked Lakewood/Corx repo with the newest commit and passing tests. Report which path and commit you picked. `Ai-clean-verify` copies are not canonical. Never import menu, pricing, POS, telephony, Twilio or keys.
- **`/v1/actions/*` routes:** allowed. Change the security test deliberately in its own commit. It must allow exactly `/v1/actions/proposals`, `/v1/actions/{id}/approval` and `/v1/actions/{id}`, require auth on each, and keep every other "action" path forbidden.
- **Kokoro:** install the `kokoro` Python package into the Core env and put the Kokoro-82M weights + `af_heart` voice under `F:\reva-assets\models\tts\kokoro\`. Add 3 manifest entries: provenance `licensed`, license `Apache-2.0`.
- **Wake word:** default off; enabling requires a hash-listed `.ppn` and the AccessKey in Credential Manager. openWakeWord is evaluated as an alternative.
- **Cloud:** "cloud" means an opt-in hosted model now (Anthropic in the provider registry). Supabase sync comes later (S22).
- **Order:** P0 (S00–S03) → S05 → S06 → S07 (+wake word, +cloud) → S08 avatar → S09 apps → S04 Kernel → S10 → Android S11–S15.

## Layout

Real layout after S03-lite (the `core/` and `windows/` renames are not done).

```
reva_core/   Python Core (api, agent, memory, models, orchestration, security, storage, domains, gateway). Moves to core/ later.
desktop/     WinUI 3 app and tests (NAudio capture/playback, WebView2 avatar host, executor). Moves to windows/ later.
kernel/      Rust Domain Kernel (crate reva-kernel: SQLCipher, event log, Finance) + UniFFI bindings (generated)
android/     Kotlin/Compose app (Today, Finance, Talk placeholder, More; Kernel through the Kotlin binding; Keystore)
avatar/      three.js + three-vrm web package (placeholder until S08)
contracts/   JSON Schemas, capability registry (copy of docs/spec/REVA_v2.0/08_CONTRACTS, checked by CI)
assets/avatar/  .blend + .vrm (Git LFS rules in .gitattributes; folder created when assets arrive)
tests/       unit, integration, contract, security, e2e, evidence/ledger.csv; voice-evals is opt-in (REVA_RUN_VOICE_EVALS=1)
tools/ci/    CI helper scripts; tools/kernel/ bindings, Android libs, conformance runners, paired_devices test helper; tools/android/ build_apk.py; tools/desktop/ fixture generator; tools/voice-lab/ voice experiments (untracked, no hardcoded paths)
docs/        spec/REVA_v2.0/, persona/, archive/, voice/, plus older adr/ architecture/ development/ plans/ product/ security/ superpowers/ testing/
.github/workflows/ci.yml   lanes: python, csharp-desktop, contracts, kernel, android
```

## Commands

Run from the repo root. `.venv\Scripts\python -m ...` is the Core environment.

- Python: `python -m pytest -q` (the env guard sets a temp `REVA_DATA_DIR`; a non-temp value or a non-localhost DB URL aborts the run) · `ruff check <files>` · `ruff format <your files only>` · `mypy reva_core`
- Contracts: `python tools/ci/check_contracts.py` (needs `jsonschema`)
- .NET: `dotnet build desktop\Reva.Desktop.sln` · `dotnet test desktop\Reva.Desktop.sln` (run with `REVA_DATA_DIR` unset)
- Rust: `cargo test -p reva-kernel` · `cargo clippy --workspace --all-targets -- -D warnings` · `cargo fmt --all`
- Kernel bindings: `python tools/kernel/build_bindings.py` · `python -m pytest tests/cross_binding` · `python tools/kernel/run_kotlin_conformance.py` · `python tools/kernel/build_android.py`
- Android (`cd android`, `ANDROID_HOME` set): `./gradlew :app:testDebugUnitTest` · sync end to end on an emulator: `python tools/android/sync_e2e.py --serial emulator-5554` · sideload APK: `python tools/android/build_apk.py` · emulator suite: `./gradlew :app:connectedDebugAndroidTest -Preva.uiTests=true -Pandroid.testInstrumentationRunnerArguments.requireAirplane=true` (set `ANDROID_SERIAL`, turn airplane mode on first)

## Skills to use in this repo

- `architecture-design`: before any slice that changes a boundary (S04, S06, S13, S22).
- `security-review`: on every slice touching auth, routes, grants, pairing, secrets or sync, before commit.
- `code-review`: on the full diff before every commit.
- `cicd-setup`: S03 CI lanes and the release lanes in S25/S26.
- `tech-stack-eval`: library choices (NAudio vs alternatives, wake-word engines, STT model size).
- `mvp-scoping`: when a slice grows past one session. Split it; don't stretch it.
- `prd-writing` / `roadmap-planning`: only if the spec itself must change.
- `skill-creator`: to build project skills `reva-slice-runner` (preamble + report format) and `reva-evidence-ledger` (append and verify ledger rows) in `.claude/skills/`.
- `playwright-cli`: only for the avatar web package test page, not for WinUI.
- Other skills (sales, marketing, fundraising, SEO, etc.) are not used here.

## End-of-slice report (always)

Summary · Files changed · Commands + real results · Requirements → evidence rows · NEEDS_HARDWARE steps · Not done / risks · Ready for next slice (yes/no + why). Commit as `<SLICE-ID>: <summary>`. Tag only when the slice says so.

## Stop and ask when

- a test would touch real data,
- a security check fails open,
- someone else's changes are in the tree,
- the spec is ambiguous in a way that changes architecture,
- or a task needs something listed under the safety invariants.
