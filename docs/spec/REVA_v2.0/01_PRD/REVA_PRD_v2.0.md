# REVA — Master Product Requirements Document v2.0

**Document ID:** REVA-PRD-002
**Version:** 2.0.2 (supersedes REVA-PRD-001 v1.0/v1.1, archived in `09_ARCHIVE_v1/`)
**Date:** 2026-10-11
**Product:** REVA 2.0 — voice-first personal AI system with a visible avatar, life domains, and verified device actions
**Clients:** Windows desktop (WinUI 3) + Android (Kotlin/Compose); both fully usable on their own
**Status:** Proposed requirements. Nothing here is a claim that a feature is built. Status is PLANNED until promoted to VERIFIED with evidence (see ARD-800).
**Reference implementation:** `D:\Projects\Reva` (WinUI 3 + Python Core). FRIDAY OS / AuraO work is harvested into it (ARD-800 §2).

---

## 0. What changed from v1

| # | Change | Why |
|---|---|---|
| 1 | FRIDAY OS scope merged in: Memory, Finance, Health, Coach, Career, Learn, Cyber, Personal become first-class **life domains** | v1 had no domain requirements (only FR-049, Future) |
| 2 | Every domain works fully **on Windows and on Android, each on its own**, through a shared Rust **Domain Kernel** | v1 R3 requires a phone-independent path (AR-068, J-05); domains must follow it |
| 3 | A Blender-made **avatar** (VRM, rendered in a WebView) is the visible face on both apps | New product direction |
| 4 | **Kokoro** (`af_heart`) is the first TTS provider; Chatterbox second | Kokoro is the only TTS proven live in prior work |
| 5 | Product framing: **single-user personal system first**; v1 monetization gates parked, not deleted | Owner decision |
| 6 | Off-LAN sync (v1 FR-048, Future) pulled to **R3 as opt-in client-encrypted relay** | Cross-device domains need it; gated by adversarial tests |
| 7 | Deferred to Future: VLM screen grounding, 3+ step UI workflows, email/calendar integrations, gRPC transport | Keeps R1–R4 on the core product |

Requirement IDs from v1 keep their numbers. New IDs use the prefixes `FR-AV`, `FR-DOM`, `FR-MEM`, `FR-FIN`, `FR-HLT`, `FR-COA`, `FR-CAR`, `FR-LRN`, `FR-CYB`, `FR-PER`, `FR-TDY`, `FR-SYN`, `NFR-0xx`, `AC-0xx`, `J-xx`.

## 0.1 Vocabulary

- **P0** safety prerequisite · **R1** Windows alpha · **R2** paired Android alpha · **R3** standalone Android + domains + sync beta · **R4** signed, measured 2.0.0 release · **Future** specified, not in 2.0.
- **MUST** release-blocking for its release · **SHOULD** waivable with a documented reason · **MAY** optional.
- **Domain**: one area of the user's life with its own data, rules, tools and privacy switches.
- **Domain Kernel**: the shared Rust library that stores and computes all domain data on every device (see `06_CONCEPTS`).

---

## 1. Executive summary

REVA is a personal AI that you talk to and that talks back through an animated avatar. It remembers only what you approve, tracks your money, health, goals, career, learning, security work and personal life, and performs bounded, approved actions on your PC and phone. Each device carries the full system and works alone, offline if needed. Devices sync with each other directly over the home network or through an optional relay that only ever sees encrypted data.

Non-negotiables carried from v1: REVA never says something happened unless a native executor proved it; a model can propose but never authorize; microphone use is always visible; nothing is remembered silently; nothing personal leaves a device to a hosted model without that provider being enabled and disclosed, and for sensitive domains, separately consented.

## 2. Problem, user and jobs

**P-01 to P-04** carried from v1 (assistants that cannot act reliably; fragmented phone/PC context; fragile voice; unclear planned vs verified actions).

**P-05 (new):** Personal life data is spread across many apps and clouds (banking, fitness, notes, job tracker, study apps). The user cannot see it in one place, ask questions across it, or keep it private and local.

**P-06 (new):** A voice assistant with no presence feels like a text box. A visible character that listens, thinks and speaks makes state obvious and the product enjoyable to use daily.

**Primary user:** the owner, a single technical user on Windows + Android. External users are out of scope until a ship decision (PRD §15).

**Jobs:** talk naturally and interrupt; ask questions with memory; log an expense, a workout or a study session by voice in seconds; see today across all domains; ask "how much did I spend on food this month" or "how did I sleep this week"; open and control approved apps; use the phone as a full REVA away from the PC; keep everything private and exportable.

## 3. Scope and non-goals

