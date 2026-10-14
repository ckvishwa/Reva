# REVA — Concepts Guide v2.0

**Document ID:** REVA-CONCEPTS-002 · **Version:** 2.0.2 · **Date:** 2026-10-12
Every idea the PRD and ARDs depend on, explained in plain words, with where it is specified.

## 1. Product shape

**Two full devices.** The Windows app and the Android app are each a complete REVA. Either works alone and offline. When both exist, they sync. *(ARD-000)*

**REVA Core.** The Python program on the PC that runs sessions, voice, planning, policy and sync. It listens only on `127.0.0.1`. *(ARD-300)*

**Android local brain.** The phone's equivalent of the Core: its own session, planner client and policy broker. It uses the PC when paired, a hosted model if you enable one, or offline-lite. *(ARD-200)*

**Run modes (Android).** *Paired* — the PC thinks. *Standalone* — a disclosed hosted model thinks. *Offline-lite* — deterministic commands and local data only. The current mode is always shown. *(ARD-200 §2)*

## 2. Domains and the Kernel

**Life domain.** One area of life with its own data, rules, voice tools and privacy switches: Memory, Finance, Health, Coach, Career, Learn, Cyber, Personal. *(ARD-700)*

**Domain Kernel.** One Rust library that holds all domain rules and storage. The same compiled logic runs inside the Core (via Python bindings) and inside the Android app (via Kotlin bindings). Write once, behave identically on both devices. *(ARD-700, ADR-027)*

**UniFFI.** A tool that generates Python, Kotlin (and Swift) bindings from one Rust library, so other languages can call it like a normal library. *(ADR-027)*

**SQLCipher.** SQLite with full-file encryption. Each domain gets its own encrypted file. *(ADR-028)*

**OS key vault.** Where encryption keys live: DPAPI/Credential Manager on Windows, Android Keystore on the phone. Keys never sit in files or logs. *(ADR-015, ADR-028)*

**KeyProvider.** The small interface the Kernel uses to ask the host app for a domain key, so the Kernel never knows which OS it runs on.

**Event sourcing.** Every change is recorded as an event ("transaction added", "workout deleted"). Current tables are rebuilt from these events. This gives history, audit and sync. *(ADR-029)*

**Projection.** A table computed from events, e.g., "current transactions". It can be deleted and rebuilt. *(AR-DOM-004)*

**Tombstone.** An event that marks something deleted. It always beats older edits, so deleted data can never come back after sync. *(AR-DATA-011)*

**Today.** A read-only summary across all enabled domains on one screen. *(FR-TDY-001)*

**Privacy switches.** Per domain: sync on/off, which devices, and whether a hosted model may see it. Hosted access starts off for Memory, Finance, Health, Personal. *(ADR-032)*

**Consent filter.** Code in the Core and Android brain that removes data from non-consented domains before any request goes to a hosted model. *(AR-CORE-010)*

**Domain safety limits.** No capability to move money exists. Health answers never diagnose or suggest doses; urgent symptoms get a fixed "contact a professional or emergency services" message. *(ADR-033)*

**Health Connect.** Android's shared health data store. REVA reads only the types you grant and never writes back. *(ADR-034)*

## 3. Sync

**Outbox.** A queue of local events waiting to be sent to other devices. *(ARD-500 §3)*

**Idempotent apply.** Receiving the same event twice changes nothing. *(AR-DATA-010)*

**Lamport clock.** A counter each device increments so events can be ordered without trusting wall clocks. *(ARD-700 §2.2)*

**Conflict record.** When two devices change the same Finance amount or Health measurement at once, REVA shows both and asks you, instead of silently picking one. *(AR-DOM-008)*

**LAN sync.** Devices sync directly on the home network through the pairing gateway. Default. *(ARD-500)*

**Relay.** Optional off-network sync through Supabase. Events are encrypted on your devices before upload; the server stores only ciphertext. No "end-to-end encrypted" label until adversarial tests pass. *(ADR-031)*

