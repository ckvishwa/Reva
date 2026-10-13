# SYNC-1d: security review of the Android pairing and sync client

Date: 2026-10-12 · Scope: `android/app/src/main/java/app/reva/sync/`, `ui/devices/`, manifest, network security config, backup rules, `tools/android/sync_e2e.py`. Method: security-review checklist on the diff, then a test for every finding.

| Threat | Control | Proof |
|---|---|---|
| Fake PC on the LAN | TLS key pinned from the QR; no trust-all manager; wrong key fails the handshake before any request bytes | `PinnedHttpsTransport`, instrumented e2e; PC-side `test_a_phone_refuses_a_gateway_whose_tls_key_is_not_in_the_qr` |
| Hostile QR code pointing at the internet | host must be loopback, private, link-local, `localhost` or `*.local`; expired codes refused | `only_addresses_on_the_local_network_are_accepted_for_pairing` |
| Key swap while pairing | the phone computes the 6 digits itself from the pinned key, its own key and the session; the user compares with the PC | vector test for the digits; `sync_e2e` checks PC and phone digits are equal |
| Forged or replayed answers | `X-Reva-Resp-Sig` checked before JSON is read or events applied; fresh random nonce per request | `SyncEngine.signed` |
| Forged events from the PC | Kernel verifies each event against the registered PC key; whole batch refused | `KeystoreSignerInstrumentedTest`, Kernel `sync_peers` tests |
| Device key theft | private key in the Keystore, never exported; backup excludes everything | `KernelConformanceTest` (no_backup), manifest test |
| Over-broad permissions | exactly INTERNET + CAMERA; cleartext refused; no QUERY_ALL_PACKAGES, no AccessibilityService | `ManifestTest` on the merged manifest; `aapt2 dump permissions` on the APK |
| Secrets in the pairing record or logs | public material only; no `Log` calls in the sync package | `PairedPcStoreTest.the_record_holds_public_material_only` |
| Camera misuse | permission asked at Scan; frames decoded in memory only; optional hardware | `QrScanner` |

## Findings fixed during the slice

* Pairing code could point the phone at any host (information leak: phone public key, Kernel device id and name would go to an attacker's server that supplies its own pin). Fixed with the local-network host rule.
* Re-pairing must restart the cursors: the phone revokes then registers the PC peer.
* Poll loop has a client-side limit (150 s) and cancels the session.

## Residual risks

1. **Name and key sent to a LAN attacker.** A hostile QR on the user's own network could still receive the phone's public key and name before the user sees a mismatch; no secret is in that data and nothing is granted without the PC approval.
2. **Clock.** Requests are valid for two minutes either side; a badly set phone clock gets "no longer accepts this phone". Fix the time.
3. **Forget is local.** It stops syncing on the phone; the PC keeps the grant until Revoke is used there. The screen says so.
4. **No unlocked-device requirement** on the Keystore key (background sync while locked is a goal; same decision as the AES wrapper).
5. **Emulator-only proof.** The pairing was proven on two emulators against the real gateway, not yet on a phone over Wi-Fi (NEEDS_HARDWARE).