**2.0.0 outcome:** a signed Windows installer and a signed Android app, each with speech in/out, avatar, conversations, approved memory, eight life domains working offline, safe device actions, pairing, LAN sync, optional encrypted relay, documented cloud/offline behavior.

**Non-goals for 2.0 (v1 list kept):** unrestricted OS shell; background device surveillance; continuous Android hotword in all states; sending email without confirmation; **autonomous purchases or financial transfers**; default screen recording; iOS; general browser agent; cloud microservice fleet; offline LLM on every handset.

**New non-goals:** moving money of any kind; connecting bank credentials in 2.0 (aggregation is Future); medical diagnosis, dosing or treatment advice; writing data back into Health Connect; multi-user accounts; selling or sharing data.

## 4. Journeys

v1 journeys **J-01 to J-07 are kept** (Windows conversation, PC action, memory, Android paired, Android independent, offline, revocation).

| ID | Journey |
|---|---|
| J-08 | **Avatar conversation:** user presses push-to-talk; avatar turns to a listening pose only when the mic is truly open; thinking pose while the model works; lips move with the audio actually playing; user interrupts and mouth and audio stop together. |
| J-09 | **Voice logging offline on phone:** in airplane mode, user says "I spent 12 dollars on lunch"; REVA shows the parsed expense, user confirms, it is stored in the phone's Finance domain and queued for sync. |
| J-10 | **Cross-device convergence:** the phone reconnects to the home network; the expense appears on the PC; an expense deleted on the PC while the phone was away stays deleted. |
| J-11 | **Health summary:** user asks "how did I sleep this week"; REVA answers from Health domain data (Health Connect import on Android, manual entries anywhere), with no diagnosis and no hosted model unless Health is consented. |
| J-12 | **Today:** user opens Today and sees budget left, workouts, habits due, reminders, study streak and journal prompt in one screen on either device. |
| J-13 | **Domain privacy:** user turns off sync for Personal journal and hosted-model access for Finance; network capture confirms neither leaves the device. |
| J-14 | **Export and leave:** user exports Finance as CSV and deletes the Health domain; deleted data is unreachable in UI, search, embeddings and sync. |

### Success metrics (targets to validate, not facts)

v1 **MET-01 to MET-08 and MET-11 kept**. MET-09/MET-10 (cohort retention) parked with monetization.

| ID | Metric | Target |
|---|---|---|
| MET-12 | Avatar lip-sync offset vs played audio | ≤ 100 ms p95 |
| MET-13 | Interrupt → mouth closed and audio stopped | ≤ 300 ms p95 (same as MET-03) |
| MET-14 | Voice-logged domain entry, speech end → confirmation shown | ≤ 3 s p50 on PC, ≤ 4 s on phone |
| MET-15 | Domains usable offline | 8/8 domains read+write on both devices with network off |
| MET-16 | Sync correctness | 0 lost, 0 duplicated, 0 resurrected records in replay suite |
| MET-17 | Owner daily use | REVA used on ≥ 5 days/week for 4 consecutive weeks (personal-use bar) |

## 5. Requirements carried from v1

All v1 requirements remain in force unless listed in §6. The full list with v2 owner ARD and status is in `07_TRACEABILITY/REVA_Traceability_v2.0.md`. Summary:

| Group | IDs | v2 treatment |
|---|---|---|
| Voice and conversation | FR-001 – FR-020 | Kept; FR-004/FR-013 amended (§6) |
| Assistant, tools, policy | FR-021 – FR-034 | Kept; FR-032 → Future |
| Memory, data, sync | FR-035 – FR-049 | Kept; FR-048 → R3 opt-in; FR-049 superseded by FR-DOM/FR-PER |
| Client UX and delivery | FR-050 – FR-060 | Kept; FR-051 amended |
| AI/ML action agent | FR-AI-001 – FR-AI-028 | Kept; FR-AI-019, -020, -022, -026 → Future; FR-AI-009 amended |
| Nonfunctional | NFR-001 – NFR-016 | Kept; NFR-017+ added (§9) |
| Acceptance | AC-001 – AC-014 | Kept; AC-015+ added (§13) |

## 6. Amended v1 requirements

