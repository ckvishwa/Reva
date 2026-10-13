# REVA — Architecture Decision Register v2.0

**Document ID:** REVA-ADR-INDEX-002 · **Version:** 2.0.2 · **Date:** 2026-10-12
Each ADR: decision, rejected alternatives, consequence, reversal trigger, proof. v1 ADR full text is in `09_ARCHIVE_v1/03_REVA_ADR_DECISIONS.md`.

## Part A — v1 ADRs, status in v2

| ADR | Title | v2 status |
|---|---|---|
| 001 | Keep existing Windows (WinUI 3) and Python architecture | **Kept.** Rejects Tauri/Flutter/Electron rewrites. Trigger: dominant third platform or Windows UI maintenance becomes the bottleneck |
| 002 | Android native Kotlin + Compose | **Kept.** Flutter (AuraO) retired |
| 003 | One modular monolith Core | **Kept.** Kernel is a library inside it, not a service |
| 004 | Provider-neutral voice pipeline | **Amended by ADR-025, then ADR-040** (Revi first when it passes the voice gate; Kokoro fallback) |
| 005 | Full duplex is an enhancement | Kept |
| 006 | Local-first memory with explicit controls | **Amended by ADR-027/028** (memory moves into the Kernel, encrypted) |
| 007 | Deterministic action policy separate from LLM | Kept |
| 008 | Target-device approval for sensitive remote actions | Kept |
| 009 | Loopback Core + distinct pairing gateway | Kept |
| 010 | Peer authentication, QR pairing | Kept |
| 011 | JSON events + binary audio over local WebSocket | Kept; avatar events ride the same channel |
| 012 | Android background hotword gated by feasibility | Kept |
| 013 | Hybrid speech/provider strategy on Android | Kept |
| 014 | Durable outbox and tombstone sync | **Extended by ADR-029/031** |
| 015 | Windows secrets in OS credential storage | Kept; covers domain keys |
| 016 | Package the product, not the dev environment | Kept; adds Kernel library |
| 017 | Local security and observability | Kept |
| 018 | Third-party voice infrastructure selectively | Kept |
| 019 | First-class AI/ML subsystem; one bounded planner | Kept; max 2 steps in 2.0 |
| 020 | Native UI grounding with observed outcomes | **Partly deferred by ADR-036** (UIA kept at R2; VLM to Future) |
| 021 | Android Play: intents and user-directed flows | Kept |
| 022 | Typed model/native contracts; defer gRPC | Kept; `07` proto is reference only |

## Part B — New ADRs

### ADR-023 — Merge FRIDAY OS into the Reva repo; retire Next.js, Flutter, Tauri after harvest
- **Decision:** `D:\Projects\Reva` is the only product repo. FRIDAY OS/AuraO features are re-implemented from harvested designs and tests.
- **Rejected:** merging the AuraO monorepo wholesale; keeping a cloud Next.js backend.
- **Consequence:** one stack, one test suite; some TypeScript work is rewritten.
- **Trigger:** none expected.
- **Proof:** AuraO archived; harvested tests pass in Reva.

### ADR-024 — Avatar: VRM model, three.js in a WebView on both platforms
- **Decision:** Blender → VRM 1.0; three.js + three-vrm in WebView2 and Android WebView; driven only by session events.
- **Rejected:** Unity embed (size, licensing, two runtimes); native DirectX/OpenGL renderer per platform (double work); 2D sprite only (kept as fallback).
- **Consequence:** one avatar codebase; WebView GPU cost to watch.
- **Trigger:** AR-WIN-007 or AR-AND-015 budgets fail.
- **Proof:** offline load, FPS/GPU profile, lip-sync offset.

### ADR-025 — Kokoro first TTS (amends ADR-004)
- **Decision:** Kokoro-82M `af_heart` first; Chatterbox second.
- **Rejected:** Chatterbox first (never verified live); cloud TTS default.
- **Trigger:** Chatterbox wins a blind listening test at equal latency.
- **Proof:** real synthesis, interrupt, orphan-free shutdown tests.

### ADR-026 — Single-user personal framing; monetization parked
- **Decision:** optimize for one owner's privacy, reliability and daily use; v1 PRD §15 parked.
- **Rejected:** multi-tenant SaaS architecture now.
- **Trigger:** decision to ship to outside users.

### ADR-027 — Domain Kernel in Rust with UniFFI bindings
- **Decision:** all domain rules and storage in one Rust crate, bound to Python (Core) and Kotlin (Android); Swift later.
- **Rejected:** implementing each domain twice (Python + Kotlin); Kotlin Multiplatform (does not reach the Python Core); a cloud domain server (breaks offline and privacy); Python on Android (heavy, poor fit).
- **Consequence:** Rust toolchain and Android NDK in the build; one test suite for both devices.
- **Trigger:** Android cross-build or SQLCipher on NDK fails the S04 spike → fall back to schema-generated models with thin per-platform services.
- **Proof:** AR-DOM-001 cross-binding conformance.

### ADR-028 — One SQLCipher file per domain; keys in the OS vault
- **Decision:** separate encrypted file per domain; per-domain key in DPAPI/Credential Manager or Android Keystore; Core SQLite stays separate.
- **Rejected:** one shared database; app-level field encryption as default; storing keys in config.
- **Consequence:** independent wipe/export per domain; more files to migrate.
- **Proof:** AR-DOM-002, AR-AND-010.

