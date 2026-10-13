# ARD-500 — Data, Sync, Relay and Security v2.0

**Document ID:** REVA-ARD-500 · **Version:** 2.0.6 · **Date:** 2026-10-12 · **Status:** Proposed
**Replaces:** ARD v1 §6, §7, §13. **Decisions:** ADR-006, ADR-008, ADR-009, ADR-010, ADR-014, ADR-015, ADR-028, ADR-031, ADR-032.

## 1. Storage map

| Store | Device | Engine | Holds | Key |
|---|---|---|---|---|
| Core DB | PC | SQLite WAL | conversations, messages, sessions, actions, audit, devices, sync cursors | plaintext file protected by OS profile; secrets never inside |
| Domain files | PC + phone | SQLCipher (one file per domain, via Kernel) | Memory, Finance, Health, Coach, Career, Learn, Cyber, Personal + their event logs + outbox | per-domain key in DPAPI/Credential Manager or Android Keystore |
| UI cache | phone | Room | conversation cache, session state | Keystore-backed where sensitive |
| Embeddings | PC (phone optional) | inside Memory domain file | vectors; rebuildable, not synced | domain key |
| Relay | cloud (opt-in) | Supabase Postgres/Storage | ciphertext events + routing metadata | relay never holds keys |

## 2. Identity and pairing (v1 §6 kept)

PC shows a short-lived QR with a one-time session and the gateway key hash; the phone scans, opens TLS, both show a matching code, the PC user approves; each side records a scoped device grant; mutual auth by signed challenge with device keys. Revocation is checked atomically before every dispatch. The phone never receives the Core bearer token. LAN only for R2.

**Implementation note (2.0.6, SYNC-1b):** the gateway is a separate ASGI app on its own TLS socket inside the Core process, off until the Devices setting turns it on, bound to one LAN address and never the loopback Core port. Five POST routes only (`/pair/start`, `/pair/complete`, `/sync/push`, `/sync/pull`, `/sync/ack`). The phone pins the SHA-256 of the gateway TLS public key from the QR (`contracts/pairing-qr.schema.json`); the QR carries a 120-second one-time code; both screens show a 6-digit fingerprint and approval on the PC must echo it. After pairing every request is signed by the phone key and re-checked against the database; revocation takes the same lock as dispatch. The PC forwards a third device's events only with that device's public key in the same response and withholds events from revoked devices. Details, decisions and threat model: `docs/architecture/pairing-gateway.md`, `docs/security/SYNC-1b-gateway-review.md`.

## 3. Sync

- **Unit:** a Kernel domain event (`08_CONTRACTS/domain-event.schema.json`) with `event_id`, `domain`, `aggregate_id`, `version`, `origin_device_id`, `lamport`, `kind`, `payload`, `tombstone`.
- **Outbox:** every local write appends to the domain's outbox; batches (`sync-batch.schema.json`) are sent, acknowledged by cursor, and retried idempotently.
- **Apply:** by `event_id` (duplicate = no-op); ordering by (`aggregate_id`, `version`, `lamport`, `origin_device_id`); tombstones beat any older version; never wall-clock last-write-wins (AR-057).
- **Conflicts:** concurrent edits to the same field produce a conflict record shown to the user for Finance amounts and Health measurements; other fields merge per field with deterministic tie-break.
- **Scopes:** per-domain sync switch and device list enforced on send **and** receive (AR-058).
- **Implementation note (2.0.5):** events are signed with a P-256 device key held in the OS vault (Credential Manager, Android Keystore). The Kernel verifies against the peer's registered public key, rejects a whole batch if any event fails, and keeps per-peer cursors. Ed25519 was not used because Android Keystore supports it only from API 33 (minSdk is 31). Details: ARD-700 section 2.3. The pairing gateway, QR and approval flow (S13) are still to come.
- **Never synced:** raw audio, action commands (outcomes only, as information), embeddings (rebuilt), keys.

### Transport 1 — LAN direct (R2 default)

Through the pairing gateway on the PC, TLS + device keys. The phone exchanges batches with the PC; the PC is a peer, not a server for other peers.

### Transport 2 — Relay (R3, opt-in)

