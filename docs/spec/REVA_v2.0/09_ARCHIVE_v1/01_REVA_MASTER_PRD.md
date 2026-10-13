# REVA — Master Product Requirements Document (PRD)

**Document ID:** REVA-PRD-001  
**Version:** 1.0 — architecture baseline / proposed requirements  
**Date:** 2026-10-11  
**Product:** REVA — voice-first personal assistant  
**Target clients:** Windows desktop + Android APK (later Play Store AAB)  
**Document status:** Proposed for implementation; *does not* claim these features are built.  
**Reference implementation:** `D:\Projects\Reva`, branch `feature/windows-app-command-routing`, audit HEAD `6004fed`.

## 0. Decision record and vocabulary

- **P0** = prerequisite for continued development or release due to safety/correctness.
- **R1** = first working voice loop and Windows development alpha.
- **R2** = paired Windows + Android private alpha.
- **R3** = independent Android voice sessions and cross-device beta.
- **R4** = distributable, hardened, measured full V1.
- **Future** = specified but explicitly not part of initial release.
- **MUST** = release-blocking when that release is in scope; **SHOULD** = strongly desired but waivable with documentation; **MAY** = optional.
- Requirements are normative design targets, not evidence of implementation.

## 1. Executive summary

REVA is a personal, voice-first AI assistant that can converse naturally, remember only with clear user controls, and perform bounded, authorized tasks on Windows and Android. It combines **native clients**, a **Python assistant runtime**, **speech-provider adapters**, an **explicit action policy layer**, **local memory**, and eventually **paired cross-device sessions**. It must remain useful with network loss, must never quietly imply an action succeeded, and must explain when an advanced model or a paired computer is unavailable.

**Commercial wedge:** technical students and productivity-oriented Windows + Android users who need controllable on-device automation and persistent, inspectable memory. This is a hypothesis, not proven product–market fit. General-purpose voice companionship alone has severe competitive pressure from ChatGPT Voice, Gemini Live, and device assistants.

**Key product decision:** Deliver the complete vision in staged releases, not one giant branch. Android must eventually converse without a Windows computer; early paired builds may transparently depend on the Windows Core. Do not confuse an APK that can launch with an independent full assistant.

## 2. Problem, user and jobs-to-be-done

**Problem P-01:** Voice assistants often answer questions but cannot reliably perform specific user-approved desktop operations.

**Problem P-02:** Personal context is fragmented between phone and computer; users cannot easily inspect, correct, or delete saved memory.

**Problem P-03:** Voice interactions degrade under noise, pauses, interruption, bad networks, or unresponsive model providers.

**Problem P-04:** Users lack clear differentiation between a planned tool operation and a successfully executed and verified operation.

**Primary user / potential payer:** Windows + Android student, developer, or knowledge worker using the same personal workflow across devices. Individual B2C payment is speculative; validate before building subscription infrastructure.

**Secondary user:** Privacy-conscious power user with a capable PC and a willingness to operate local models; high support cost and limited addressable audience are risks.

**Jobs:** dictate and revise thoughts; ask follow-up questions; find user-saved facts; open approved applications; create reminders; use phone as a remote voice entry point for approved PC tasks; continue a conversation across devices with clear privacy choices.

## 3. Scope and commercial constraints

**Full V1 outcome:** A signed/installable Windows app and installable Android app capable of speech in/out, recoverable conversations, inspectable memory, explicit safe actions, optional pairing, device-respecting permissions, and documented offline/cloud behavior.

**Non-goals for V1:** unrestricted OS shell; arbitrary background device surveillance; continuous Android hotword in all device states; automated email sending without confirmation; autonomous purchases or financial transfers; cross-platform screen recording by default; iOS; a full general-purpose browser agent; a self-hosted cloud microservice fleet; 100% offline LLM inference on every Android handset.

