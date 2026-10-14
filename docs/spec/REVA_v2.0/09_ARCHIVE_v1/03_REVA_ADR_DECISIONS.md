# REVA — Architecture Decision Records (ADRs)

**Document:** REVA-ADR-INDEX-001 | **Status:** Proposed architecture choices, effective only when adopted into repository | **Date:** 2026-10-11

An ADR records a **decision with rejected alternatives and a reversal trigger**. These decisions complement the PRD and ARD; they are not proof that the implementation has been completed.

## ADR-001: Keep the existing Windows and Python architecture

- **Status:** Accepted as planning baseline.
- **Context:** The audited code already contains a WinUI 3 client, FastAPI Core, SQLite, ADK, voice providers, and 660 passing tests across Python/.NET, while the app is not distributable.
- **Decision:** Incrementally enhance the existing WinUI 3/C# desktop and Python Core; do not rewrite in Electron, Flutter, Tauri, or another Python GUI framework.
- **Rejected:** cross-platform UI rewrite solely for code sharing; duplicate assistant logic in each client.
- **Consequence:** Windows-native UI remains separate from Android UI, while protocols, sessions, memory and policy concepts are shared. Two UI stacks increase maintenance but avoid discarding verified code.
- **Revisit when:** core product data demonstrates a dominant third platform or Windows maintenance becomes the actual bottleneck.
- **Proof:** existing tests remain green after every migration slice.

## ADR-002: Android native Kotlin + Jetpack Compose

- **Status:** Proposed.
- **Decision:** New Android app is Kotlin/Compose using coroutines, Room, Android Keystore and platform audio adapters. APK is a first-class build artifact.
- **Rejected:** porting deleted AuraO Flutter code, wrapping WinUI, running desktop Python unchanged on Android, React Native as a reflexive default.
- **Consequence:** distinct UX layer and testing; better direct access to Android microphone, foreground services and lifecycle.
- **Revisit when:** two mobile OS targets become committed and existing native implementation has measurable reuse problems.
- **Proof:** emulator + real-device mic permission and speech round-trip tests.

## ADR-003: One modular monolith Core, not microservices

- **Status:** Proposed.
- **Decision:** One Python Core with strict assistant, voice, policy, memory and device boundaries; separate subprocess permitted for heavyweight TTS or model isolation.
- **Rejected:** early Kubernetes/microservices, Kafka-based communication, multiple databases, shared mutable Python state across devices.
- **Consequence:** simpler debugging, release/hosting and performance profiling; later scaling requires extraction of a demonstrably hot boundary.
- **Revisit when:** isolation, multi-user scaling or uptime requirements are measured and cannot be met by this process.
- **Proof:** module contract and process lifecycle tests.

## ADR-004: Provider-neutral voice pipeline (STT → LLM → TTS)

- **Status:** Proposed.
- **Decision:** Build reusable session state/events, cancellation, VAD, STT, model and TTS interfaces. Start with existing faster-whisper and Chatterbox when available; use Android system voice as client adapters. Never directly copy restaurant-domain flows.
- **Rejected:** hardcoding one voice provider or assuming a live speech-to-speech model supports all tool use and offline cases.
- **Consequence:** extra interface/test work; safe substitution and lower lock-in. Barge-in and endpointing are modeled as first-class events.
- **Revisit when:** real-time end-to-end provider produces demonstrably better measured latency/quality without breaking policy semantics.
- **Proof:** provider contract tests, 100-turn evaluation and physical audio trace.

## ADR-005: Full duplex is an enhancement, not a launch dependency

- **Status:** Proposed.
- **Decision:** R1 uses reliable turn-based natural conversation, incremental/chunked TTS, explicit cancellation; R3 may add continuous full-duplex barge-in and AEC by capability.
- **Rejected:** indefinite parallel audio capture/playback as the very first milestone.
- **Consequence:** first usable loop ships faster; early voice quality is more limited than premium consumer voice products.
- **Revisit when:** interrupts are stable and physical echo/crosstalk benchmarks justify a duplex audio stack.
- **Proof:** interruption latency and device-loss tests.

## ADR-006: Local-first memory with explicit user controls

- **Status:** Proposed.
- **Decision:** Windows SQLite remains authoritative for local memory; Android Room stores scoped local data. Memory CRUD, export, retention states and semantic search are explicit APIs. User data is not saved merely because it appears in conversation.
- **Rejected:** invisible auto-memory on every turn, hosted vector database at R1, global shared SQLite file.
- **Consequence:** user trust and portable state; harder sync semantics require durable events and tombstones.
- **Revisit when:** measured retrieval and concurrency demand alternate storage; user opts into managed cloud storage.
- **Proof:** delete never appears in FTS/semantic results, even after sync retry.

## ADR-007: Separate deterministic action policy from LLM