### ADR-029 — Event-sourced domain writes with projections
- **Decision:** every write is an event in the domain log + outbox; tables are projections.
- **Rejected:** row-level last-write-wins sync; CRDT library adoption in 2.0.
- **Consequence:** sync and audit come for free; storage grows (compaction is Future).
- **Proof:** AR-DOM-004, AR-DATA-010/011.

### ADR-030 — Android local brain sharing the capability registry
- **Decision:** Android runs its own session, planner client and policy broker loaded from the same registry artifact as the Core.
- **Rejected:** phone as a thin PC client forever (breaks R3); separate Android tiers.
- **Proof:** registry parity test; AR-AND-011.

### ADR-031 — Opt-in relay with device-side encryption on Supabase (amends FR-048)
- **Decision:** LAN direct default; optional relay storing only events encrypted on the devices with a pairing-delivered group key.
- **Rejected:** Supabase as primary database; server-readable sync; key escrow in 2.0.
- **Consequence:** key loss requires re-pairing.
- **Trigger:** adversarial review fails → relay stays disabled.
- **Proof:** AR-DATA-013, AR-DATA-014.

### ADR-032 — Per-domain privacy switches; sensitive domains closed to hosted models by default
- **Decision:** sync / devices / hosted-model switches per domain; hosted access default off for Memory, Finance, Health, Personal.
- **Proof:** AR-CORE-010, AR-DOM-009.

### ADR-033 — Domain safety limits: no money movement, no medical advice
- **Decision:** payment, transfer, purchase, bank-login and medical-dosing capabilities are absent from every registry; health safety routing.
- **Rejected:** "T3 with approval" for payments (any path is a risk).
- **Proof:** AR-AGT-018, AR-DOM-007.

### ADR-034 — Health Connect read-only as the Android health source
- **Decision:** read granted types only; manual entry and import on both devices; no Windows health platform.
- **Rejected:** writing to Health Connect; vendor wearable cloud APIs in 2.0.
- **Trigger:** Play health-apps declaration rejected → manual entry and import only.
- **Proof:** AR-AND-013.

### ADR-035 — Provider registry: Ollama default, hosted opt-in
- **Decision:** Ollama on PC by default (model chosen by eval); Anthropic or other hosted only when enabled and disclosed; consent filter per domain.
- **Proof:** AR-CORE-003, AR-CORE-010.

### ADR-036 — Deferrals to Future
- **Decision:** VLM grounding, 3+ step UI workflows, email/calendar integrations, MediaProjection, narrow Accessibility, gRPC transport move to Future.
- **Rejected:** keeping them in R2/R3 scope.
- **Trigger:** 2.0.0 shipped and a measured need appears.

### ADR-037 — Reuse the Lakewood/Corx voice structure
- **Decision:** port the proven Corx/Lakewood patterns into REVA: VAD with ~280 ms end-of-speech and pauses handled as follow-up turns; acknowledge-first turn-taking; Whisper with a words-only vocabulary prompt; per-stage latency measurement from the first slice; propose → authorize → commit with `AuthorizationDecision`; exact → alias → fuzzy → vector → ask resolution ladder; every failed turn becomes a regression fixture. If Corx is already decoupled from ordering logic, publish it as a standalone package used by both products; otherwise port into `core/voice/` with its tests.
- **Rejected:** importing Lakewood wholesale (telephony, menu, pricing, POS, restaurant data, keys — out of scope per v1 PRD §3); reusing Lakewood WER/latency numbers without re-measuring (8 kHz phone audio vs wideband desk mic).
- **Proof:** S06/S07 fixtures; WER and latency re-measured on REVA hardware.

### ADR-038 — Voice asset governance
- **Decision:** models, datasets and run outputs live outside git in an asset root; `assets.manifest.json` records path, SHA-256, size, engine, source, license and provenance status for each; providers load a voice only if its hash matches the manifest (same fail-closed rule as wake-word files). Environments are rebuilt from frozen requirements, not copied. Files named after real people are excluded from the repo and from every dataset. The source tool's terms must allow training on its outputs before a dataset is used.
- **Rejected:** committing models/venvs to git; unknown-provenance datasets.
- **Proof:** AR-VA-020, manifest schema validation, `Merge-RevaVoiceWorkspace.ps1` log.

### ADR-039 — Layered NLU and NLG
- **Decision:** normalize → rule fast path → resolution ladder → dialogue state → LLM planner fallback → pure `authorize()`; NLG by templates for every outcome, grounded LLM answers only for open questions, number/claim check, spoken rewrite. Shared artifacts on Windows and Android.
- **Rejected:** LLM-only understanding; model-written confirmations; auto-resolving vector matches before calibration.
- **Proof:** ARD-450 AR-LANG-001–018.

### ADR-040 — Revi as REVA's voice (amends ADR-025)
- **Decision:** the trained Revi voice becomes the default TTS once it passes the voice gate (AR-VA-021) on the engine chosen by the bakeoff, with a license that allows this use; Kokoro `af_heart` is the fallback. Telugu output must pass its own eval before Telugu is enabled.
- **Rejected:** shipping a voice with unrecorded provenance or a non-permissive engine/model license for the intended use.
- **Trigger:** Revi fails latency or interrupt gates on the PC → Kokoro stays default and Revi is offered as "high quality, slower".
- **Proof:** V2–V4 slices, AR-VA-020/021.

## Governance

Each ADR change names affected FR/NFR/AR IDs, files, migration impact, measurable reason, proof and rollback; adopted by commit on the main branch.
