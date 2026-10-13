# ARD-300 — REVA Core v2.0

**Document ID:** REVA-ARD-300 · **Version:** 2.0.1 · **Date:** 2026-10-11 · **Status:** Proposed
**Replaces:** ARD v1 §3, §10, §11. **Decisions:** ADR-003, ADR-011, ADR-022, ADR-035, ADR-036.

## 1. Summary

The Core is one Python process on the PC (modular monolith). It owns sessions, voice coordination, planning, policy, sync, audit and the provider registry, and it loads the Domain Kernel through UniFFI Python bindings for all domain data. It binds loopback only. Heavy TTS or model work may run in a supervised subprocess (ADR-003).

## 2. Packages

```text
core/reva_core/
  api/            existing routes + v2 routes (§4)
  session/        SessionCoordinator, turn_epoch, deadlines
  voice/          VAD, STT, TTS adapters (ARD-400)
  planner/        model calls, PlannerDecision validation (ARD-600)
  policy/         capability registry loader, tiers, grants (ARD-600)
  tools/          tool adapters; domain tools call the Kernel
  domains/        thin API layer over the Kernel binding (no domain logic)
  sync/           outbox transport, LAN gateway client, relay client (ARD-500)
  devices/        pairing grants, identities (ARD-500)
  providers/      provider registry (models, STT, TTS)
  observability/  redacted events, traces, local metrics
  storage/        Core SQLite WAL: conversations, messages, sessions, audit, actions
```

`domains/` only translates HTTP ↔ Kernel calls. Any domain rule found in Python is a defect (AR-CORE-009).

## 3. Session state machine

`Idle → AcquiringPermission → Listening → Endpointing → Transcribing → Reasoning → [ApprovalPending → Executing] → Speaking → Listening | Idle`. Any state → `Cancelling` → `Idle`. Errors → `RecoverableError` or `FatalError` with cleanup. A valid interrupt increments `turn_epoch`, stops playback and invalidates older audio, model output and tool results. The avatar state is a projection of this machine (ARD-400 §4).

## 4. API

Kept: `/v1/messages`, `/v1/memories`, `/v1/voice/transcriptions`, `/v1/voice/speech`, `/v1/audit-events`, health, version.

| Route | Method | Purpose |
|---|---|---|
| `/v1/voice/sessions` | POST | Open voice session |
| `/v1/voice/sessions/{id}` | DELETE | Cancel and release |
| `/v1/voice/sessions/{id}/events` | WebSocket | Session events, transcripts, avatar events, proposals; binary audio frames |
| `/v1/actions/proposals` | POST | Policy-reviewed proposal |
| `/v1/actions/{id}/approval` | POST | Signed target-device approval |
| `/v1/actions/{id}` | GET | Outcome and evidence |
| `/v1/domains` | GET | Enabled domains, schema versions, privacy switches |
| `/v1/domains/{domain}/{collection}` | GET/POST | Query / create (Kernel command) |
| `/v1/domains/{domain}/{collection}/{id}` | GET/PATCH/DELETE | Read / edit / tombstone |
| `/v1/domains/{domain}/export` | GET | Export CSV/JSON |
| `/v1/domains/{domain}/import` | POST | File import with row report |
| `/v1/today` | GET | Today summary across enabled domains |
| `/v1/settings/privacy` | GET/PATCH | Per-domain sync / devices / hosted-model switches |
| `/v1/devices/pair`, `/v1/devices/{id}/revoke` | POST | Gateway only / owner on PC |
| `/v1/sync/events`, `/v1/sync/cursor` | POST/GET | Paired scoped identity |

Error taxonomy: v1 list kept, plus `DOMAIN.VALIDATION`, `DOMAIN.LOCKED` (key unavailable), `DOMAIN.MIGRATION_FAILED`, `DOMAIN.CONSENT_REQUIRED`, `AVATAR.UNAVAILABLE`.

## 5. Provider registry

| Kind | Default | Opt-in | Rule |
|---|---|---|---|
| Reasoning | Ollama (model chosen by FR-AI-002 eval) | Anthropic or other hosted | Hosted sees domain data only for consented domains; disclosure in Settings |
| STT | faster-whisper (size by WER/latency eval) | consented provider | — |
| TTS | Kokoro `af_heart` | Chatterbox (local) | — |
| Embeddings | Ollama embedding model | — | Lexical fallback always works (AR-052) |
| Deterministic | test/fake provider | — | Never the silent default in consumer mode (ADR-019) |

## 6. Requirements

| ID | Stage | Requirement | Verification | Replaces |
|---|---|---|---|---|
| AR-CORE-001 | R1 | One active turn per session; `turn_epoch` cancels older STT, model, tool and TTS results | Late-response injection | AR-003, AR-007, AR-020, AR-AI-006 |
| AR-CORE-002 | R1 | Separate deadlines for VAD/STT, model, tool, TTS | Timeout fixture | AR-008, FR-008 |
| AR-CORE-003 | R1 | Provider registry with capability-driven selection; Ollama default, hosted opt-in | Fake + real provider contract tests | AR-019, AR-AI-001, M-14 |
| AR-CORE-004 | P0 | Tests never use a real data dir or non-local database (harvested env guard) | Guard test with spawned child | NFR-008 |
| AR-CORE-005 | R1 | Session/turn/correlation IDs on every event | Trace assertions | AR-004 |
| AR-CORE-006 | R1 | Additive protocol evolution within a major; unknown major rejected | Compatibility tests | AR-006 |
| AR-CORE-007 | R2 | Core loopback only, bearer auth; remote access only via gateway | Port scan + auth tests | AR-010, NFR-001 |
| AR-CORE-008 | R3 | Config resolution explicit per device/provider/domain; secrets encrypted | Precedence tests | AR-012 |
| AR-CORE-009 | R1 | No domain rule in Python; `domains/` maps HTTP to Kernel only | Architecture test: no SQL or business rules in `domains/` | new |
| AR-CORE-010 | R1 | Hosted-model calls pass a consent filter that strips fields from non-consented domains | Network capture per domain | FR-DOM-006 |
| AR-CORE-011 | R4 | Schema migrations for Core SQLite are versioned and reversible | Snapshot migration | AR-013, AR-055 |
| AR-CORE-012 | R1 | Every queue bounded with documented saturation behavior | Load tests | AR-075, AR-015 |
| AR-CORE-013 | R4 | Opt-in, redacted, removable telemetry | Opt-out tests | AR-082, NFR-016 |