- **Status:** Proposed (preserves existing desktop allowlist principle).
- **Decision:** Model emits a typed proposed action. Capability registry and policy independently compute risk, require approval, execute on target, and return observed result.
- **Rejected:** arbitrary shell tool, model-selected risk tier, natural-language direct executor command, optimistic success speech.
- **Consequence:** bounded utility and extra confirmations; fewer security failures and clearer user trust.
- **Revisit when:** tightly scoped high-trust automation has complete audit and explicit enablement.
- **Proof:** prompt-injection, parameter tampering, stale approval, duplicate execute tests.

## ADR-008: Target-device approval for sensitive remote actions

- **Status:** Proposed.
- **Decision:** Phone may propose a PC action; sensitive PC actions require explicit confirmation at the PC (or separately reviewed user-present PC authorization mechanism). Approval binds full arguments, target and expiry.
- **Rejected:** accept phone speech as final consent to close/delete/send on PC.
- **Consequence:** less frictionless; significantly safer against lost phone, replay and accidental speech.
- **Revisit when:** trusted hardware-authenticated remote approval has a documented threat model.
- **Proof:** phone-only approval test must fail.

## ADR-009: Loopback Core with a distinct pairing gateway

- **Status:** Proposed.
- **Decision:** Python Core API remains loopback by default. A dedicated opt-in, narrow gateway listens on LAN for authenticated paired devices and maps only permitted operations into Core service calls.
- **Rejected:** changing Core bind to `0.0.0.0`, port-forwarding internal bearer API, shipping bearer token inside APK.
- **Consequence:** another boundary to implement and test; prevents accidentally making all local endpoints remotely available.
- **Revisit when:** a formal zero-trust remote API is ready, but Core local auth should still remain separate.
- **Proof:** unauthenticated LAN port scan, scope and revocation tests.

## ADR-010: Explicit peer authentication, QR-assisted pairing

- **Status:** Proposed.
- **Decision:** verified QR/short-code handshake, bound gateway fingerprint, device-generated keys, signed challenge and revocable capability grants.
- **Rejected:** IP address alone, shared static password for all users, unauthenticated Bonjour/mDNS discovery, TOFU without identity check.
- **Consequence:** additional onboarding steps; mitigates LAN impersonation and key substitution.
- **Revisit when:** mature account-bound identity is introduced with equal/better explicit consent.
- **Proof:** wrong fingerprint, expired code, device replacement, replay and revocation tests.

## ADR-011: JSON events + binary audio over local WebSocket first

- **Status:** Proposed.
- **Decision:** HTTP control APIs, WebSocket ordered typed events, and negotiated binary audio frames for paired LAN. Add WebRTC/LiveKit only after duplex/network measurements support it.
- **Rejected:** base64 all PCM in REST JSON, immediate LiveKit as mandatory back-end, self-invented unreliable-UDP protocol.
- **Consequence:** easier R2 implementation and debugging; WAN latency and NAT traversal are intentionally deferred.
- **Revisit when:** real packet loss/jitter, echo control, bandwidth or remote off-LAN requirements justify WebRTC.
- **Proof:** turn/cancel ordering, reconnect, audio format validation and 5% packet drop simulation.

## ADR-012: Android background hotword gated by platform feasibility

- **Status:** Proposed.
- **Decision:** R2 default is explicit tap-to-talk foreground session. Validate future background mic paths only against Android service rules, permission states and OEM battery behavior. A system-selected `VoiceInteractionService` is a separate OS-role UX/product decision.
- **Rejected:** promise unrestricted 24/7 microphone via an ordinary background service, use a perpetual generic SpeechRecognizer loop.
- **Consequence:** fewer invisible assistant interactions initially; Play policy/battery and user trust protected.
- **Revisit when:** target API/OEM testing and eligible role support prove a compliant implementation.
- **Proof:** Android 12–16 lifecycle matrix and battery profile; ensure no stealth capture.

## ADR-013: Hybrid speech/provider strategy on Android

- **Status:** Proposed.
- **Decision:** Android selects on-device STT only when available, otherwise user-approved recognizer; Android system TTS first; paired Windows Core or opt-in hosted model for advanced reasoning. Capability UI shows actual processing path.
- **Rejected:** promise wholly offline advanced assistant on every mid-range phone or assume system SpeechRecognizer is always local.
- **Consequence:** honest offline limitations; hosted mode may incur per-turn cost and privacy disclosure.
- **Revisit when:** a usable on-device model meets speed, heat, quality and APK-size budgets.
- **Proof:** no-PC and offline matrix, provider failover/no-internet tests.

## ADR-014: Durable event outbox and tombstone sync

- **Status:** Proposed.
- **Decision:** eventual sync with UUID event idempotency and monotonically versioned memory; deletes carry tombstones until ack/retention horizon; action requests are not auto-replayed from sync stream.
- **Rejected:** raw SQLite replication, naive wall-clock last-write-wins for deletes, treating queued actions as normal data changes.
- **Consequence:** added schema and conflict testing; resilient offline operation and safe deletion.
- **Revisit when:** >2 devices or complex collaborative edits justify full CRDT analysis.
- **Proof:** clock skew, reordered batches, offline edits, duplicate events and deletion resurrection tests.

## ADR-015: Windows secrets protected with OS-native credential storage

