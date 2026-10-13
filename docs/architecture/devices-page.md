# Devices page (SYNC-1c)

The Windows side of pairing: a page in the left nav that drives the loopback Core API from SYNC-1b (`/v1/devices/*`). Design: `docs/architecture/pairing-gateway.md`. Code: `desktop/src/Reva.Desktop/Devices/`, `ViewModels/DevicesViewModel.cs`, `Views/DevicesPage.xaml`.

## What it does

* **Gateway switch.** Off by default. The switch follows what Core reports, not what was clicked: if Core cannot start the listener (no LAN address, port busy), the switch stays off and Core's reason is shown. When on, the page shows `Listening on <host>:<port>` and the first 16 hex digits of the gateway TLS key hash (the value a phone pins).
* **Pair a phone.** Opens a pairing and draws the QR code (dark on a light tile, with a quiet zone) with a two-minute countdown and a Cancel button. The QR text is turned into image bytes in memory and dropped when the pairing ends, expires, is cancelled or the gateway is switched off; it is never written to disk or kept as text on the view model (a test checks this). When the countdown reaches zero the QR is removed at once, without waiting for Core.
* **Approval.** When a phone has scanned, the QR is replaced by the phone's name and the six digits in large type. **Approve** sends the digits back to Core, which refuses unless they match the pairing it holds; **Deny** turns the phone away. Outcomes (paired, denied, expired, too many wrong codes, cancelled) stay on screen until dismissed.
* **Paired phones.** Name, Active/Revoked, scope ("Finance only"), last seen, pairing time and the first 16 hex digits of the phone key hash. **Revoke** asks for confirmation first ("A revoked phone can no longer sync. Its data already on this PC stays.").
* **Polling.** Core is asked only while the Devices page is the open section: every 5 seconds, every second while a pairing is on screen. Leaving the page stops the timer.
* **Sync conflicts.** The existing Finance banner reads `GET /v1/domains/finance/conflicts`, which is where Kernel conflicts from phone sync appear. The Finance page now re-reads only that banner every 10 seconds while it is open, so a phone that syncs while the page is open raises the banner without a manual reload.

## Third-party library: QR code (tech-stack-eval note)

Need: draw an offline QR code from ~200 bytes of text in a WinUI app. No network, no camera, no native dependency.

| Option | Verdict |
|---|---|
| **QRCoder 1.6.0** (MIT, https://github.com/codebude/QRCoder) | **Chosen.** One small managed package, `PngByteQRCode` writes a PNG to a byte array with no System.Drawing use, ECC levels, active maintenance, widely used. |
| ZXing.Net | Larger, mixes encoder and decoder, more surface than needed. |
| Hand-written encoder | A QR encoder (Reed-Solomon, masking, version tables) is easy to get subtly wrong; a wrong QR looks fine and fails on a phone. Not worth owning. |

* Pinned in `Reva.Desktop.csproj` (`QRCoder` 1.6.0, lock files updated). Licence MIT, recorded here.
* Its package metadata lists `System.Drawing.Common` 6.0.0 as a dependency for some target frameworks. REVA calls only the managed PNG writer and never touches drawing APIs.
* QRCoder makes no network calls; nothing leaves the PC. The payload is the pairing QR text defined by `contracts/pairing-qr.schema.json`.

## Tests

* Unit (`desktop/tests/Reva.Desktop.Tests/Devices/`): API client routes, bodies, bearer token, error mapping, token never in URL/body/error; contract tests over fixtures captured from the real Core (`tools/desktop/generate_devices_fixtures.py`, kept current by `tests/contract/test_devices_ui_fixtures.py`); QR encoder; view-model state machine (off, listening, failed start, QR open, countdown and expiry, pending, approved, denied, locked, cancelled, Core losing the session, stale open pairing, revoke, newest refresh wins, double click).
* FlaUI smoke (`DevicesSmokeTests`, opt-in `REVA_RUN_UI_TESTS=1`): the real window, the real Core, the real gateway on loopback with an in-memory vault in a temp directory. A second, independent implementation of the phone (C#, `GatewayPhone.cs`) pins the TLS key from the QR, computes the six digits itself, completes pairing, syncs, is revoked and is refused. If the C# phone and the Python gateway ever disagree about a signed string or the fingerprint, this test fails.
* The window screenshots for review come from `PrintWindow` of the app's own handle: screen-rectangle captures through UI Automation are cropped on scaled displays.

## Not in this slice

The Android Devices screen, scanner and sync client (SYNC-1d). Any LAN-address picker or friendly PC name in the QR (the QR carries the address Core detected).
