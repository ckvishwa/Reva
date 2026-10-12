# CLAUDE.md — REVA 2.0

REVA is a personal AI that you talk to through an animated avatar. It has a WinUI 3 Windows app and a Kotlin/Compose Android app, and each one works on its own. Eight life domains (Memory, Finance, Health, Coach, Career, Learn, Cyber, Personal) live in one shared Rust Domain Kernel. A Python Core on the PC handles voice, planning, policy and sync. Single user, local-first; any cloud use is opt-in.

## Source of truth

- Specs: `docs/spec/REVA_v2.0/` (README, CHANGELOG, SHA256SUMS, `01_PRD` … `11_PROMPTS`). Read the slice you are working on in `docs/spec/REVA_v2.0/04_SLICES/REVA_Version_Slices_v2.0.md`, then the ARDs it cites in `docs/spec/REVA_v2.0/02_ARD/`.
- Decisions: `docs/spec/REVA_v2.0/03_ADR/REVA_ADR_Register_v2.0.md` (ADR-001 to ADR-040). Contracts: `contracts/` at the repo root is a copy of `docs/spec/REVA_v2.0/08_CONTRACTS/`; keep them identical (CI checks it).
- Prompts and build order: `docs/spec/REVA_v2.0/11_PROMPTS/REVA_Slice_Playbook_and_Prompts_v2.0.md`.
- Persona: `docs/persona/REVA_Persona.md`.
- If `docs/spec/REVA_v2.0/` is missing or the paths differ (for example the old `docs/08_CONTRACTS/`), stop and tell me. Don't guess paths.

## Current state (update this section at the end of every slice)

- Baseline (Oct 11 audit): Python 326 passed / 2 skipped, .NET 334 passed.
- PIPE-1 steps 1–2 (TTS registry + Kokoro provider, voice sessions + WebSocket) are built and **uncommitted**. Python is at 439 passed / 2 skipped. Steps 3–9 have not started. `v2.0.0-alpha.1` is not tagged.
- 3 failing tests came from a parallel session (route whitelist ×2, voice-unavailable reply text). The mypy errors are in `planner/*`.
- V1-fix is done. Real-person (Lana) material is quarantined in `F:\reva-assets\_excluded\`, and the manifest is updated.
- **Revi voice is blocked.** It's a separate project; it stays out of REVA until its manifest provenance is filled. Kokoro `af_heart` is the voice.
- Open items:
  - chatterbox-v3-src: reconcile the two halves.
  - Lana-derived untracked copies are still in `tools/voice-lab/revi-prosody-study/` and `tests/voice-evals/outputs/`. Delete them before any commit.
  - The merge script pattern misses `LDR*` names.

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

The current layout is pre-S03: `reva_core/` (Python Core) and the desktop WinUI app. The S03 target is below.

```
core/        Python Core (sessions, voice, planner, policy, providers, sync)
kernel/      Rust Domain Kernel + UniFFI bindings (Python, Kotlin)
windows/     WinUI 3 app (NAudio capture/playback, WebView2 avatar host, executor)
android/     Kotlin/Compose app
avatar/      three.js + three-vrm web package (shared by both apps)
contracts/   JSON Schemas, capability registry
assets/avatar/  .blend + .vrm (Git LFS)
tests/       unit, contract, cross-binding, security, voice-evals, e2e, evidence/ledger.csv
tools/voice-lab/  voice experiments (read REVA_ASSET_ROOT; no hardcoded paths)
docs/        spec/, persona/, voice/, archive/
```

## Commands

Fill in the exact forms in S00 and keep them current.

- Python: `pytest -q` · `ruff check <files>` · `ruff format <your files only>` · `mypy <package>`
- .NET: `dotnet build` · `dotnet test`
- Rust (after S04): `cargo test -p reva-kernel` · `cargo clippy`
- Android (after S11): `./gradlew lint testDebugUnitTest`

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
