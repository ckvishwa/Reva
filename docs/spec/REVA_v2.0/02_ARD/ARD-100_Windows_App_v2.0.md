# ARD-100 — Windows App v2.0

**Document ID:** REVA-ARD-100 · **Version:** 2.0.1 · **Date:** 2026-10-11 · **Status:** Proposed
**Replaces:** ARD v1 §1 Windows parts, §9 Windows parts. **Decisions:** ADR-001, ADR-015, ADR-020, ADR-024 (`03_ADR`).

## 1. Summary

The Windows app is the existing WinUI 3 desktop, grown into the full REVA face: avatar at the center, voice in and out, every life domain as a page, and the only place Windows actions run. It owns hardware and the window; the Python Core owns thinking, policy and sync; the Domain Kernel (inside the Core) owns domain data.

## 2. Process model

- `Reva.Desktop` (WinUI 3, .NET 10) starts an **owned** Core process using a bundled Python runtime, bound to `127.0.0.1` on a random port.
- The Core bearer token is generated per install and stored in Credential Manager (DPAPI); never in a config file (NFR-005).
- If a healthy Core is already running, the app attaches as **external** and never kills it on exit (AC-010).
- The avatar runs in a WebView2 control loaded from the local `avatar/` package through a virtual host mapping; navigation outside it is blocked.
- Windows actions run in the WinUI process's executor (C#) only with a Core-signed grant.

## 3. Screens

Talk (avatar, live transcript, Stop, mic mute, speaker mute) · Today · Conversations · Memory (candidate approvals, edit, delete, export) · Finance (accounts, transactions, budgets, bills, import) · Health (fitness, sleep, nutrition, measurements, medication schedule) · Coach (goals, habits, check-ins, weekly review) · Career · Learn · Cyber · Personal (journal, people, reminders) · Activity (actions with evidence) · Devices (pair, revoke, sync status) · Settings (providers, per-domain privacy and sync, voice, avatar, telemetry).

Rich charts on Today and domain pages may render in WebView2 panels fed by Core APIs; all data access stays in the Core.

## 4. Modules

| Module | Owns | Never does |
|---|---|---|
| WIN-01 Shell | Navigation, pages, state from Core events, accessibility | Decide policy |
| WIN-02 AudioCapture | Mic selection, 16 kHz mono PCM, device loss, real mic-open state | Store raw audio |
| WIN-03 Playback | Speaker output, `turn_epoch` flush, RMS envelope for lip sync | Play audio from a stale epoch |
| WIN-04 AvatarHost | WebView2, forwards state/mouth events, FPS cap, pause when hidden | Send anything to Core except UI-ready pings |
| WIN-05 CoreSupervisor | Start, health, attach, owned-vs-external shutdown | Expose Core beyond loopback |
| WIN-06 Executor | App launch/close (allowlist), UIA inspect/invoke/set-text, postcondition evidence | Act without a valid grant |
| WIN-07 ApprovalUI | T2 confirmation bound to action digest and TTL | Accept voice-only approval for T2+ |
| WIN-08 Secrets | DPAPI/Credential Manager for Core token, provider keys, domain keys | Write secrets to logs or files |
| WIN-09 Tray and hotkey | Global push-to-talk, tray quit through the same shutdown path | Arm a mic without a visible indicator |
| WIN-10 WakeWord | Porcupine, default off, SHA-256-bound `.ppn` | Arm with empty or mismatched manifest |

## 5. Requirements

| ID | Stage | Requirement | Verification | Replaces |
|---|---|---|---|---|
| AR-WIN-001 | P0 | Wake-word resolver fails closed on empty or mismatched SHA-256 manifest | Unit + recorder-not-armed test | AR-016 part, FR-019 |
| AR-WIN-002 | P0 | Owned Core exits on app close; external Core survives | 10 open/close cycles with PID diff | AR-072, AC-010 |
| AR-WIN-003 | R1 | Audio, model and avatar work never block the UI thread | Typing stays responsive during slow STT/LLM/TTS | AR-071, NFR-003 |
| AR-WIN-004 | R1 | Mic indicator and avatar listening pose come from real capture state | Unplug and permission-loss tests | AR-023 |
| AR-WIN-005 | R1 | Interrupt flushes playback and avatar mouth within 300 ms p95 | Loopback timing trace | AR-017, MET-03 |
| AR-WIN-006 | R1 | Avatar loads offline from local package; no navigation outside it | Network-off launch; navigation-block test | new |
| AR-WIN-007 | R1 | Avatar capped at 60 fps, paused when minimized; under 15% GPU on reference laptop | 10-minute profile | new |
| AR-WIN-008 | R1 | Executor accepts only grants bound to action ID, canonical args, target, expiry, idempotency key | Forged, replayed, substituted grant tests | AR-033, AR-AI-028 |
| AR-WIN-009 | R1 | Spoken and visual "done" only after executor evidence says verified | False-success corpus 0/100 | FR-AI-007, AR-AI-007 |
| AR-WIN-010 | R1 | Global push-to-talk hotkey; no always-on mic by default | Hotkey test; default settings audit | FR-001 |
| AR-WIN-011 | R2 | UIA inspect redacts password/OTP fields; elevated or secure desktops fail closed | Redaction + locked desktop tests | AR-AI-019, AR-AI-020 |
| AR-WIN-012 | R1 | Domain pages read and write only through Core APIs | Static dependency guard | AR-009 |
| AR-WIN-013 | R4 | Installer bundles .NET runtime, Windows App SDK, Python runtime, Kernel library; no repo or `.venv` needed | Clean VM install, upgrade, uninstall | AR-078, FR-057 |
| AR-WIN-014 | R4 | Signed MSIX/installer, checksums, SBOM | CI release check | AR-079 |
| AR-WIN-015 | R1 | Separate mic and speaker mute; device selection; device-loss returns to safe idle | Device tests | FR-009, FR-010 |
| AR-WIN-016 | R2 | UIA executor uses fresh snapshot IDs and target window identity; stale snapshot denied | Stale/focus/DPI tests | AR-AI-016–018 |

## 6. Release gate (R1)

On real hardware: say "open Notepad" into a real mic; hear Kokoro answer while the avatar lip-syncs; Notepad opens with evidence in Activity; interrupt mid-sentence and audio and mouth stop together; say "I spent 12 dollars on lunch", confirm, and see it in Finance. Three recorded runs.