**Lakewood AI reuse boundary:** reuse architecture concepts (VAD, endpoints, interruptions, deterministic intent/tool contracts, simulations/evaluations, event traces). Do not import menu, tax, order placement, POS, telephony, or production secrets. Any copied code needs a compatibility/license/dependency review.

## 4. Product journeys and definition of success

**J-01 Windows conversation:** user presses Talk or starts a consented voice session → mic capture/VAD → STT → transcript correction opportunity → contextual answer → audible TTS → user interrupts → playback stops → next turn begins; transcript and error state remain visible.

**J-02 PC action:** user says “open calculator” → deterministic/capability-aware router identifies allowlisted action → policy evaluates → desktop executes → result verified → REVA says it opened (or reports failure). A destructive/sensitive action requires deliberate approval from the target device.

**J-03 Memory:** user says or types “remember my preferred coding language is Python” → REVA previews the data to store → saves after explicit action or unambiguous explicit request → can retrieve, edit, export, and delete it; tombstones prevent deleted content from reappearing after sync.

**J-04 Android paired:** phone opens REVA → pairs to trusted Windows PC over encrypted channel → user speaks from phone → Core reasons on PC → phone plays output → an action targeted at PC requires PC-targeted policy and, when sensitive, PC confirmation.

**J-05 Android independent:** phone uses device-supported STT/TTS and configured standalone assistant provider or on-device model; if neither is available, REVA offers local commands and cached data and reports the limitation.

**J-06 Offline:** airplane mode → local notes/reminders and supported system intents still work, with an explicit “advanced reasoning unavailable” state; queued sync applies safely later.

**J-07 Revocation:** user unpairs phone → prior device credential fails on next connection, queued remote commands are rejected, local user data remains under the user's chosen retention policy.

### Success metrics (targets to validate, not measured facts)

| ID | Metric | Target / gate | Measurement |
|---|---|---|---|
| MET-01 | Windows voice turn success in quiet fixture | >= 95% on 100 scripted turns | deterministic test+hardware evidence |
| MET-02 | Speech starts after end of user turn | p50 <= 2.5 s, p95 <= 5 s with defined hardware/provider | timestamps: EOU to first audible PCM |
| MET-03 | Interrupt playback stop | p95 <= 300 ms after valid interrupt detection | loopback timestamps |
| MET-04 | Unsupported action false-success | 0/100 injected unsupported commands | tool policy eval |
| MET-05 | Sensitive action without approval | 0 executions | policy attack tests |
| MET-06 | Memory deletion resurrection | 0 in paired replay suite | sync fixtures |
| MET-07 | Crash-free session rate | >= 99% of 100+ dogfood sessions | opt-in local telemetry / manual ledger |
| MET-08 | Android cold start to ready | p50 <= 4 s excluding model download | midrange reference phone |
| MET-09 | Weekly retention among first testers | >= 40% week-2 of 10 users | consented cohort; directional only |
| MET-10 | Sustained user pull | >= 5/10 testers use voluntarily 3+ days/week | interviews + observed activity |
| MET-11 | Monthly support cost | tracked per device-minute and provider | bill of materials, no uncapped free use |

## 5. Functional requirements — voice and conversation

