# Android pairing and LAN sync (SYNC-1d)

Spec: ARD-500 sections 2 and 3, ARD-200 AR-AND-007. PC side: `docs/architecture/pairing-gateway.md`. Code: `android/app/src/main/java/app/reva/sync/` and `ui/devices/`.

## What the phone does

1. **Device key.** A P-256 key pair in the Android Keystore (alias `reva.device.signing`, StrongBox when present, software-backed Keystore otherwise; `StrongBoxUnavailableException` and `ProviderException` both fall back). It implements the Kernel's `DeviceSigner`: SPKI DER public key, DER `SHA256withECDSA`. P-256 because Keystore supports Ed25519 only from API 33 and the app supports API 31.
2. **Scan.** More, Devices, "Scan the code". CameraX shows the preview and ZXing decodes frames on the phone. The code text can also be pasted. The text is `REVA-PAIR1:` + base64url JSON (`contracts/pairing-qr.schema.json`); expired codes and any host that is not on the phone's own network (private IPv4, link-local, loopback, IPv6 unique-local or link-local, `localhost`, `*.local`) are refused before any connection.
3. **Pin.** The HTTPS client (`PinnedHttpsTransport`) accepts exactly one TLS key: the SHA-256 of the SPKI named in the QR code. Any other key fails the handshake before a request byte is sent. It is not a trust-all manager. The host-name check is switched off for that one connection because the pinned key is the identity.
4. **Pair.** `pair/start` with the code, the phone's public key, its Kernel device id and a signature over the code (proof of possession). The phone computes the 6 digits itself (`GatewayProtocol.fingerprint`, identical to the PC's) and shows them large. The user compares them with the PC and approves there. The phone polls `pair/complete` (signed, fresh nonce) and, when approved, registers the PC as its only Kernel peer (revoke then register, so a re-pair resets the cursors), then syncs once.
5. **Sync.** `push` the phone's signed events (ack the PC's `ack_cursor`), then `pull`: register any key-directory entries, `sync_apply`, `ack`. Every request carries the device id, time, a random nonce and a signature over method, path, time, nonce, body hash and the gateway hash. Every answer must carry a valid `X-Reva-Resp-Sig` from the PC's signing key, or nothing is applied.
6. **Conflicts.** The Finance tab reads the Kernel's unresolved `conflicts`. The banner offers "Keep mine" / "Keep PC's", which write `conflict.resolve`; after the next sync both devices agree.
7. **Forget.** Revokes the PC peer in the phone's Kernel and deletes the pairing record. Removing the phone on the PC side is done on the PC (Revoke).

## What is stored where

| Item | Place | Backup |
|---|---|---|
| Domain files, wrapped Kernel key | `noBackupFilesDir/domains`, `keys` | excluded |
| Paired-PC record (host, port, PC key hash, PC signing public key, ids, last sync) | `noBackupFilesDir/sync/paired_pc.json` | excluded (`root/no_backup`) |
| Device private key | Android Keystore | never leaves it |

The pairing record holds public material only. A test checks that the file mentions no secret.

## Permissions (exact set, checked by `ManifestTest` on the merged manifest)

* `INTERNET`: HTTPS to the paired PC on the local network. Cleartext is refused (`usesCleartextTraffic=false`, network security config), and no server of ours is involved.
* `CAMERA`: to read the pairing QR code, asked for when the user taps Scan. The camera is optional hardware.
* Not needed: `ACCESS_NETWORK_STATE`, location, Wi-Fi state. The "local network" permission that Android introduces for apps targeting API 37+ does not apply at targetSdk 36; revisit when targetSdk moves.
* Never present: `QUERY_ALL_PACKAGES`, any AccessibilityService.

## QR scanning: library choice

| Option | Play services | License | Size | Verdict |
|---|---|---|---|---|
| CameraX + ZXing core | no | Apache-2.0 both | about 0.6 MB for ZXing core | chosen: fully on-device, no Google service, no model download |
| CameraX + ML Kit barcode (bundled) | no | proprietary terms + Apache-2.0 | about 2.5 MB plus model | works offline but heavier and licence-encumbered |
| ML Kit unbundled / Google code scanner | yes | proprietary | small | needs Play services and a download: rejected |

Versions: CameraX 1.4.2, ZXing core 3.5.3. The decoded frame is never stored or sent.

## Tests

* JVM: `GatewayProtocolTest` checks every signed string, the fingerprint, base64url, QR parsing and an ECDSA signature against `protocol_vectors.json`, written from `reva_core/gateway/protocol.py` by `python tools/android/gen_protocol_vectors.py` (`--check` verifies it is current). `PairedPcStoreTest`, `DevicesViewModelTest`, `FinanceConflictsTest`, `ManifestTest`.
* Instrumented (API 31 and 36): `KeystoreSignerInstrumentedTest` (Keystore signatures verify in the Kernel, forged batch rejected), `SyncComposeTest` (Devices screen and conflict banner), `SyncE2eTest`.
* End to end: `python tools/android/sync_e2e.py --serial <emulator>` runs a real Core and gateway on the host (temp data, in-memory vaults), reaches it through `adb reverse`, and drives `SyncE2eTest` on the device: pair with the digits compared and approved over the Core API, an expense on each side, sync, both Kernels identical, revoke, the next sync refused. Install `app-debug.apk` and `app-debug-androidTest.apk` (built with `-Preva.uiTests=true`) first. This suite does not use airplane mode, on purpose; `KernelConformanceTest` is still the airplane-mode domain suite.
* Run the whole instrumented suite with `adb shell am instrument -w -e requireAirplane true app.reva.android.test/androidx.test.runner.AndroidJUnitRunner` after `adb shell cmd connectivity airplane-mode enable`. (`connectedDebugAndroidTest` through Gradle dropped the emulator connection on this PC, so the suite was run with `am instrument`.)
