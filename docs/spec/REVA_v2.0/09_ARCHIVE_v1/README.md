# REVA Cross-Platform Specification Pack

**Version:** 1.1 | **Created:** 2026-10-11 | **Status:** Proposed specification, not repository implementation.

## Files, read in this order

1. `01_REVA_MASTER_PRD.md` — main product vision, original 60 functional requirements, 16 NFRs; AI agent extension cross-references.
2. `02_REVA_MASTER_ARD.md` — architecture diagrams, original 82 technical requirements, plus explicit AI agent extension.
3. `03_REVA_ADR_DECISIONS.md` — 22 choices including rejected alternatives, tradeoffs, reversal triggers and evidence.
4. `04_REVA_REQUIREMENTS_TRACEABILITY.md` — full requirement-by-requirement register with proposed test IDs.
5. `05_REVA_EXECUTION_AND_QA.md` — two-person delivery plan, test matrix, sprint gates, first 24-hour tasks and agent handoff prompt.
6. `06_REVA_AI_ML_ACTION_AGENT_PRD_ARD.md` — **NEW**: 10 AI/ML layers, 28 FR-AI + 36 AR-AI requirements, screen understanding, policy, native executor, proof and agent evals.
7. `07_REVA_NATIVE_AGENT_V1.proto` — **NEW**: proposed typed native executor contract (not compiled into app).
8. `08_REVA_PLANNER_DECISION.schema.json` — **NEW**: strict model output schema (validated locally).

## What this pack is not

- Not an installer or APK.
- Not proof Android code exists; Android was still an `android/README.md` placeholder in the supplied October 11 audit.
- Not a code migration or a Git commit. Existing branch/worktree was not modified here.
- Not a promise of unrestricted background wake word on Android or complete hardware parity.

## Core architectural choice

**One REVA product, native WinUI 3 Windows + native Kotlin Android, a modular Python Core, shared typed contracts, deterministic action policy, local/private memory, staged secure pairing, provider-independent voice.**

## Release path

P0 security/lifecycle → R1 Windows audible assistant → R2 Android paired APK → R3 independent Android assistant with sync → R4 installed/signed full V1.

## External evidence

See sources in PRD §18 and ARD §17. The source code itself must be re-inspected before any implementation: audit state is dated 2026-10-11.

## AI and ML explicit placement (extension v1.1)

AI/ML is not the transport. Real reasoning (opt-in ADK + Ollama/provider), VAD/STT, embedding retrieval, optional user-consented VLM UI grounding and TTS sit **above** a deterministic independent policy broker and **beside** native OS adapters. New extended requirements total **88 FR** (60 original + 28 extension) and **118 AR** (82 original + 36 extension), with the original 16 NFRs preserved. New agents and Android remain planned.