- **Status:** Proposed.
- **Decision:** migrate `local_auth_token` and external provider secrets to DPAPI/Credential Manager; Android keys via Keystore. Do not use plain `.env` as a shipped user key store.
- **Rejected:** plaintext token file long term, encrypted bytes with hardcoded app key, logging keys for troubleshooting.
- **Consequence:** identity/migration complexity for Windows profiles and backup/restore.
- **Revisit when:** hardware-backed/enterprise key provider required.
- **Proof:** local file scan, same-user API tests, cross-user access denial and upgrade migration.

## ADR-016: Package the product, not development environment

- **Status:** Proposed.
- **Decision:** signed, self-contained or correctly dependency-bundled Windows distribution that starts Core without installed `.venv`; signed APK for testers and AAB for Play release.
- **Rejected:** tell users to install Python/dotnet CLI and clone repo, distribute unsigned production builds.
- **Consequence:** larger artifacts and extra installer/update work.
- **Revisit when:** deployment constraints favor MSIX vs traditional installer; keep clean-machine criterion either way.
- **Proof:** clean Windows VM installation/uninstall, APK physical install, update/signature checks.

## ADR-017: Local security and observability over opaque cloud metrics

- **Status:** Proposed.
- **Decision:** structured, redacted session/action logs, user-facing audit and opt-in diagnostic metrics; no raw audio in logs. Every action has correlation ID and observed outcome.
- **Rejected:** silent full transcript upload, indefinite microphone file retention, “success” based on model response.
- **Consequence:** debugging needs synthetic fixtures and explicit user-repro export tools.
- **Revisit when:** enterprise compliance adds explicit retention/legal requirements.
- **Proof:** telemetry opt-out, log scan and outcome reconciliation.

## ADR-018: Use third-party voice infrastructure selectively

- **Status:** Proposed.
- **Decision:** treat Lakewood's learnings and LiveKit patterns as references, not automatic wholesale dependencies. If advanced real-time media/remote NAT is required, conduct a constrained LiveKit proof with provider/data flow/privacy evaluation.
- **Rejected:** move everything onto SIP telephony, assume cloud LiveKit always cheaper than local voice, or create media microservices without users.
- **Consequence:** lower initial infrastructure overhead but more in-house turn orchestration.
- **Revisit when:** user trials show p95 latency or barge-in quality unattainable with current session pipeline.
- **Proof:** side-by-side instrumented prototype before migration.

## ADR governance

Every ADR change must identify: affected PRD FR/NFR IDs; ARD AR IDs; impacted files; migration compatibility; measurable reason; proof artifacts; rollback. Record adoption in Git on the chosen branch. The current ADRs are design proposals in this packet, not repository commits.


## ADR-019: First-class AI/ML intelligence subsystem; one bounded planner

- **Status:** Proposed, 2026-10-11.
- **Decision:** integrate wake/VAD/STT, real tool-call-capable model, memory embeddings, policy-aware planning, UI grounding and verified TTS response as separable provider interfaces; use **one bounded planner loop** before multi-agent frameworks.
- **Rejected:** passive chat-only product, silent deterministic fake model in consumer mode, building custom LLM/VLM before benchmarks, swarm/microservice agent choreography.
- **Proof:** typed tool-decision schema, provider contract tests, reproducible intent/action eval, measured live mic→real model→speech.

## ADR-020: Native UI grounding with observed outcomes, not blind clicks

- **Status:** Proposed, 2026-10-11.
- **Decision:** Windows UI Automation/app APIs first, fresh snapshots and target identity checks, opt-in VLM screenshot fallback when necessary; strict policy and native evidence verify effects.
- **Rejected:** generic `execute_os_command`, static click coordinates, unrestricted `SendInput`, VLM self-approval or self-certified success.
- **Proof:** stale selector, focus changes, DPI, screen injection and physical Notepad E2E fixtures.

## ADR-021: Android Play distribution prioritizes policy-compliant intents and user-directed flows

- **Status:** Proposed, 2026-10-11.
- **Decision:** Android voice + intents/public APIs first, explicit MediaProjection consent for visual use, narrowly scoped Accessibility only after Google Play eligibility/purpose review. A generic autonomously planning and executing Accessibility agent is **not** assumed Play-publishable.
- **Rejected:** treating AccessibilityService as a universal AI automation permission.
- **Proof:** Play policy review, runtime permission UI, real Android API 34+ device test and negative permissions suite.

## ADR-022: Typed model/native contracts; defer forced gRPC migration

- **Status:** Proposed, 2026-10-11.
- **Decision:** model output validated using `08_REVA_PLANNER_DECISION.schema.json`; native executor messages standardized in `07_REVA_NATIVE_AGENT_V1.proto` for potential sidecar/gRPC integration. Keep existing HTTP and the ADR-011 planned WebSocket transport for near-term delivery.
- **Rejected:** making Protobuf transport itself an authorization system or replacing working loopback paths before an adapter performance/security need is measured.
- **Proof:** valid and invalid schema tests, replay/idempotency, transport-auth review, cross-language contract generation before implementation.
