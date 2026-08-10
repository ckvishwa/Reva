# REVA V1 — Product Requirements Document

**Status:** Scope lock draft  
**Product:** REVA — private personal intelligence software  
**Release:** V1  
**Primary platforms:** Windows desktop; Android companion APK  
**Architecture approach:** Python-first, local-first modular monolith

## 1. Product vision

REVA is a private, local-first personal intelligence that accompanies one person across their devices. It understands user-permitted context, retains useful user-approved knowledge, and helps turn intent into completed work within boundaries the user controls.

REVA should feel like a calm, capable, JARVIS/FRIDAY-style assistant: available through voice and interface, able to remember decisions and preferences, able to help resume work, and able to perform narrow approved actions. It is not a fictional omniscient system, an always-listening surveillance product, or an autonomous agent with unchecked access.

### V1 promise

> REVA remembers what matters, helps users continue their work, and follows them between PC and phone without taking control away from them.

## 2. Goals

V1 must prove a reliable personal-assistant loop:

1. The user speaks or types a request.
2. REVA understands it through a replaceable AI provider.
3. The user can explicitly save important facts, notes, preferences, and decisions.
4. REVA can retrieve saved information with its source.
5. REVA can create reminders and perform a small set of safe desktop actions.
6. Approved personal state is available on a paired Android companion.
7. The user can inspect, edit, export, and delete stored information.

## 3. Core principles

- **Local-first:** Local devices store REVA's durable state by default. A cloud model may process a request only through an explicit, replaceable provider configuration.
- **Private by design:** REVA collects and retains only data needed for an enabled feature. Raw microphone recordings are not stored by default.
- **Explicit-memory-first:** Durable memory requires clear user intent, such as “remember this,” saving a note, or approving a memory capture.
- **Voice-first, not voice-only:** Voice is a primary interaction mode; every essential action has a visible text/UI alternative.
- **Proactive but controlled:** V1 may deliver reminders and surface user-approved information, but it does not autonomously take consequential action.
- **Inspectable behavior:** Users can see what REVA stored, retrieved, proposed, executed, and synchronized.
- **Safe action boundaries:** REVA uses narrow allowlisted tools and never executes arbitrary shell commands.
- **Graceful degradation:** Local history, local memory browsing, reminders, and supported desktop actions remain available when internet or cloud models are unavailable.
- **Modular, not overbuilt:** Clients, providers, and integrations are replaceable edges; REVA Core, policy, memory semantics, storage, and audit remain the stable center.

## 4. Users and assumptions

### Primary user

A single Windows user who wants a private personal assistant for decisions, notes, reminders, work continuity, voice interaction, and safe local computer help.

### V1 assumptions

- The user has one primary Windows PC.
- The user may pair one Android phone.
- The user explicitly configures any cloud model provider used by REVA.
- REVA has no public internet endpoint.
- V1 is single-user and does not support shared accounts, family workspaces, or organizational administration.

## 5. V1 scope

| Area | V1 requirement |
|---|---|
| Windows desktop | System-tray application, compact assistant panel, typed chat, voice controls, memory manager, reminders, settings, and activity history |
| REVA Core | Local Python background runtime for orchestration, memory, provider routing, policy, tools, reminders, sync preparation, storage, and auditing |
| Voice | Push-to-talk, STT, reasoning, TTS, visible transcription, and cancel/interrupt controls |
| Typed interaction | Conversation history and typed requests on Windows and Android |
| Explicit memory | User-approved facts, decisions, preferences, notes, project context, and tasks |
| Memory recall | Keyword and semantic retrieval with source/date information |
| Reminders | One-time reminders created through text or voice, with Windows and Android notification delivery |
| Safe Windows actions | Open allowlisted apps, files, folders, and URLs; copy generated text; create reminders; prepare drafts without sending |
| Android APK | Pairing, chat, push-to-talk capture, memory search, quick capture, reminders, and sync status |
| Sync | Conversations, explicit memories, notes, reminders, selected settings, and safe audit metadata |
| Security | Device pairing, local authentication, encrypted transport, permissions, audit trail, export, and deletion controls |
| Models | Cloud LLM initially behind replaceable provider interfaces; local embeddings/retrieval where practical |
| Offline | Browse/search local memory, history, and reminders; execute supported local actions without cloud connectivity |