| ID | Release | Priority | Requirement | Acceptance / negative case |
|---|---|---|---|---|
| FR-001 | R1 | MUST | User can initiate and stop voice explicitly on Windows. | Visible mic indicator; mic closes after Stop/error. |
| FR-002 | R2 | MUST | User can initiate and stop voice explicitly on Android. | Permission denied gives instructions; no crash. |
| FR-003 | R1 | MUST | Voice input produces visible finalized and optional partial transcript. | Transcript includes source/quality status. |
| FR-004 | R1 | MUST | REVA responds with audible speech and visible text. | Speech failure preserves text answer. |
| FR-005 | R1 | MUST | Session controller supports Listening, Processing, Speaking, Interrupted, Error and Idle. | No simultaneous conflicting capture sessions. |
| FR-006 | R1 | MUST | User can interrupt TTS by voice or Stop button. | Playback buffer flushed; obsolete audio cannot resume. |
| FR-007 | R1 | MUST | VAD/endpointing handles pauses without premature send in fixture suite. | Turn-complete policy version recorded. |
| FR-008 | R1 | MUST | Every session has cancel and timeout controls for STT, LLM and TTS. | Cancellation produces no delayed spoken answer. |
| FR-009 | R1 | MUST | Audio devices can be selected and device-loss handled. | Unplug event returns to safe idle/error. |
| FR-010 | R1 | MUST | Microphone mute and speaker mute are separately available. | Muting speaker does not silently mute microphone. |
| FR-011 | R2 | MUST | Android foreground voice session has persistent, visible notification where required. | Background constraints respected. |
| FR-012 | R2 | MUST | Android voice path checks on-device STT capability before selecting it. | Fallback clearly indicates possible cloud processing. |
| FR-013 | R2 | MUST | Android TTS voice, rate and accessibility controls follow system availability. | Missing voice returns readable text. |
| FR-014 | R2 | MUST | Voice/typed turns share conversation history. | Same thread read on both surfaces where synced. |
| FR-015 | R3 | SHOULD | Session continuity after network disconnect is explicit. | No duplicate responses/actions after replay. |
| FR-016 | R3 | SHOULD | Duplex and noise suppression are selectable as capabilities, not mandatory. | Graceful fallback to half-duplex PTT. |
| FR-017 | R3 | SHOULD | Multilingual STT/TTS support includes explicit active language and fallback. | Language mismatch handled without fake confidence. |
| FR-018 | Future | MAY | Always-on wake word on Android only with reviewed platform-feasible mode. | No unsupported background microphone promise. |
| FR-019 | R1 | MUST | Wake-word feature on Windows remains default-off and integrity-checked. | Empty hash manifest cannot arm recorder. |
| FR-020 | R4 | MUST | Voice recording history defaults to off, configurable only by consent. | No raw audio retained on normal flow. |

## 6. Functional requirements — assistant, tools and policy

| ID | Release | Priority | Requirement | Acceptance / negative case |
|---|---|---|---|---|
| FR-021 | R1 | MUST | Model-independent assistant interface supports deterministic test provider and opted-in real provider. | Contract tests pass with fake and live adapter. |
| FR-022 | R1 | MUST | Dialog planner distinguishes answer vs tool proposal vs clarification. | Proposed operation never equals executed operation. |
| FR-023 | R1 | MUST | Typed/tool payloads are validated against versioned schemas. | Unknown fields/actions rejected at boundary. |
| FR-024 | R1 | MUST | Windows actions use explicit allowlist, fixed targets and device context. | User text cannot become executable path/flags. |
| FR-025 | R1 | MUST | Close, delete, send, or other high-risk operations require explicit confirmation. | Voice-only confirmation not sufficient for sensitive action unless separately hardened. |
| FR-026 | R1 | MUST | Every tool execution returns attempted/succeeded/failed/cancelled and evidence. | No success response without executor success evidence. |
| FR-027 | R1 | MUST | Policy engine denies by default on unknown capability/device or absent permission. | Fuzzed payloads produce deny. |
| FR-028 | R2 | MUST | Phone actions use Android platform APIs/intents, not arbitrary shell. | Unsupported app automation is refused. |
| FR-029 | R2 | MUST | Cross-device commands identify initiator, target and approval device. | PC-sensitive action cannot be approved only by compromised phone. |
| FR-030 | R3 | SHOULD | Multi-step task plans run with bounded steps, budget and abort button. | Loop/budget exhausted => safe stop. |
| FR-031 | R3 | SHOULD | Tools can be disabled individually in Settings. | Disabled tool cannot be invoked via model. |
| FR-032 | R3 | SHOULD | Email/calendar integrations use least-scope delegated auth. | No credential copy or silent send; refresh failures visible. |
| FR-033 | R4 | MUST | REVA can explain which action it executed, on which device, and when. | Event history matches user-visible claim. |
| FR-034 | Future | MAY | Third-party plugins run within scoped capability/approval boundary. | Untrusted plugin cannot request ambient OS privileges. |