- Each paired device group shares a **sync group key** created on the PC at pairing and delivered to the phone inside the paired TLS channel.
- Events are encrypted on the device with the group key (authenticated encryption) before upload. The relay stores `{group_id, device_id, seq, ciphertext, nonce, created_at}`.
- Supabase auth is only an access control for the mailbox; it cannot read content.
- Key loss = re-pair; there is no cloud key escrow in 2.0.
- **Label rule:** the UI says "encrypted on your devices before upload". The words "end-to-end encrypted" may be used only after AR-DATA-014 passes.

## 4. Threat model (v1 table kept, additions)

| Threat | Boundary | Control | Proof |
|---|---|---|---|
| Stolen phone with domain data | device → attacker | SQLCipher + Keystore key; OS lock | file inspection, no key on disk |
| Relay operator or breach reads data | relay | client-side encryption, no keys on server | relay dump test shows only ciphertext |
| Malicious peer event (forged delete) | sync apply | events signed by device key; scope check; revoked device rejected | forged-event suite |
| Hosted model leaks Finance/Health | Core/brain → provider | per-domain consent filter, minimal fields | network capture |
| Imported CSV injection | import → Kernel | strict parsing, formula-prefix neutralizing on export | malicious CSV fixture |
| Health misinformation | planner → user | safety policy + eval (ARD-700 AR-DOM-007) | health safety eval |
| Test run corrupts real data | tests → data dir | env guard (AR-CORE-004) | guard test |

## 5. Requirements

| ID | Stage | Requirement | Verification | Replaces |
|---|---|---|---|---|
| AR-DATA-001 | R2 | Pairing key agreement authenticated by user-approved QR/fingerprint | MITM/wrong peer | AR-041 |
| AR-DATA-002 | R2 | Gateway TLS + device auth for every paired connection | Unauthenticated access test | AR-042 |
| AR-DATA-003 | R2 | Grants scoped to approved actions and data classes | Escalation tests | AR-043 |
| AR-DATA-004 | R2 | Revocation checked atomically before dispatch | Stale token/replay | AR-044 |
| AR-DATA-005 | R2 | Gateway binds to LAN only when enabled; reports interface/port | Port scan | AR-045 |
| AR-DATA-006 | R2 | No remote caller reaches unrestricted `/v1/*` | Allowlist contract | AR-046, AR-036 |
| AR-DATA-007 | R3 | Authenticated resume tokens; duplicate events dropped | Packet-loss test | AR-047 |
| AR-DATA-008 | R3 | Credential rotation and device-key compromise recovery | Rotation/revoke test | AR-048 |
| AR-DATA-009 | R4 | Security logs record requesting device without secrets | Audit format | AR-049 |
| AR-DATA-010 | R2 | Sync idempotent with durable outbox acknowledgment | Replay/reorder | AR-056 |
| AR-DATA-011 | R2 | Tombstones beat older versions; no wall-clock-only rule | Skew/offline | AR-057 |
| AR-DATA-012 | R3 | Per-domain scopes enforced on send and receive | Scope tests | AR-058 |
| AR-DATA-013 | R3 | Relay stores only ciphertext + routing metadata | Relay dump inspection | FR-048 |
| AR-DATA-014 | R3 | Relay key handling, recovery and threat model pass adversarial tests before any E2EE label | External or QA-led adversarial review | ARD v1 §15 |
| AR-DATA-015 | R2 | Synced events signed by origin device key; unsigned or revoked rejected | Forged-event suite | new |
| AR-DATA-016 | R4 | Wipe and unpair clear credentials, queues, embeddings and caches | Inspection | AR-060, FR-060 |
| AR-DATA-017 | R4 | Export covers conversations, memory and all domains with documented omissions | Round-trip | AR-059, FR-047 |
| AR-DATA-018 | R1 | Temporary audio and files have bounded lifetime | Cleanup tests | AR-053 |
| AR-DATA-019 | R1 | No raw mic bytes in logs | Log scan | AR-073 |
| AR-DATA-020 | R4 | Security signoff covers MASVS, transport, policy, secrets, privacy | Signed checklist | AR-080 |