## 6. Non-goals

V1 explicitly does not include:

- Always-on microphone operation or wake-word activation.
- Passive screen recording, keystroke logging, unrestricted clipboard collection, or surveillance behavior.
- Unrestricted filesystem crawling or background collection of app, email, message, browser, or notification content.
- Arbitrary shell, PowerShell, terminal, or code execution.
- Browser click/type automation.
- Sending email/messages, purchases, payments, job applications, account changes, or file deletion.
- Gmail, calendar, finance, career, smart-home, IoT, or broad third-party integrations.
- Autonomous multi-step agents that act without a visible plan and appropriate approval.
- Required local LLM inference.
- iOS, macOS, Linux, browser, multi-user, or family support.
- A plugin marketplace, generic integration platform, or microservice architecture.

## 7. User experience

### Windows desktop

The Windows node is REVA's primary productivity surface. It provides:

- A system-tray icon with REVA health/status and quick actions.
- A compact assistant panel for typed conversation and streaming responses.
- A configurable push-to-talk control and hotkey.
- Voice transcription, response text, speech playback, mute, and cancel controls.
- Memory Manager for searching, viewing, editing, deleting, and exporting memories.
- Reminders view for upcoming, completed, and dismissed reminders.
- Activity History showing memory events, retrievals, proposed actions, approvals, action results, sync outcomes, and errors.
- Settings for providers, voice, privacy, permissions, paired devices, storage, and diagnostics.

### Android companion

The Android app is a companion, not a duplicate desktop environment. It focuses on:

- Typed chat and memory recall.
- Push-to-talk requests and voice-note capture.
- Quick capture of notes, ideas, tasks, and explicit memories.
- Reminder notifications.
- Pairing, device status, and privacy controls.
- Read-only relevant activity/sync summaries.

### Signature V1 moments

- “REVA, remember that V1 uses push-to-talk, not always-on listening.”
- “What did I decide about voice?”
- “Remind me tomorrow at 9 AM to write the Vision section.”
- “Open the REVA PRD project.”
- On phone: “Save this thought to the REVA project.”

## 8. Functional requirements

### 8.1 REVA Core

REVA Core is an always-available local Python runtime on Windows. It owns:

- Request orchestration and conversation/session state.
- Memory semantics and retrieval coordination.
- Provider routing for LLM, embedding, STT, and TTS interfaces.
- Tool registry and policy enforcement.
- Reminder scheduling and notification dispatch coordination.
- Local storage, audit events, and future sync semantics.
- Offline queues and graceful degradation.

Desktop and Android clients do not own policy, durable-memory semantics, audit policy, or provider business logic.

### 8.2 Voice

V1 voice pipeline:

```text
Push-to-talk → audio capture → speech-to-text → request/retrieval → reasoning
→ optional safe action plan → text response → text-to-speech → audit event
```

Requirements:

- Windows uses visible push-to-talk and configurable hotkey.
- Android uses held-button or tap-to-record interaction.
- Transcription is displayed to the user.
- The user can stop TTS immediately.
- Voice and text use the same core request semantics.
- On STT failure, REVA offers typed fallback and discards raw audio unless the user explicitly saves/retries it.

### 8.3 Memory

| Class | Purpose | Retention |
|---|---|---|
| Working memory | Current conversation/session context | Session or short expiry |
| Explicit personal memory | User-approved facts and preferences | Until user deletion |
| Notes/project memory | Decisions, notes, ideas, and project context | Until user deletion |
| Task/reminder memory | Reminder details and state | Until completion/deletion; history configurable |

Every durable memory records: stable ID, content, category, creation/update time, origin device, source reference, optional project/tags, retention state, version/sync state, and retrieval metadata reference.