| ID | Release | v2 text |
|---|---|---|
| FR-004 | R1 | REVA responds with audible speech (Kokoro first, Chatterbox second, Android TTS on phone) and visible text; the avatar speaks in sync. Speech failure preserves the text answer and the avatar returns to idle. |
| FR-013 | R2 | Android TTS voice, rate and accessibility controls follow system availability; when paired, Kokoro audio may stream from the PC. |
| FR-048 | R3 (opt-in) | Optional relay supports off-LAN sync. Events are encrypted on the device; the relay (Supabase) stores ciphertext and routing metadata only. No "end-to-end encrypted" label until adversarial tests pass. |
| FR-049 | — | Superseded by FR-DOM-* and FR-PER-*. |
| FR-051 | R2 | Android has Talk, Today, Conversations, Memory, Finance, Health, Coach, Career, Learn, Cyber, Personal, Devices, Approvals, Settings and permission screens. |
| FR-032 | Future | Email/calendar integrations (least-scope, no silent send) move to Future. |
| FR-AI-009 | R1 | User selects local vs provider reasoning **per domain** and sees whether audio, screens or text leave the device. |
| FR-AI-019, FR-AI-020, FR-AI-022, FR-AI-026 | Future | Multi-step UI workflows, email-draft workflow, VLM grounding and grounding explanations move to Future. |

## 7. New functional requirements

### 7.1 Avatar (FR-AV)

| ID | Release | Priority | Requirement | Acceptance / negative case |
|---|---|---|---|---|
| FR-AV-001 | R1 | MUST | An animated avatar (VRM model made in Blender) is shown on the Talk screen on Windows. | Loads with network off. |
| FR-AV-002 | R1 | MUST | Avatar pose mirrors the real session state: idle, listening, thinking, speaking, approval pending, error. | Listening pose never shown while the mic is closed, and vice versa. |
| FR-AV-003 | R1 | MUST | Mouth movement is driven by the audio actually playing. | Failed TTS = no mouth movement. |
| FR-AV-004 | R1 | MUST | Interrupt stops mouth and audio together. | ≤ 300 ms p95. |
| FR-AV-005 | R1 | MUST | Positive expressions (smile, nod) for an action appear only after verified success. | False-success corpus 0/100. |
| FR-AV-006 | R1 | MUST | Avatar can be turned off or set to reduced motion. | Setting persists; text UI fully usable. |
| FR-AV-007 | R2 | MUST | The same avatar and behavior run on Android. | Airplane-mode launch on phone. |
| FR-AV-008 | R3 | SHOULD | Phoneme-level visemes replace amplitude lip sync. | Offset ≤ 100 ms p95. |

### 7.2 Domains — common (FR-DOM)

| ID | Release | Priority | Requirement | Acceptance / negative case |
|---|---|---|---|---|
| FR-DOM-001 | R1 (Win) / R2 (Android) | MUST | Every domain is readable and writable on each device with the network off. | Airplane-mode suite per domain. |
| FR-DOM-002 | R1/R2 | MUST | Domain data is stored encrypted on each device. | File unreadable without the device key. |
| FR-DOM-003 | R1 | MUST | Every domain entry can be created, viewed, edited and deleted from the UI; edits keep history. | Delete creates a tombstone. |
| FR-DOM-004 | R1 | MUST | Domain entries can be created by voice; REVA shows the parsed entry and saves only after confirmation. | Misheard amounts are corrected before save. |
| FR-DOM-005 | R1 | MUST | Domain questions ("how much did I spend on food this month") are answered from stored data with the numbers shown. | Answer cites the records used; no invented figures. |
| FR-DOM-006 | R3 | MUST | Each domain has three privacy switches: sync on/off, which devices, hosted-model access. Hosted-model access defaults off for Memory, Finance, Health, Personal. | Network capture with switches off shows no domain content. |
| FR-DOM-007 | R3 | MUST | Per-domain and full export (CSV/JSON) and delete. | Export re-imports into a fresh install; delete removes data from UI, search, embeddings and sync queue. |
| FR-DOM-008 | R3 | MUST | File import per domain (CSV; OFX for Finance; standard health export formats where documented). | Bad rows reported, never silently dropped. |
| FR-DOM-009 | R3 | MUST | Changes on one device appear on the other after sync; deletes always win over older edits. | J-10 replay suite. |

### 7.3 Per-domain requirements

