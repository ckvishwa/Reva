# ARD-200 — Cross-Platform App (Android first) v2.0

**Document ID:** REVA-ARD-200 · **Version:** 2.0.1 · **Date:** 2026-10-11 · **Status:** Proposed
**Replaces:** ARD v1 §8. **Decisions:** ADR-002, ADR-012, ADR-013, ADR-021, ADR-030, ADR-034.

## 1. Summary

A native Kotlin + Compose Android app that is a full REVA on its own: every domain screen, its own encrypted data through the Domain Kernel, its own local brain. It shares four things with Windows: Core API contracts, the avatar package, the action/approval rules (same capability registry), and the Domain Kernel. iOS is out of scope; Swift bindings from the same Kernel are the path if it is ever added (ADR-002 trigger).

## 2. Run modes (always shown on screen)

| Mode | Brain | Domains | STT | TTS | Needs |
|---|---|---|---|---|---|
| Paired | Windows Core over the pairing gateway | Local Kernel copy, LAN sync | On-device recognizer, or audio streamed to PC | Kokoro streamed from PC, or Android TTS | PC reachable on LAN |
| Standalone | Opt-in hosted model, disclosed; sensitive domains only with per-domain consent | Local Kernel copy; relay sync if enabled | On-device if available, else disclosed fallback | Android TTS | Internet + consent |
| Offline-lite | Deterministic commands + Kernel queries | Local Kernel, fully usable; outbox queues changes | On-device only | Android TTS | Nothing; "advanced reasoning unavailable" for open questions |

## 3. Architecture

- **UI:** Compose, ViewModel + StateFlow, coroutines. Single-activity, navigation per screen.
- **Local brain:** Kotlin session state machine (same states as ARD-300 §3), provider registry, planner client (PC Core or hosted), and a policy broker that loads the **same capability registry file** as the Core (`08_CONTRACTS/capability-registry`), so tiers are identical.
- **Kernel:** UniFFI Kotlin bindings plus `libreva_kernel.so` per ABI (`arm64-v8a`, `x86_64`). Keys from Android Keystore. Domain files under `noBackupFilesDir`.
- **Avatar:** same `avatar/` package in a WebView via `WebViewAssetLoader`; network blocked; lip sync from the envelope of audio actually played (TTS synthesized to file, played through `AudioTrack`).
- **Health Connect:** read-only client; per-type permission; imports into the Health domain through the Kernel.
- **Storage split:** Room for UI cache (conversations, sessions); Kernel files for domain data; Keystore for keys.

## 4. Modules

| Module | Owns | Never does |
|---|---|---|
| AND-01 Shell | Talk, Today, Conversations, eight domain screens, Devices, Approvals, Settings | Call a Windows executable |
| AND-02 VoiceService | Foreground service type `microphone`, notification, started from a user tap | Capture outside an allowed, visible state |
| AND-03 STT | `SpeechRecognizer`, on-device only after availability check | Continuous recognition loop |
| AND-04 Playback | TTS to file, `AudioTrack`, `turn_epoch` flush, envelope | Resume stale audio |
| AND-05 AvatarHost | WebView, local assets, state/mouth events, pause in background | Load remote content |
| AND-06 Actions | Intents/public APIs: app launch, alarms, reminders, calendar insert, share | Use AccessibilityService for agent control |
| AND-07 Pairing | Keystore keypair, QR, fingerprint, signed challenge | Hold the Windows Core bearer token |
| AND-08 LocalBrain | Session, provider registry, planner calls, policy broker | Let a model compute its own risk tier |
| AND-09 DomainKernel | Kotlin bindings, encrypted file per domain, Keystore key | Expose domain files to other apps |
| AND-10 HealthConnect | Read-only import of granted types | Write to Health Connect or read ungranted types |
| AND-11 Sync | Outbox, tombstones, per-domain scopes, LAN or relay | Replay actions from the sync stream |
| AND-12 Providers | Actual processing path per provider and per domain | Label a cloud path "offline" |

## 5. Requirements

| ID | Stage | Requirement | Verification | Replaces |
|---|---|---|---|---|
| AR-AND-001 | R2 | Mic permission requested only on a user tap; text works when denied | Deny, deny-forever, revoke-mid-session | AR-062, AR-067 |
| AR-AND-002 | R2 | Foreground service type and notification match the running API level | Physical phone + API 31–36 emulators | AR-063, FR-011 |
| AR-AND-003 | R2 | On-device STT only after availability check; fallback disclosed | Capability mock test | AR-064, FR-012 |
| AR-AND-004 | R2 | Recognizer, TTS and WebView released on session end | Leak test | AR-065 |
| AR-AND-005 | R2 | Avatar loads offline; mouth driven by played-audio envelope; stops on interrupt | Airplane launch; interrupt timing | new |
| AR-AND-006 | R2 | No `QUERY_ALL_PACKAGES`, AccessibilityService or privileged settings | Manifest review in CI | AR-066, ADR-021 |
| AR-AND-007 | R2 | Pairing: QR + fingerprint + signed challenge; wrong peer and replay fail closed | MITM, replay, expired code | AR-041, AR-042 |
| AR-AND-008 | R2 | Phone can request PC actions; T2+ PC actions need approval on the PC | Phone-only approval fails | AR-037, ADR-008 |
| AR-AND-009 | R2 | Kernel loads on arm64-v8a and x86_64; every enabled domain readable/writable offline | Airplane domain suite | new |
| AR-AND-010 | R2 | Domain files encrypted; key only in Keystore; excluded from backup and device transfer | File inspection; backup-rules test | AR-054, FR-040, NFR-023 |
| AR-AND-011 | R3 | Standalone mode answers with the PC off via a disclosed provider; sensitive domains leave only with consent | No-PC E2E; network capture | AR-068, FR-AI-024, AR-AI-033 |
| AR-AND-012 | R3 | Offline-lite answers domain questions locally; never fabricates open-ended answers | AC-006 + domain fixtures | FR-AI-024 |
| AR-AND-013 | R3 | Health Connect read-only, per-type permission, revocation stops import, rationale screen | Permission matrix, Android 14+ | new |
| AR-AND-014 | R3 | Deleted records never return after offline reconnect, in every domain | Tombstone replay per domain | AR-057, AC-008 |
| AR-AND-015 | R3 | 30-min active voice battery and thermal profile on 2 device tiers | Profiling report | AR-077 |
| AR-AND-016 | R4 | Signed APK for testers, AAB for Play; upgrade keeps all domain data | Clean install and upgrade | AR-070, FR-058 |
| AR-AND-017 | R2 | minSdk 31, targetSdk/compileSdk 36 recorded in the build | Gradle assertion | AR-061 |
| AR-AND-018 | R2 | Compose main thread never blocked by capture, recognition or Kernel calls (Kernel on IO dispatcher) | StrictMode + jank trace | NFR-004 |

## 6. Release gate (R2)

On a physical phone: tap Talk, speak, avatar answers through the paired PC; open Calculator on the PC from the phone with PC approval; in airplane mode add an expense and a memory; reconnect and see both on the PC; revoke the phone on the PC and the next request fails.