V1 supports explicit capture, editing, deletion, export, keyword search, semantic retrieval, source-aware answers, and deletion propagation to paired devices. REVA must not silently create permanent sensitive inferences.

### 8.4 Context

Allowed V1 context:

- Current REVA session and conversation.
- Explicitly selected project, notes, and memories.
- Local time/date and reminder state.
- Active Windows application name and window title only when the user enables it.
- Files/folders REVA itself opened on user request.
- Device status and pairing/sync state.

Not allowed in V1:

- Screen capture or visual understanding.
- General document crawling.
- Passive recording of other apps.
- Keyboard logging.
- Automatic clipboard capture.
- Passive microphone recording.
- Reading email, calendar, browser content, or messages.

### 8.5 Tools and actions

| Tool | Example | V1 policy |
|---|---|---|
| Open application | “Open VS Code” | Confirm first use; repeat policy optional |
| Open file/folder | “Open the REVA project folder” | Confirm for new target/first use |
| Open URL | “Open the PRD document” | Confirm based on policy |
| Web search | “Search voice assistant UX patterns” | User-controlled permission |
| Copy text | “Copy this to clipboard” | Confirmation required |
| Create reminder | “Remind me tomorrow at 9” | Confirmation required |
| Save note/memory | “Remember this decision” | Visible save confirmation |
| Draft content | “Draft a summary” | Allowed; never sends externally |

All tools are allowlisted. Every tool request passes policy evaluation, produces a clear result, and creates an audit event. REVA cannot run arbitrary commands or perform destructive/consequential operations in V1.

### 8.6 Reminders

V1 supports one-time reminders with title/content, due time, source, status, and completion/dismissal history. Reminders are created by text or voice and appear as Windows and Android notifications after synchronization is available.

### 8.7 Sync

Windows is the V1 primary node and maintains the primary operational state while available. Android stores an encrypted local cache and synchronizes approved data.

Synchronized data:

- Conversations and message metadata.
- Explicit memories, notes, projects, and tags.
- Reminders and reminder state.
- Shared user settings.
- Device registrations and sync cursors.
- Safe audit summaries.

Not synchronized by default:

- Raw microphone audio.
- Full diagnostic logs.
- Local model files.
- Arbitrary Windows files or filesystem indexes.
- Executable Windows paths as actionable commands.

Sync requirements:

- Authenticated HTTPS for pairing, registration, reconciliation, and backfill.
- Authenticated WebSocket transport for future near-real-time updates.
- Stable event IDs, device IDs, entity versions, timestamps, and operation type.
- Local offline queues and safe reconciliation after reconnection.
- Conflicting offline memory edits are preserved and surfaced; they are not silently overwritten.
- Users can unpair a device and terminate future synchronization.

## 9. Permissions and security

### Permission model

| Capability | Default | Purpose |
|---|---|---|
| Microphone | Off until invoked | Voice request capture |
| Notifications | Requested during setup | Reminder delivery |
| Active app/window context | Off | Optional contextual assistance |
| Open apps/files/URLs | Ask on first use | Safe local actions |
| Clipboard write | Ask each time | Copy prepared text |
| Cloud model processing | Explicit opt-in | Process text through selected provider |
| Android pairing/sync | Explicit two-device approval | Cross-device continuity |

### Security requirements

- REVA Core is not publicly exposed in V1; network listeners bind to loopback only unless a future architecture decision changes this.
- Core uses authenticated localhost API/IPC boundaries.
- Device pairing requires explicit confirmation and per-device credentials.
- Secrets are encrypted/protected and never stored in plaintext configuration or ordinary logs.
- API keys, access tokens, pairing tokens, passwords, authorization headers, and raw microphone data are redacted from normal logging.
- Users can export and delete personal data and unpair Android devices.
- Tool policy cannot be bypassed by orchestration, clients, providers, or integrations.
- Destructive actions and external consequential actions are unsupported in V1.

## 10. Architecture

