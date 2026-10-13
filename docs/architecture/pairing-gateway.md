# Pairing gateway (SYNC-1b)

Spec: ARD-500 sections 2 and 3, ARD-300 AR-CORE-007, ADR-008, ADR-009 (loopback Core + distinct pairing gateway), ADR-010 (peer authentication, QR pairing).
Code: `reva_core/gateway/`. Tests: `tests/gateway/`. Contract: `contracts/pairing-qr.schema.json`.

## Shape

```
phone ──TLS (pinned key)──► gateway app  ──► GatewayService ──► Kernel (finance) + Core DB (devices, device_grants)
                            127.0.0.1 never; one LAN address; only while the Devices setting is on

WinUI / tools ──loopback + Core bearer token──► Core API /v1/devices/*  ──► GatewayManager (same process)
```

* The gateway is its own FastAPI app on its own socket and thread inside the Core process. It shares no router, dependency, exception handler or token with the Core API. The Core bearer token is never sent to a phone and never accepted by the gateway (a test greps the gateway sources for it).
* **Off by default.** `PATCH /v1/devices/gateway {"enabled": true}` is the Devices setting. It is remembered in `<data_dir>/gateway/settings.json`. Turning it off closes the socket. If the LAN address is missing or the port is busy, the setting stays off and the reason is returned.
* **Bind.** One interface address (`REVA_GATEWAY_HOST`, default: the machine's LAN IPv4), port `REVA_GATEWAY_PORT` (default 47821, 0 = any). Never the wildcard. `GET /v1/devices` reports `host`, `port`, `listening` and the TLS key hash.
* **Allowlist.** `POST /pair/start`, `/pair/complete`, `/sync/push`, `/sync/pull`, `/sync/ack`. Everything else is a bare 404/405 (`{"error": ...}`); no docs, no OpenAPI, no trailing-slash redirects. Body limit 9 MB; JSON only.

## Keys

| Key | Where | Used for |
|---|---|---|
| Gateway TLS key (P-256) | Credential Manager `reva.gateway.tls` | TLS server identity. Phones pin the SHA-256 of its public key. |
| PC device key (P-256) | Credential Manager `reva.gateway.device` | Signs Kernel events and gateway responses (Kernel `DeviceSigner`). |
| Phone device key (P-256) | Android Keystore (SYNC-1d) | Signs requests and the phone's Kernel events. |

Private scalars are 32 bytes in the vault and nowhere else. The TLS server needs files, so an *encrypted* PEM key (random one-time password) and the public certificate are written for the instant the server loads them, then deleted. Tests check no private key text or scalar is in the data directory or database.

## Pairing (AR-DATA-001, AR-AND-007)

1. User turns the gateway on and opens pairing in Devices: `POST /v1/devices/pairing`. A random code is made (only its hash is kept; 120 s; one session at a time; opening again cancels the old one). The QR text is `REVA-PAIR1:` + base64url of `{v, host, port, code, gw, exp}`.
2. The phone scans, **checks the TLS public key against `gw`**, and calls `/pair/start` with the code, its public key, its Kernel device id and a signature over the code (proof of possession). The code is consumed: a second use is `code_used`. Five wrong codes lock the session.
3. Both screens show the same 6 digits: SHA-256 over the gateway key hash, the phone public key and the session id, reduced to 6 digits. If anyone swapped the phone key on the way, the digits differ.
4. The user approves on the PC by sending the digits back (`POST /v1/devices/pairing/approve {"fingerprint": "123456"}`); a mismatch is refused. Approval creates the `devices` + `device_grants` rows and registers the phone in the Kernel as a finance-only peer. If the Kernel refuses (for example the phone claims another device's Kernel id with a different key), the grant is removed again.
5. The phone polls `/pair/complete` (signed) and receives its Core device id, the PC's signing key, and the PC's Kernel device id. It registers the PC as its peer.

## Every request after pairing (AR-DATA-002, -004, -007)

Headers: `X-Reva-Device`, `X-Reva-Ts`, `X-Reva-Nonce`, `X-Reva-Sig` = ECDSA P-256 over method, path, timestamp, nonce, SHA-256 of the body and the gateway key hash. The gateway checks, in order: rate limit, device id shape, timestamp within 120 s, nonce shape, **the grant in the database is active**, nonce not seen, signature. Every failure is the same `401 {"error":"unauthorized"}`; the reason goes to the security log (with the device id when known, never signatures, codes or keys). Authenticated responses carry `X-Reva-Resp-Sig`, the PC's signature over nonce, status and body hash.

**Revocation is atomic.** Admission and the Kernel call run under one lock, and `revoke` takes that lock: when `revoke` returns, no earlier request is still running and no later one is admitted. The Kernel peer is revoked in the same step and refuses on its own as well.

**Re-pair after revoke** gives a new grant. The Kernel resets both cursors for that peer to zero when a revoked peer is registered again (and `reset_peer_cursors` exists for a phone that was wiped), so the next exchange starts from the beginning of the log; apply is idempotent, so the replay is harmless. The phone does the same for its peer entry for the PC (revoke, then register).

## Sync (AR-DATA-010, -011, -015)

* `push`: the phone's signed events go to `sync_apply`. The answer lists applied, duplicates and amount conflicts; `ack_cursor` is the phone's log position the PC now holds.
* `pull`: `sync_export` for that phone after its cursor, filtered as below, plus `directory`. The phone registers directory entries, applies, then calls `ack` with `cursor_to`.
* `ack`: moves the PC's cursor for that phone forward (never back, never beyond the PC's log).
* The finance **sync** privacy switch is read on every push and pull (send and receive). Domains other than finance are `out_of_scope`.

## Third-device forwarding: decision

*Send the key directory, scoped to the grant; withhold anything else.*

* The PC forwards an event from device X to phone P only when X is the PC itself or another **active** phone with a finance grant, and every pull response carries the public key and label of each such X that appears in the batch (`directory`). P registers them before applying, so P can verify the signatures itself. P never trusts the PC's word about an event, only about who the other devices are, and the PC is the device P's user approved.
* Events whose origin is not in that set (a revoked phone, or any origin the PC cannot name) are **withheld**: they stay on the PC, are counted in `withheld`, and the cursor still moves, so one unknown origin cannot block a phone.
* Consequence: a revoked phone's earlier events do not reach other phones after the revoke. Chosen because forwarding data from a device the user has just distrusted is the worse failure. If the user wants them, re-pairing resets cursors.
* The directory never contains the requesting phone and never contains a device without a finance grant.

## Not in this slice

WinUI Devices page and the QR image (SYNC-1c); Android scanner, Keystore signer, sync client and conflict banners (SYNC-1d); relay transport (R3). The Core API exposes everything the Devices page needs.