## 7. Functional requirements — memory, personal data and sync

| ID | Release | Priority | Requirement | Acceptance / negative case |
|---|---|---|---|---|
| FR-035 | R1 | MUST | User can create and query explicit memories. | Existing behavior retained. |
| FR-036 | R1 | MUST | User can list, edit, archive, delete and export their saved memories. | Edit preserves version/history; delete creates tombstone. |
| FR-037 | R1 | MUST | Memory is not silently saved from every conversation. | Per-user opt-in; default explicit storage only. |
| FR-038 | R1 | MUST | Hybrid search combines lexical and semantic retrieval with safe fallback. | Missing Ollama/vector provider never blocks lexical. |
| FR-039 | R1 | MUST | Conversation history can be cleared independently of memories. | Clear history does not delete memories without choice. |
| FR-040 | R2 | MUST | Local Android data uses encrypted-at-rest protection for tokens/secrets. | Key stays in Android Keystore; no secret in backups/logs. |
| FR-041 | R2 | MUST | Paired sync has per-device identity, revocation and permission scopes. | Revoked device rejected; audit event retained. |
| FR-042 | R2 | MUST | Pairing requires proximity/verification with an explicit one-time handshake. | Replay and wrong-peer tests fail closed. |
| FR-043 | R3 | MUST | Data sync is resumable, idempotent and conflict-aware. | Replaying batch does not duplicate item/tool event. |
| FR-044 | R3 | MUST | Deletes take precedence over older updates. | Offline older device cannot resurrect tombstone. |
| FR-045 | R3 | MUST | User can choose which data classes sync. | Audio history never syncs by accident. |
| FR-046 | R3 | SHOULD | Conversations and preferences are usable with both devices online or offline. | Sync status and last-good state displayed. |
| FR-047 | R4 | MUST | Complete export and deletion paths exist for supported local/synced data. | Verification checks indexes/embeddings and queue. |
| FR-048 | Future | MAY | Optional encrypted relay supports off-LAN connections. | Server cannot silently impersonate peer. |
| FR-049 | Future | MAY | Life-memory entities Person/Event/Commitment can be opt-in. | Consent, edit and deletion tested. |

## 8. Functional requirements — client UX, accessibility and delivery

| ID | Release | Priority | Requirement | Acceptance / negative case |
|---|---|---|---|---|
| FR-050 | R1 | MUST | Desktop has accessible voice controls, transcript and typed fallback. | Keyboard navigation / screen reader smoke. |
| FR-051 | R2 | MUST | APK has home, voice, text, memory, device, settings and permissions screens. | Navigation smoke on emulator + physical phone. |
| FR-052 | R2 | MUST | User can inspect provider/connection availability. | Offline or missing model is not silently hidden. |
| FR-053 | R2 | MUST | Pair/Unpair/Approve remote access can be completed in-app. | Unpair invalidates all active sessions. |
| FR-054 | R3 | MUST | Settings disclose local/cloud processing for each active provider. | No false “fully offline” label if data leaves device. |
| FR-055 | R3 | SHOULD | Conversation search and pinned sessions. | Deleted sessions excluded. |
| FR-056 | R3 | SHOULD | Local reminders and notifications support opt-in scheduling. | Reboot/permission behavior tested. |
| FR-057 | R4 | MUST | Windows installer includes runtime and supports uninstall/upgrade. | Clean-machine installation, no repo/.venv required. |
| FR-058 | R4 | MUST | Android signed APK installs; Play distribution uses AAB. | Signature/upgrades validated. |
| FR-059 | R4 | MUST | Crash recovery shows unsent action status without duplicate execution. | Restart/replay integration suite. |
| FR-060 | R4 | MUST | User can wipe local state and revoke pairing. | Post-wipe secrets/data not accessible via normal app. |

## 9. Detailed nonfunctional product requirements