| ID | Release | Priority | Requirement |
|---|---|---|---|
| FR-MEM-001 | R1 | MUST | Memory stores facts and preferences the user approves; candidates proposed by REVA wait for approval (extends FR-035–FR-039). |
| FR-MEM-002 | R1 | MUST | Memory answers cite the stored items used, and say "I don't have that" instead of guessing. |
| FR-FIN-001 | R1 | MUST | Accounts, transactions, categories and budgets; voice and manual entry. |
| FR-FIN-002 | R3 | MUST | Bills with due-date reminders; recurring transactions; net-worth snapshots. |
| FR-FIN-003 | R3 | MUST | CSV and OFX import with duplicate detection. |
| FR-FIN-004 | all | MUST | No capability to move money, pay, buy or connect bank logins exists in 2.0. |
| FR-HLT-001 | R3 | MUST | Workouts, steps, sleep, heart rate, weight, nutrition and medication schedule; manual entry on both devices. |
| FR-HLT-002 | R3 | MUST | Android reads granted Health Connect types (read-only, per type), with a rationale screen and revocation honored. |
| FR-HLT-003 | all | MUST | REVA never diagnoses, recommends doses or treatment; urgent-symptom phrases get "contact a professional or emergency services". |
| FR-COA-001 | R3 | MUST | Goals, habits, daily check-ins and a weekly review. |
| FR-CAR-001 | R3 | MUST | Job applications, contacts, interviews and resume versions with a pipeline view. |
| FR-LRN-001 | R3 | MUST | Courses, certification progress, flashcards ("quiz me"), study-session log and streak. |
| FR-CYB-001 | R3 | SHOULD | Lab notes, CVE notes and home-lab inventory; no scanning or exploitation tools. |
| FR-PER-001 | R3 | MUST | Journal, people, reminders and events; journal never synced or sent anywhere unless switched on. |
| FR-TDY-001 | R3 | MUST | Today screen summarizes every enabled domain on both devices. |
| FR-SYN-001 | R2 | MUST | LAN sync between paired devices for every domain with sync on. |
| FR-SYN-002 | R3 | MAY | Opt-in relay sync (FR-048 amended). |

### 7.4 Language and voice (FR-LNG)

| ID | Release | Priority | Requirement |
|---|---|---|---|
| FR-LNG-001 | R1 | MUST | Common commands (open/close app, log expense, log workout, remind me, remember, today) work without waiting for a model. |
| FR-LNG-002 | R1 | MUST | When REVA is unsure which app, category, person or item you mean, it asks instead of guessing. |
| FR-LNG-003 | R1 | MUST | Follow-ups like "change it to 15", "delete that one" and "undo" refer to the last item correctly. |
| FR-LNG-004 | R1 | MUST | Every number REVA says about your data matches the stored data. |
| FR-LNG-005 | R1 | MUST | REVA speaks in the trained Revi voice once it passes the voice gate; the voice can be switched in Settings. |
| FR-LNG-006 | R3 | SHOULD | Telugu and Telugu–English mixed speech understood and answered (extends FR-017). |

## 8. Release mapping of domains

| Domain | Windows | Android | Sync |
|---|---|---|---|
| Memory | R1 | R2 | R2 (LAN) |
| Finance (core) | R1 | R2 | R2 (LAN) |
| Finance (bills, import) | R3 | R3 | R3 |
| Health | R3 | R3 (+ Health Connect) | R3 |
| Coach, Personal | R3 | R3 | R3 |
| Learn, Career, Cyber | R3 | R3 | R3 |

## 9. Nonfunctional requirements

NFR-001 – NFR-016 kept. New:

| ID | Release | Requirement |
|---|---|---|
| NFR-017 | R1 | Each domain is stored in its own encrypted file; keys live only in DPAPI/Credential Manager (Windows) or Android Keystore. |
| NFR-018 | R1 | Domain logic is implemented once (Domain Kernel) and verified through both the Python and Kotlin bindings with the same tests. |
| NFR-019 | R1 | Avatar rendering never blocks the UI thread; capped at 60 fps; paused when hidden. |
| NFR-020 | R4 | Domain queries meet a p95 of 100 ms on 10,000 records on the reference phone (target to validate). |
| NFR-021 | R3 | Health and Finance answers pass a safety/accuracy eval before release (no diagnosis, no invented numbers). |
| NFR-022 | R3 | Sync is idempotent and order-tolerant; tombstones beat older versions; no wall-clock-only conflict rule. |
| NFR-023 | R1 | Domain files are excluded from Android cloud backup and device-transfer by default. |

## 10. Provider and connectivity matrix (v2)

| Mode | Device | Reasoning | Domains | Speech | Disclosure |
|---|---|---|---|---|---|
| W-LOCAL | Windows | Ollama / deterministic | Local Kernel | faster-whisper + Kokoro | no network if models installed |
| W-REMOTE-OPTIN | Windows | Anthropic or other, enabled | Local Kernel; content sent only for consented domains | local | provider + data path shown |
| A-PAIRED | Android | Windows Core over gateway | Local Kernel, LAN sync | Android STT; Kokoro streamed or Android TTS | PC must be reachable |
| A-STANDALONE | Android | Opt-in hosted model | Local Kernel; consented domains only | Android STT/TTS | cost and network shown |
| A-OFFLINE-LITE | Android | Deterministic commands + Kernel queries | Local Kernel, fully usable | on-device STT only | "advanced reasoning unavailable" |

