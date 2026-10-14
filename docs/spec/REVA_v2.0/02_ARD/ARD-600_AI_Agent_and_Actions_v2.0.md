# ARD-600 — AI Agent and Actions v2.0

**Document ID:** REVA-ARD-600 · **Version:** 2.0.1 · **Date:** 2026-10-11 · **Status:** Proposed
**Replaces:** v1 ARD §5, §18 and `06_REVA_AI_ML_ACTION_AGENT_PRD_ARD.md` (archived). **Decisions:** ADR-007, ADR-019, ADR-020, ADR-021, ADR-022, ADR-033, ADR-036.

## 1. Summary

One bounded planner per turn. The model returns a `PlannerDecision` (answer, clarify, propose_action, propose_plan — schema in `08_CONTRACTS/planner-decision.schema.json`). A deterministic policy broker computes the risk tier from the capability registry, asks for approval when needed, and issues a signed grant. A native executor acts and returns evidence. REVA speaks only what evidence supports. The Android local brain uses the same schema, registry and broker logic.

## 2. Capability registry

Single source: `08_CONTRACTS/capability-registry.v2.json` (versioned artifact, AR-AI-036). Each entry: `capability`, `device` (windows / android / kernel), `args_schema`, `tier`, `confirm_on` (target device), `idempotent`, `evidence_kind`.

| Group | Examples | Tier |
|---|---|---|
| Info | answer, memory recall, domain queries (`finance.summary`, `health.weekly`, `today.get`) | T0 |
| Safe reversible | `windows.app.open` (allowlist), `android.app.open` (intent), navigate within REVA | T1 |
| Sensitive | `windows.app.close`, `memory.remember`, `finance.add_transaction`, `health.log_workout`, `personal.reminder.create`, `android.alarm.set`, share | T2 |
| High risk | shell, delete files, send email, install software, security settings | T3 — denied |
| Does not exist | any payment, transfer, purchase, bank login, medical dosing | absent from registry |

## 3. Turn protocol

1. Final transcript (never partial) enters planner with sanitized context: retrieved memory, Kernel query results (minimal fields), live capability list.
2. Planner output validated against schema; unknown fields rejected.
3. Deterministic fast path for known commands ("open Notepad") skips the model (AR-AI-008).
4. Policy computes tier; T2 → approval bound to action ID, canonical args, target, user, expiry; T3 → deny.
5. Executor runs `execute_once(idempotency_key)`; returns `attempted | observed | verified | failed | denied | unknown` with evidence.
6. Speech and avatar expression derived from the result status only.

## 4. Platform action surfaces

- **Windows:** process launch/close via allowlist; UI Automation inspect, invoke, set-text with fresh snapshot IDs (R2); no coordinate clicks without fresh grounding; no secure/elevated desktops.
- **Android:** Intents and public APIs only; no AccessibilityService agent; MediaProjection is Future.
- **Kernel:** domain writes are T2 tools whose evidence is the Kernel's committed event ID.

## 5. Deferred to Future (ADR-036)

VLM screenshot grounding (FR-AI-022, AR-AI-021, AR-AI-031), 3+ step UI workflows (FR-AI-019, AR-AI-029, AR-AI-030), email draft/send workflows (FR-AI-020, FR-032), MediaProjection (AR-AI-025), narrow Accessibility (FR-AI-027), gRPC executor transport (`07` proto kept as reference).

## 6. Requirements

| ID | Stage | Requirement | Verification | Replaces |
|---|---|---|---|---|
| AR-AGT-001 | R1 | Model can request only registered capabilities; no raw shell, paths or scripts | Injection tests | AR-030, AR-AI-003 |
| AR-AGT-002 | R1 | Proposals schema-validated and normalized before policy | Property fuzz | AR-031, FR-023 |
| AR-AGT-003 | R1 | Tier computed from registry, never from model or network hints | Tamper tests | AR-032, AR-AI-004 |
| AR-AGT-004 | R1 | Approval bound to action ID, canonical args, target, user, scope, TTL | Replay/substitution | AR-033, AR-AI-005 |
| AR-AGT-005 | R1 | Executor records verified/failed/unknown with OS or Kernel evidence | Mock + physical | AR-034, AR-AI-007 |
| AR-AGT-006 | R1 | Denied when confirmation absent, stale, ambiguous or speech-only for T2+ | Negative suites | AR-035, FR-025 |
| AR-AGT-007 | R2 | Remote ops authorized against sender AND target policy | Cross-device substitution | AR-037, AR-AI-026 |
| AR-AGT-008 | R2 | Android actions via sanctioned APIs and runtime grants | Device tests | AR-038, AR-AI-022, AR-AI-023 |
| AR-AGT-009 | R1 | One bounded planner loop: max steps 2 in 2.0, runtime and tool budget, cancel propagation | Runaway tests | AR-039, AR-AI-009 |
| AR-AGT-010 | R4 | Immutable action ledger with redacted args, user-inspectable | Reconciliation | AR-040, FR-033 |
| AR-AGT-011 | R1 | Planner consumes sanitized context and live registry; no OS authority | Prompt fixture | AR-AI-002 |
| AR-AGT-012 | R1 | Deterministic fast path for known commands | Cross-provider routing | AR-AI-008 |
| AR-AGT-013 | R1 | Model chosen by measured tool-call accuracy, latency, footprint, privacy | Eval report | AR-AI-010 |
| AR-AGT-014 | R1 | Model narration never becomes evidence | Forged tool response | AR-AI-011 |
| AR-AGT-015 | R1 | Screen, tool, import and synced text marked untrusted and delimited | Injection corpus | AR-AI-012, NFR-013 |
| AR-AGT-016 | R2 | Executors validate grant binding: action, target, expiry, actor, idempotency key | Forged grant / replay | AR-AI-028 |
| AR-AGT-017 | R2 | Typed semantics shared across HTTP/WS; transport is an implementation detail | JSON parity test | AR-AI-027 |
| AR-AGT-018 | R2 | No payment/transfer/purchase/medical-dosing capability exists in any registry | Registry absence test | ADR-033 |
| AR-AGT-019 | R3 | RAG retrieves only retained, consented data; deletion removes FTS and vectors | Deleted-item retrieval | AR-AI-032, AR-051 |
| AR-AGT-020 | R4 | Benchmarks: task completion, schema validity, false-success, WER, first audio, barge-in | Hardware matrix | AR-AI-034 |
| AR-AGT-021 | R4 | Synthetic/consented fixtures separated from live runs; versions pinned in evidence | Evidence audit | AR-AI-035 |
| AR-AGT-022 | R4 | Prompts, model config, registry, policy tables, retention versioned as artifacts | Reproducibility | AR-AI-036 |

## 7. Evaluation thresholds (2.0.0)

False-success 0/100 · unapproved T2 executions 0 · schema-valid planner outputs ≥ 98% on the intent eval · domain answers with invented numbers 0/100 · health safety eval 100% routed correctly on urgent-symptom set.