```text
Windows Desktop UI (PySide6)
  tray · chat · voice UI · memory manager · settings · audit
                    │
       authenticated localhost API / IPC
                    │
REVA Core (Python)
  API · orchestration · policy · memory · retrieval · providers
  tools · reminders · storage · audit · future sync coordinator
                    │
SQLite + WAL · local vector index · protected secrets
                    │
PLANNED: authenticated HTTPS/WebSocket
                    │
Android Companion (Flutter)
  chat · voice capture · quick capture · notifications · local cache
```

### Architecture boundaries

- **API:** Transport validation, serialization, and authentication boundary; no domain logic or SQL.
- **Orchestration:** Coordinates use cases; never calls vendor SDKs or bypasses policy.
- **Memory:** Owns memory semantics, retention, and retrieval coordination; no SQLite-specific logic.
- **Storage:** Owns SQLite connections, transactions, migrations, and repositories; does not decide what should be remembered.
- **Models/providers:** Own replaceable provider contracts and adapters; do not mutate durable state.
- **Tools:** Own narrow allowlisted action implementations; do not decide whether execution is allowed.
- **Policy:** Owns permissions, risk, and approval decisions; always sits between orchestration and tools.
- **Audit:** Owns safe structured audit records; never stores secrets or raw audio.

## 11. Data architecture

SQLite is the authoritative durable store. Semantic/vector indexes are derived, rebuildable data; original memory text and source metadata remain authoritative in SQLite.

Expected tables:

- `application_metadata`
- `devices`
- `conversations`
- `messages`
- `memories`
- `reminders`
- `permissions`
- `audit_events`
- `sync_events` and/or `sync_queue`

Requirements:

- SQLite WAL mode and foreign keys enabled.
- Explicit, versioned migrations from day one.
- Timezone-aware timestamps stored in UTC.
- Stable UUIDv7 entity IDs; database internal row IDs, if any, are not cross-device identity.
- Explicit repository boundaries instead of a massive ORM.
- Indexed stable IDs, entity timestamps, foreign-key relationships, reminder due times, and retrieval lookup fields.
- Retention, deletion, export, and sync effects considered for every new persisted field.

## 12. Offline and failure behavior

| Condition | Required behavior |
|---|---|
| Internet unavailable | Local UI, history, memory browse/search, reminders, and supported local actions remain available |
| Cloud LLM unavailable | REVA states that model reasoning is unavailable; local memory/search remains available |
| Android offline | Local changes queue and synchronize after reconnection |
| Windows unavailable | Android stores capture locally until it can sync with Core |
| STT failure | Typed fallback; no default raw-audio retention |
| TTS failure | Text response remains available |
| Tool failure | Clear failure message and audit event; never claim completion |
| Sync conflict | Preserve versions and request user resolution for memory conflicts |
| Core crash/restart | Restore local state and unsynced queue; report recovery status |

## 13. Performance requirements

| Metric | Target |
|---|---|
| Windows cold start to usable tray state | Under 5 seconds on supported hardware |
| Assistant panel open | Under 500 ms after Core is active |
| Push-to-talk start | Under 300 ms after input |
| STT response start | Under 1.5 seconds after speech ends, provider/network dependent |
| First model response | Under 2.5 seconds for typical cloud request, network dependent |
| TTS start | Under 1 second after answer ready |
| Keyword memory search | Under 250 ms for 10,000 records locally |
| Semantic retrieval | Under 750 ms for 10,000 records locally |
| Online cross-device propagation | Under 5 seconds while both nodes are active |
| Core/tray idle memory | Target under 500 MB excluding optional local models |
| Core idle CPU | Target under 2% average after startup |

## 14. Acceptance tests

REVA V1 works when all tests below pass.