## 11. Privacy and trust

v1 rules 1–10 kept. Added:

11. Each domain's data stays on the device unless its sync switch is on.
12. Hosted models receive domain data only if that domain's hosted-model switch is on, and only the minimal fields a tool returned.
13. Health content is never used for advertising, never shared, and never interpreted as medical advice.
14. Finance features can read and record money only; there is no path to move it.
15. The relay stores only data encrypted on the device; REVA never claims end-to-end encryption before adversarial tests pass.
16. The avatar must never misrepresent state (listening, success) — it is an honest status display.

## 12. Screens

**Windows (WinUI 3):** Talk (avatar) · Today · Conversations · Memory · Finance · Health · Coach · Career · Learn · Cyber · Personal · Activity · Devices · Settings. Explicit approval dialog; push-to-talk hotkey; no always-on mic by default.

**Android (Compose):** onboarding and permissions · Talk (avatar) · Today · Conversations · the eight domain screens · Devices/pairing · Approvals · Settings (providers, per-domain privacy, storage, Health Connect). TalkBack, landscape, dark mode, permission-denied states. Never calls a Windows executable.

## 13. Acceptance scenarios

AC-001 – AC-014 kept. New:

- **AC-015:** Given the mic is closed, the avatar never shows the listening pose.
- **AC-016:** Given TTS fails, the avatar's mouth does not move and the text answer is shown.
- **AC-017:** Given airplane mode on Android, when the user logs an expense by voice and confirms, then it is stored encrypted and queued for sync.
- **AC-018:** Given an expense deleted on Windows while the phone is offline with an older edit, when the phone reconnects, then the expense stays deleted on both.
- **AC-019:** Given Finance hosted-model access off, when the user asks a spending question in Standalone mode, then no Finance data appears in any outbound request and REVA answers from local data or says reasoning is unavailable.
- **AC-020:** Given the user says "I have chest pain", REVA gives the professional/emergency message and no diagnosis.
- **AC-021:** Given Health Connect sleep permission revoked, the next import reads no sleep data and the UI shows the permission state.
- **AC-022:** Given a request to pay or transfer money, REVA explains it cannot do that; no capability exists to execute.
- **AC-023:** Given a Finance CSV export, when imported into a fresh install, then totals match exactly.

## 14. Release gates and versions

| Gate | Version tag | Must pass |
|---|---|---|
| G0 / P0 | v2.0.0-alpha.0 | Wake-word fail-closed committed; shutdown PID proof; repo restructured; all existing tests green |
| G1 / R1 | v2.0.0-alpha.7 | Real mic → model → Revi (or Kokoro) → speaker with avatar lip sync; interrupt; Notepad verified action; Memory + Finance in Kernel on Windows |
| G2 / R2 | v2.0.0-alpha.12 | Android app with avatar, voice, Memory + Finance offline, pairing, LAN sync, phone→PC action with PC approval |
| G3 | v2.0.0-alpha.17 | All eight domains on both devices offline; Today; privacy switches; export/delete |
| G4 / R3 | v2.0.0-beta.4 | Standalone Android; opt-in relay passed adversarial gate; reliability and battery profile |
| G5 / R4 | v2.0.0 | Signed installer, signed APK/AAB, security review, accessibility, evidence ledger complete |

Slice-by-slice detail: `04_SLICES/REVA_Version_Slices_v2.0.md`.

## 15. Validation and monetization (parked)

v1 §15 is parked, not deleted. It returns as a gate only if the owner decides to ship to outside users. Until then the success bar is MET-17 (owner daily use) plus all release gates.

## 16. Ownership and document control

- **Owner/developer:** implementation, architecture, releases.
- **QA engineer:** acceptance criteria, fixtures, automation, security/privacy regression, release evidence.
- Every change cites PRD ID, ARD ID, test ID, rollout flag and rollback plan (v1 rule kept).
- A requirement is VERIFIED only with evidence recorded in the ledger (ARD-800 §5). Compiling or a passing unit test is not enough for voice, Android, packaging, pairing, sync or Health Connect.

## 17. Baseline (from the 2026-10-11 audit)

Verified then: Python 326 passed / 2 skipped; .NET 334 passed; ruff/mypy clean. Not verified: live mic, GUI E2E, real Ollama, real Chatterbox, installer, any Android code, any avatar, any domain beyond memory. Wake-word resolver fails open in HEAD (P0-01). Re-inspect the repo before implementation.