**Group key.** The shared encryption key for relay sync, created on the PC at pairing and passed to the phone over the paired channel. *(ARD-500 §3)*

## 4. Devices and trust

**Pairing.** PC shows a QR code; phone scans; both show a matching code; you approve on the PC; each side keeps a scoped grant. *(ARD-500 §2)*

**Pairing gateway.** A narrow, separate entry point on the PC for paired devices. The phone never gets the Core's own token. *(ADR-009)*

**Revocation.** Removing a device makes its next request fail before anything runs. *(AR-DATA-004)*

**Trust zones.** Untrusted input (speech, model output, screen text, imports, synced events) → deterministic policy → native executors with evidence. *(ARD-000 §4)*

## 5. Agent and actions

**Planner.** The model step that reads your request and returns a typed decision: answer, clarify, propose an action, or propose a short plan. *(ARD-600)*

**PlannerDecision schema.** The strict JSON format the planner must return; anything else is rejected. *(`08_CONTRACTS/planner-decision.schema.json`)*

**Capability registry.** The list of everything REVA can do, with arguments, risk tier and which device confirms. Shared by PC and phone. *(ARD-600 §2)*

**Risk tiers.** T0 information · T1 safe and reversible · T2 sensitive, needs your approval · T3 high risk, denied. Policy computes the tier; the model cannot. *(ARD-600 §2)*

**Grant.** A signed permission for one action, bound to its arguments, target device, expiry and idempotency key. Executors act only on a valid grant. *(AR-AGT-016)*

**Target-device approval.** A sensitive action on the PC must be approved on the PC, even if the phone asked. *(ADR-008)*

**Idempotency key.** A unique key that makes a retried action run at most once. *(AC-004)*

**Evidence.** What the executor actually observed (process started, window has the text, Kernel committed event). REVA speaks success only from evidence. *(AR-AGT-005)*

**Fast path.** Known simple commands ("open Notepad") skip the model for speed and reliability. *(AR-AGT-012)*

**UI Automation (UIA).** Windows' accessibility API used to inspect and operate app controls safely. *(ARD-100, R2)*

## 6. Voice

**Session state machine.** Idle → Listening → Endpointing → Transcribing → Reasoning → (Approval → Executing) → Speaking → back. *(ARD-300 §3)*

**turn_epoch.** A number that goes up on every interrupt. Anything from an older epoch (audio, model output, avatar mouth) is thrown away. *(AR-CORE-001)*

**VAD / endpointing.** Detects speech and when you finished talking. *(ARD-400)*

**Barge-in.** Interrupting REVA while it speaks; playback stops and a new turn starts. *(FR-006)*

**Chunked TTS.** Speaking sentence by sentence while the rest is generated. Labeled as chunked, not streaming. *(ARD-400 §1)*

**Provider registry.** The list of available STT, TTS and model providers, with defaults (faster-whisper, Kokoro, Ollama) and opt-ins. *(ARD-300 §5)*

**Push-to-talk.** A hotkey or button that opens the mic; no always-on mic by default. *(AR-WIN-010)*

## 6b. Language understanding and generation (ARD-450)

**NLU (natural language understanding).** Turning what you said into a structured request: intent ("log expense") plus slots (amount, category, date).

**NLG (natural language generation).** Turning results back into what REVA says.

**Normalization.** Converting spoken forms into typed values: "twelve bucks" → 12.00 USD, "tomorrow at 7" → a datetime. Ambiguous readings are kept, not guessed.

**Rule fast path.** Hand-written patterns for common commands that skip the model entirely. Faster and never hallucinates. *(Lakewood rule interpreter)*

**Slot.** One piece of information an intent needs (amount, app name, time).

**Entity resolution ladder.** How a phrase becomes a specific thing: exact name → known alias → word match → fuzzy match → vector similarity → ask you. *(Lakewood)*

**Alias table.** Learned alternative names ("VS code", "code editor" → Visual Studio Code). Grows only from confirmed clarifications.

**Shadow mode.** A new method (e.g., vector matching) runs and logs its guesses but does not decide, until its accuracy is measured.