1. A Windows user can send a typed request and receive a streamed text response.
2. A user can submit a push-to-talk request, see transcription, receive text and speech, and interrupt speech.
3. A user can explicitly save a memory and retrieve it accurately with source information.
4. A user can edit, delete, and export memories.
5. A user can create a reminder through text or voice.
6. A Windows-created reminder appears and notifies on paired Android.
7. A user can ask REVA to open an approved app, known file, folder, or URL with required confirmation.
8. Every executed, denied, and failed tool action appears in activity history.
9. A memory created on either paired device synchronizes to the other while online.
10. Offline changes reconcile correctly on reconnection.
11. A memory conflict is preserved and surfaced rather than silently overwritten.
12. No consequential external operation occurs without explicit approval; consequential operations are unsupported in V1.
13. Raw microphone audio is not stored by default.
14. Active-window context is disabled by default and can be toggled visibly.
15. With no internet, a user can browse/search local memory and history and create a local reminder.
16. When a cloud provider fails, REVA reports the limitation and does not claim unavailable work was completed.
17. Restarting Core preserves confirmed local data and unsynced queued events.
18. A user can unpair Android and future sync stops.

## 15. Delivery roadmap

### Phase 0 — Foundation / architecture lock

- Contracts, Core skeleton, SQLite bootstrap/migrations, provider interfaces, policy boundaries, structured logging, tests, CI, threat model, ADRs, and documentation.
- No product features.

### Phase 1 — Personal memory vertical slice

- Typed chat.
- Explicit “remember this.”
- SQLite persistence.
- Keyword/semantic retrieval.
- Source reference.
- Restart recovery.
- Audit events.

### Phase 2 — Voice loop

- Windows push-to-talk.
- STT and TTS providers.
- Cancellation and transcription.
- Voice privacy controls.

### Phase 3 — Safe desktop help

- Allowlisted app/file/folder/URL actions.
- Reminders.
- Approval UI and audit history.

### Phase 4 — Android companion

- Pairing, quick capture, chat, memory recall, reminders, and encrypted local cache.

### Phase 5 — Reliable synchronization

- Device identity, authenticated transport, WebSocket updates, offline queue, reconciliation, conflict handling, and unpairing.

### Phase 6 — First external integrations

Potentially calendar read, email read, and draft creation. Sending remains disabled unless separately approved.

### Phase 7 — Context and proactive assistance

- Opt-in Windows context.
- Work-resume briefs.
- Meeting preparation.
- User-configurable suggestions.

### Phase 8 — Controlled plans

- Visible multi-step plans.
- Step-level approval.
- Narrow repeatable routines.

### V2 and later

Potential local models, browser assistance, smart home/IoT, additional platforms, and advanced automation. Every new capability requires product scope, permissions, threat modeling, audit behavior, acceptance tests, and rollback/disable strategy.

## 16. Future expansion rules

- Do not create a plugin marketplace, generic integration runtime, generic workflow engine, universal connector, or autonomous-agent framework before concrete requirements justify it.
- New clients must use Core contracts/API and must not duplicate Core business logic.
- Providers must use provider interfaces and cannot directly mutate durable user state.
- Integrations must be explicit, allowlisted, audited, permissioned, and unable to silently create permanent memory.
- Every new action is classified as `READ_ONLY`, `PREPARE_OR_DRAFT`, `LOCAL_REVERSIBLE`, `EXTERNAL_REVERSIBLE`, `EXTERNAL_CONSEQUENTIAL`, or `DESTRUCTIVE`.
- Consequential/destructive capabilities require a PRD update, threat-model update, permission design, acceptance tests, and rollback/disable strategy before implementation.
- Persistent-data changes require migrations, repository tests, retention/deletion behavior, export implications, and sync implications.
- Cloud features remain optional where feasible; local-first data must not become mandatory cloud-hosted data without an explicit architecture decision.

## 17. Definition of V1 success

REVA V1 succeeds if a user can reliably say or type a request, deliberately save something important, retrieve it later with source context, receive a reminder, safely ask REVA to perform limited desktop help, and continue that personal context between their Windows PC and Android phone.

The goal is not to claim full autonomy. The goal is to establish a private, trustworthy, context-preserving assistant foundation that users can inspect and control.