| ID | Release | Requirement and measurable bar |
|---|---|---|
| NFR-001 | R1 | All network endpoints bind loopback by default; no LAN listener unless pairing explicitly enabled. |
| NFR-002 | R2 | Cross-device traffic uses TLS with authenticated device identity; reject unsigned/expired/revoked sessions. |
| NFR-003 | R1 | Audio and model work must not block the WinUI UI thread; backpressure and bounded queues required. |
| NFR-004 | R2 | Phone capture/recognition must not block Compose main thread; service lifecycle cleaned up. |
| NFR-005 | R1 | Secrets never stored in plaintext config files or logged; migrate local Core token to OS secret storage before R4. |
| NFR-006 | R2 | Local mobile security uses OWASP MASVS controls for storage, authentication, crypto, network, platform, privacy. |
| NFR-007 | R1 | Cancelled sessions do not execute pending tools or play stale TTS. |
| NFR-008 | R1 | Test runs never point to a user's real REVA_DATA_DIR; fixtures are isolated. |
| NFR-009 | R3 | Errors are typed and actionable; preserve correlation IDs across clients and Core without recording microphone bytes. |
| NFR-010 | R4 | p50, p95, memory, CPU, battery and thermal behavior profiled on documented devices. |
| NFR-011 | R4 | Dependencies pinned, SBOM published, release artifacts signed and checksummed. |
| NFR-012 | R4 | No permanent permission requirement for phone microphone; revoke during session handled. |
| NFR-013 | R1 | Model and tool prompts treated as untrusted; retrieved memory/webpage text never grants permissions. |
| NFR-014 | R2 | Access checks enforce user × device × capability × session × action risk on server and target. |
| NFR-015 | R3 | Local-first feature behavior documented by connectivity state (offline, LAN, internet). |
| NFR-016 | R4 | A user can turn off telemetry and erase user event traces; security-only local logs have documented retention. |

## 10. Provider and connectivity matrix

| Mode | Windows | Android | Speech input | Reasoning | Speech output | User disclosure |
|---|---|---|---|---|---|---|
| W-LOCAL | Windows Core | — | faster-whisper/local | local Ollama/ADK or deterministic | Chatterbox/local | no network for STT/LLM if models installed |
| W-REMOTE-OPTIN | Windows Core | — | local or consented provider | configured remote model | local or remote | show provider/data path |
| A-LOCAL-LITE | — | standalone | Android on-device STT if supported | deterministic local actions/cached context | Android TTS | limited assistance only |
| A-PAIRED | paired Windows | Android APK | Android STT or encrypted stream to PC | Windows Core | Android TTS or streamed voice | PC must be reachable |
| A-STANDALONE | — | Android APK | device/on-device or consented provider | opt-in hosted LLM or capable on-device model | Android / provider TTS | explicit cost/network model |
| A-OFFLINE | — | Android APK | optional on-device STT | local notes/commands | device TTS | advanced reasoning unavailable unless local model |

## 11. Policy, privacy and trust

1. Microphone activation is visible, interruptible, and permission-bound; no stealth capture.
2. Listening does not mean recording retention; raw audio memory is ephemeral unless explicit opt-in.
3. Wake word on Windows: disabled by default and every `.ppn` must be bound to a known SHA-256 before opening microphone.
4. Android unrestricted background hotword is **not guaranteed**; pursue only after feasibility and OS policy review.
5. Action execution must be a separate deterministic command boundary; LLM output is untrusted intent.
6. Sensitive actions require context-specific user approval; remote sensitive PC actions require approval on PC.
7. Pairing must not expose the Python Core bearer token to another device.
8. Each memory has source, scope, timestamps, version and deletion state; retrieval cannot quietly surface deleted rows.
9. A user's own data must not be transmitted to hosted models unless that provider is enabled and disclosed.
10. Local tests and demos use synthetic user data, not real private recordings.

## 12. UX screen-level requirements