**Score margin.** The gap between the best and second-best match. A high score with a tiny margin still means "ask". *(Lakewood calibration)*

**Dialogue state.** What the conversation currently knows: active intent, filled and missing slots, pending question, last thing mentioned (so "delete that one" works).

**Anaphora.** Words like "it", "that one" that point back to something said earlier.

**Proposal with evidence.** Every action carries how each part was understood (which phrase, which resolution type, which score). *(Lakewood MutationProposal)*

**authorize() / AuthorizationDecision.** A pure, model-free check that accepts a proposal or returns a reason code and a clarifying question. Same function for rule and model paths. *(Lakewood authorize_cart_mutation)*

**Content words vs filler.** "Uh, can I please" is filler and ignored; an unmatched content word ("salad") blocks the action until clarified.

**Template NLG.** Fixed sentences for confirmations, outcomes and errors, filled with verified values. "Done" always comes from a template.

**Grounded answer.** A model-written answer that may only use facts from the tool results it was given, and cites them.

**Number and claim check.** Every number and every "I did X" in a model answer must match the tool results, or the answer is regenerated or replaced by a template.

**Acknowledge-first.** A short "One sec." while REVA thinks, so the turn feels responsive; never phrased as success. *(Corx)*

**TurnEvent.** A local record of one turn (what was heard, understood, proposed, decided, confirmed) used to build test fixtures. *(Lakewood LearningEvent)*

**Code-mixing.** Switching between Telugu and English in one sentence; handled in normalization and aliases.

## 6c. Voice assets

**Revi.** REVA's trained voice. Becomes the default once it passes the voice gate.

**Voice gate.** The checks a voice must pass to be default: fast first audio, quick interrupt, clear pronunciation (measured by transcribing it back), owner rating, no orphan processes. *(AR-VA-021)*

**Asset root and manifest.** Models and datasets live outside git; `assets.manifest.json` lists each with its hash, source and license. A voice whose hash does not match does not load. *(ADR-038)*

**Provenance.** Where an asset came from and under what terms. Required for every voice dataset before training or shipping.

**Bakeoff.** A side-by-side comparison of TTS engines on the same scripts and metrics, ending in a written decision. *(V2)*

## 7. Avatar

**VRM.** A standard 3D avatar format (glTF-based) with a humanoid rig and named expressions. Exported from Blender. *(ADR-024)*

**VRMA.** Animation clips for VRM avatars (idle, listening, thinking, talking). *(ARD-400 §3)*

**three.js + three-vrm.** The web 3D engine and VRM loader that render the avatar inside a WebView. *(ARD-400 §4)*

**WebView2 / Android WebView.** Embedded browsers that host the same avatar package in both apps, offline. *(ARD-100, ARD-200)*

**Avatar events.** `avatar.state`, `avatar.mouth`, `avatar.expression`, `avatar.settings` — sent from the app to the avatar page; the page only replies "ready" or "error". *(`08_CONTRACTS/avatar-events.schema.json`)*

**RMS lip sync.** Mouth openness follows the loudness of the audio actually playing. First version. *(AR-VA-010)*

**Visemes.** Mouth shapes for speech sounds; a later upgrade for more accurate lip sync. *(AR-VA-013)*

**Honest avatar rule.** The avatar shows only true state: listening only when the mic is open, smiling at an action only after verified success. *(PRD §11 rule 16)*

## 8. Delivery

**Slice.** One shippable, tested increment with its own version tag. *(04_SLICES)*

**Gate.** A checkpoint (G0–G5) with must-pass criteria that ends a phase. *(PRD §14)*

**Evidence ledger.** A CSV row per verified requirement: test, commit, device, model versions, result, artifact. Nothing is VERIFIED without it. *(ARD-800 §5)*

**Env guard.** A test setup check that refuses to run against real data or non-local databases. *(AR-CORE-004)*

**Harvest.** Re-implementing proven designs and tests from FRIDAY OS/AuraO in the new stack instead of copying old code. *(ADR-023)*
