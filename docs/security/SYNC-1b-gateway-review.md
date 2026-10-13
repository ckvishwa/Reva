# SYNC-1b — security review of the pairing gateway

Date: 2026-10-12 · Scope: `reva_core/gateway/`, `/v1/devices/*`, migration 0003, Kernel peer cursor reset, `contracts/pairing-qr.schema.json` · Method: security-review checklist (scope, STRIDE per component, auth-flow trace, manual code review, then tests written to fail on each finding).

## Threat model (STRIDE, short form)

| Threat | Component | Control | Test |
|---|---|---|---|
| Spoofing: fake gateway steals the code | pairing QR | Phone pins the TLS key hash from the QR before sending anything | `test_a_phone_refuses_a_gateway_whose_tls_key_is_not_in_the_qr` |
| Spoofing: unknown phone syncs | every sync request | Device id + ECDSA signature over method, path, time, nonce, body hash, gateway hash | `test_no_credentials_no_service`, `test_garbage_credentials_...`, `test_another_phones_signature_...` |
| Spoofing: key swap during pairing | pairing | 6-digit fingerprint over gateway key, phone key and session; approval must echo the digits | `test_a_man_in_the_middle_who_swaps_the_phone_key_is_caught_by_the_digits` |
| Spoofing: phone claims another phone's Kernel identity | approval | Kernel refuses a different key for an active peer; the grant is rolled back | `test_a_phone_cannot_claim_another_devices_kernel_identity` |
| Tampering: edited events or body | push | Request signature covers the body; Kernel verifies every event signature; whole batch rejected | `test_a_body_changed_after_signing_...`, `test_events_that_fail_kernel_verification_...` |
| Tampering: forged answer to the phone | responses | `X-Reva-Resp-Sig` by the PC device key | `test_an_answer_not_signed_by_the_paired_pc_...` |
| Repudiation | all | Security log: requesting device, reason; never keys, codes, signatures | `test_denied_requests_are_logged_...`, `test_pairing_activity_is_in_the_security_log_...` |
| Information disclosure: private keys | TLS key, device key | Vault only; encrypted temp PEM deleted after load; scan of data dir finds none | `test_no_private_key_is_left_on_disk_...` |
| Information disclosure: errors | all | One `401 unauthorized` for every admission failure; bare `{"error": code}` elsewhere | `test_an_unknown_device_and_a_revoked_one_look_the_same_...`, `test_no_route_outside_the_allowlist_answers` |
| DoS | listener | Off by default; pre-auth body cap 16 KB (pairing) / admission before the 9 MB body; per-address failure limit; code lock after 5 bad tries | `test_oversized_...`, `test_repeated_failures_...`, `test_guessing_codes_locks_the_session` |
| Elevation: Core API reached from the LAN | listener | Separate app and socket; five routes; Core bearer token never read or accepted | `test_only_the_five_allowlisted_routes_exist`, `test_the_core_bearer_token_opens_nothing_on_the_gateway`, source scan |
| Elevation: revoked phone keeps working | dispatch | Admission and the Kernel call share a lock with `revoke`; Kernel refuses too | `test_a_request_in_flight_finishes_before_revoke_returns`, `test_revocation_between_admission_steps_...` |

## Findings and fixes

| ID | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| G-1 | High | `PairingManager` had no lock: two phones starting with the same code at once could both pass the "open" check, and the second would overwrite the first. A one-time code was not atomically one-time. | One re-entrant lock around every public method. | `test_two_phones_racing_for_one_code_cannot_both_win` (fails with the lock removed) |
| G-2 | Medium | The gateway read up to 9 MB of body before it knew who was asking. | `precheck` (rate limit, device, time, nonce, active grant) runs before the body is read; pairing bodies are capped at 16 KB. | `test_oversized_and_wrongly_typed_bodies_are_refused_before_parsing` |
| G-3 | Medium | `/sync/push/` answered with a redirect: a near-miss path was served. | `redirect_slashes=False`. | `test_no_route_outside_the_allowlist_answers` |
| G-4 | Low | `REVA_GATEWAY_HOST=0.0.0.0` (or `::`) would have bound every interface. | Wildcards are refused with a clear error. | `test_the_gateway_refuses_to_listen_on_every_interface` |
| G-5 | Low | A deeply nested JSON body raised `RecursionError`, a 500. | Parsed as a 400. | `test_oversized_..._before_parsing` (deep nesting case) |
| G-6 | Medium | Mutation check: removing the in-dispatch "grant is active" check was not caught, because the earlier pre-check made it redundant in tests. | Test that revokes between pre-check and dispatch. | `test_revocation_between_admission_steps_still_stops_the_request` |

Mutation checks run (each makes at least one test fail): revoked grants admitted, nonce replay allowed, approval ignoring the digits, signature not verified, pairing lock removed.

## Auth-flow trace

QR (code, key hash, expiry) → TLS with key pin → `pair/start` (code, phone key, proof of possession) → code consumed, digits derived on both sides → user compares and approves on the PC (loopback API, Core bearer token) → grant + finance-only Kernel peer → `pair/complete` poll (signed, fresh nonce) → phone registers the PC → every later request signed and re-checked against the database and the Kernel.

## Residual risks (accepted, with reasons)

1. **Audit growth.** Each denied request writes a log row. One address is limited to 20 failures a minute, but many addresses are not limited together. LAN-only and off by default; add log rotation with the Devices page (SYNC-1c).
2. **Pairing can be locked by a LAN attacker** who has seen the QR and guesses five times. The user opens a new pairing. No data is exposed.
3. **6-digit fingerprint.** It is a second factor after the QR code, not the only secret; a key swap needs the live code and still matches the user's eyes only 1 in a million.
4. **Clock.** Requests are valid for 2 minutes either side; a phone with a wrong clock is refused until its time is fixed.
5. **Key rotation.** Removing the Credential Manager entry `reva.gateway.tls` creates a new gateway key; every phone's pin then fails and each must pair again. This is intended (AR-DATA-008 covers rotation properly in R3).
6. **IP changes.** The QR holds an address, not a name; if the PC's address changes the phone must scan again (no discovery in this slice).
7. **Windows Firewall.** The first time the listener binds, Windows may ask to allow the app on the private network. NEEDS_HARDWARE step.
8. **Environment.** On this development PC, creating asyncio event loops very rarely hangs inside Python's Windows loopback socket pair (reproduced with a 10-line script, no REVA code). The gateway start retries a fresh server thread; test runs on this PC may need a re-run. Not seen on other machines; CI runs Linux for Python.
9. **Phone side not built.** The Android scanner, Keystore signer and client (SYNC-1d) are where certificate pinning and the response-signature check will live; their tests are the Python phone simulator's counterparts.
