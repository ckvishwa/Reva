# Changelog

## 2.0.6 — 2026-10-12
- ARD-500: implementation note for the pairing gateway (SYNC-1b); new contract `pairing-qr.schema.json`.

## 2.0.5 — 2026-10-12
- ARD-700: new section 2.3 Implementation notes (API names, error variants, event signatures, sync API, Finance rules, key handling on both devices, privacy store). The API block in 2.1 now matches the code.
- ARD-500 section 3: note on P-256 device-key signatures and per-peer cursors.
- There is no 2.0.4 entry in this pack; 2.0.5 follows 2.0.3.

## 2.0.3 — 2026-10-12
- New `11_PROMPTS/REVA_Slice_Playbook_and_Prompts_v2.0.md`: build order with reasons, feature first/second-version splits, Claude Code session preamble, detailed prompts for V1, S00–S10, V2, V3 and compact prompts for S11–S27, V4, A1–A4.
- `Merge-RevaVoiceWorkspace.ps1` fixed after the first real run: `-Force` for hidden/read-only items; every copy/move wrapped so one failure no longer stops the run; identical files already in the repo marked `ALREADY_DONE`; symlinks and model caches (`tmpdir`, `pretrained_models`, `.cache`, `huggingface`) skipped in code copies and not hashed; manifest built from everything already moved, so resumed runs keep complete entries. Tested with PowerShell 7.4: hidden folder, read-only files, broken symlinks, partial earlier run, forced move failure, resume.

## 2.0.2 — 2026-10-12
- New ARD-450 Language Understanding and Generation (NLU/NLG) with AR-LANG-001–018, built on Lakewood patterns (rule interpreter, resolution ladder, dialogue state, propose → authorize → commit, learning events).
- New ADR-037 (reuse Lakewood/Corx voice structure), ADR-038 (voice asset governance), ADR-039 (layered NLU/NLG), ADR-040 (Revi as default voice after the voice gate; amends ADR-025).
- ARD-400: Corx VAD/endpointing, Whisper vocabulary prompt, Revi provider, AR-VA-020–022 (manifest-verified voices, voice gate, timings from S06).
- PRD: FR-LNG-001–006 (fast commands, ask-don't-guess, follow-up references, number fidelity, Revi voice, Telugu).
- Slices S05, S06, S07, S09, S10, S12, S24 updated; new parallel voice track V1–V4.
- New contracts: nlu-frame, authorization-decision, voice-asset-manifest schemas.
- New tool: `10_TOOLS/Merge-RevaVoiceWorkspace.ps1` (tested on a mock of the workspace with PowerShell 7.4: dry run, apply, conflict handling, manifest merge preserving user edits).

## 2.0.1 — 2026-10-11
Re-check of the full v1.1 pack. Fixes applied:
1. PRD had no Finance/Health/domain requirements → PRD v2 §7 adds FR-DOM, FR-MEM, FR-FIN, FR-HLT, FR-COA, FR-CAR, FR-LRN, FR-CYB, FR-PER, FR-TDY, FR-SYN; ARD-700 written in full.
2. Draft 2.0 ran domains only on the PC (broke standalone Android, AR-068) → shared Rust Domain Kernel on both devices (ADR-027).
3. v1 non-goal "no autonomous purchases or transfers" → no money-movement capability exists anywhere (ADR-033, registry absence test).
4. Off-LAN relay (FR-048 Future) and v1 ban on unproven E2EE claims → opt-in R3 relay behind adversarial gate (ADR-031).
5. v1 P0 rule "preserve unrelated dirty work, no reset/clean" → cleanup archives to branches.
6. ADR-001 rejects Tauri/Flutter/Electron → reversal trigger aligned to ADR-001's own.
7. ADR-004 named Chatterbox first → amended by ADR-025 (Kokoro first).
8. v1 execution doc calls AuraO deleted → harvest only from surviving copies.
9. `08_REVA_PLANNER_DECISION_schema.json` did not match README/SHA256SUMS name → renamed in archive; checksums now verify.
10. Byte-identical duplicate `REVA_Full_PRD_ARD_AI_ML_Agent_2026-10-11__1_.md` removed.
11. Health data sources added: Health Connect read-only on Android, manual/import on both (ADR-034).

## 2.0.0 — 2026-10-11
FRIDAY OS merged into REVA; avatar (VRM/three.js/WebView); Kokoro first; single-user framing; 9 ARDs; ID namespaces; deferrals (VLM, multi-step UI workflows, email, gRPC).

## 1.1 — 2026-10-11 (archived)
Original REVA cross-platform pack with AI/ML action-agent extension.