**Windows:** existing WinUI MainWindow retained and incrementally expanded: Conversation (typed + speech), History, Memory, Devices, Settings, Activity/Audit. Voice state indicator; Stop Speaking; mic device selection; explicit tool approval dialog. No background always-on mic by default.

**Android:** onboarding/permissions, conversations, talk screen, memory, devices/pairing, Settings (privacy/providers/storage), action approvals, connection status. Device screens adapt for TalkBack, landscape, dark mode and permission denial. The Android app never calls a Windows executable directly.

**Expected voice UX:** Talk starts a session; user speech generates partial and final transcript; REVA speaks text chunks; barge-in cancels prior audio; Stop cancels model and TTS; failure shows whether STT, model, tool or playback failed. Never leave a spinning state indefinitely.

## 13. Functional acceptance scenarios (Given / When / Then)

- **AC-001:** Given missing wake-word hash, when user enables Porcupine and provides `.ppn`, then engine refuses to arm before recorder starts.
- **AC-002:** Given full permission, when Windows user asks a question via mic, then transcript and audible answer complete with correlation ID.
- **AC-003:** Given active spoken answer, when user interrupts, then all pending prior audio is cancelled and subsequent answer belongs to new turn.
- **AC-004:** Given two identical tool events, when network retries, then executor performs exactly one authorized action or returns an idempotency conflict.
- **AC-005:** Given Android mic denied, when user taps Talk, then REVA explains and typed input continues to work.
- **AC-006:** Given no Windows PC and no hosted model selected, when Android user asks a general complex question, then REVA clearly labels reasoning unavailable; no fabricated answer.
- **AC-007:** Given a revoked phone, when it reconnects, then the action channel fails before any command executes.
- **AC-008:** Given a deleted memory on Windows while phone offline, when phone reconnects with an older edit, then the memory remains deleted.
- **AC-009:** Given unapproved PC close command initiated on phone, when target asks confirmation, then execution does not occur until explicit PC approval.
- **AC-010:** Given Windows app closes, then owned Core exits and external Core is not terminated; PID evidence collected.
- **AC-011:** Given speech provider timeout, then UI changes from Processing to recoverable Error/Idle within policy timeout and stale TTS never plays.
- **AC-012:** Given clean Windows PC and signed distribution, then install/launch/uninstall works without a repository checkout or Python virtual environment.
- **AC-013:** Given signed Android APK, when installed on target Android devices, then permission refusal and revocation do not crash.
- **AC-014:** Given unset cloud permission, when assistant is asked a task requiring hosted model, then audio/text does not leave device.

## 14. Phased acceptance gates

**P0 (existing-branch safety gate):** committed wake-word fail-closed resolver and negative test; real Windows shutdown PID proof; preserve all unrelated dirty work; all existing Python and .NET checks remain green.

**R1 Windows voice alpha:** end-to-end mic → STT → LLM/ADK → TTS → speaker; user interruption; deterministic tool actions; memory CRUD; live Ollama verified when enabled; at least one physical mic/speaker smoke; streaming answer may use chunked TTS if Chatterbox cannot stream frames.

**R2 paired Android private alpha:** Android signed debug APK; capture/recognition + spoken output; authenticated pairing with Windows; one safe PC action (open Calculator) initiated on Android with device authorization; negative permission and network-recovery tests.

**R3 independent Android beta:** Android can answer without a running Windows PC using a selected provider path; offline limitations explicit; sync idempotency/tombstones and revocation proven; users can disable cloud providers.

**R4 full V1 release:** signed Windows installer, Android release APK + AAB as applicable, security checklist, performance and battery benchmarks, accessibility smoke, clean-machine tests, end-user documentation, measured retention.

## 15. Validation before monetization

**Competition reality:** broad assistant interfaces compete with ChatGPT Voice, Gemini Live and platform integrations. Differentiation must be measured in **reliable, user-approved device tasks** and **inspectable private memory**, not merely a voice waveform.

- Interview 10 Windows + Android users who regularly switch devices. Ask for actual weekly tasks, failure costs and privacy concerns; do not pitch first.
- Recruit 5 technical beta testers; require each to submit a task they previously failed to complete with an existing assistant.
- Test 3 top tasks across at least two sessions each; collect success/failure and return rate.
- Pricing hypotheses only: free local mode; potential $8–12/month paid plan for managed connectivity/inference. No pricing claim until cloud COGS and willingness-to-pay interviews are measured.
- **Commercial stop/pivot gate:** If fewer than 3/10 interviewed users show meaningful switching pain, or fewer than 5/10 testers return voluntarily across 2 weeks, narrow the wedge instead of adding features.

## 16. Ownership, scope change and document control

- **Founder / developer:** implementation, architecture, releases, deployment, performance decisions.
- **QA engineer:** acceptance criteria, fixture corpora, test automation, privacy/security regression matrix, release signoff evidence.
- Every change requires PRD ID, ARD mapping, test ID, rollout flag, rollback plan and signed-off product acceptance.
- Do not mark a requirement **DONE** merely because code compiles or a unit test passes; real-voice, Android, packaging and pairing require physical/runtime proof.
- Freeze scope per release; record deviations in decision log rather than silently reshaping milestones.

## 17. Audit-derived baseline (2026-10-11)

**Verified in shared audit:** Python `326 passed, 2 skipped`; `dotnet test` `334 passed`; ruff format/check and mypy clean. Python Core FastAPI/SQLite; WinUI typed UI, manual memories, fake provider default; opt-in ADK+Ollama and embeddings; faster-whisper STT, Chatterbox TTS (default off), Porcupine wake word default off; Windows app allowlist.

**Not verified:** live mic, GUI E2E, real Ollama, real Chatterbox, exit linger, installer, Android code. `WakeWordKeywordResolver` committed hash guard fails open for an empty manifest; working-tree test/fix passed but not committed. Branch has unrelated dirty shutdown edits. No September/October implementation commits according to the supplied audit. Treat these as **existing technical constraints**, not features delivered by this PRD.

## 18. External platform guidance (retrieved 2026-10-11)

- Android microphone foreground service permissions/restrictions: https://developer.android.com/develop/background-work/services/fgs/service-types
- Android while-in-use/background service restrictions: https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start
- Android on-device recognizer capability detection: https://developer.android.com/reference/android/speech/SpeechRecognizer
- Android App Bundles / APK distribution: https://developer.android.com/guide/app-bundle
- WinUI packaging/deployment: https://learn.microsoft.com/windows/apps/package-and-deploy/
- OWASP MASVS controls: https://mas.owasp.org/MASVS/
- LiveKit turn-taking concepts (design reference only): https://docs.livekit.io/agents/logic/turns/


## 19. AI/ML and action-agent requirements (extension v1.1)

**AI/ML is an explicit product subsystem.** The source of truth for perception, reasoning, grounding, native action and verification is `06_REVA_AI_ML_ACTION_AGENT_PRD_ARD.md`. That document adds **FR-AI-001 through FR-AI-028**, each with a gate and acceptance behavior. REVA is an action-oriented assistant, not merely speech-to-text and chatbot text.

End-user contract: a supported user command can be interpreted by the model, proposed as typed tool actions, checked against a device's independently verified permissions, executed in the native adapter and summarized **only from observed evidence**. The user may inspect/cancel/approve. Windows permits broader explicit foreground UI automation than a Play-distributed Android APK. See companion doc section 10 for rejected shortcuts, particularly unrestricted Android Accessibility automation.

**New PRD acceptance journeys:** J-AI-01 Spotify playback with true verification; J-AI-02 inspect this window and select grounded Submit; J-AI-03 authorized budget spreadsheet → email draft, not silent send; J-AI-04 phone → approved Windows app launch.

**Proposed AI-related release requirements are PLANNED:** no VLM/Android autonomous UI control or generic planner was observed in the supplied October 11 repository audit.
