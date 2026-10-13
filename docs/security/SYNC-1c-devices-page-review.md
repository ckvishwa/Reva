# SYNC-1c — security review of the Devices page

Date: 2026-10-12 · Scope: `desktop/src/Reva.Desktop/Devices/`, `ViewModels/DevicesViewModel.cs`, `Views/DevicesPage.*`, the QR library, the Finance conflict poll, the fixture generator and the UI smoke test. No new Core route and no new capability: the page only calls the six `/v1/devices/*` routes from SYNC-1b.

## Checked

| Area | Result |
|---|---|
| Token handling | The Core bearer token goes only into the `Authorization` header (`DevicesApiClient`), the same shared `HttpClient` and token provider as the other clients. Tests: never in a URL, body or error text; no token, no request. |
| The pairing QR is a one-time secret | It is drawn from the QR text into PNG bytes held in memory, then dropped when pairing ends, expires, is cancelled or the gateway is switched off. It is not written to disk, not stored as text on the view model (a reflection test checks every public property), not in any automation name. An expired code is removed from the screen at the deadline without waiting for Core. |
| Approval cannot be tricked into the wrong phone | Approve sends the six digits the user was shown; Core refuses unless they match the pairing it holds now (fingerprint mismatch, nothing to approve, kernel refused are all surfaced as plain errors and approve nothing). The user comparing the digits with the phone is the real control; the echo stops a stale or swapped session being approved by a click. |
| Untrusted text | A phone's display name (up to 80 characters) is shown in a `TextBlock`, which does not interpret markup. The name is attacker-chosen: it is shown with the digits, and the page says to approve only if the digits match. |
| Path handling | A device id from Core is escaped into the revoke URL; a test sends `../v1/domains/finance/export?x=1` and checks it stays inside `/v1/devices/{id}/revoke`. |
| Polling | Core is asked only while the Devices page is the open section (5 s idle, 1 s while a pairing is open); the Finance conflict poll (10 s) only while Finance is open and reads only the conflicts route. |
| No new power | No shell, no file access, no money movement. Revoke deletes nothing. The QR library (QRCoder 1.6.0, MIT) makes no network calls; only its managed PNG writer is used. |
| Real vault | The UI smoke test starts the app with `REVA_DOMAIN_KEYSTORE=memory`, a temp data directory and a loopback gateway; the in-memory guard (SYNC-1b fix F2) means it cannot reach Credential Manager. The fixture generator injects in-memory vaults. |

## Findings

None above Low. Notes:

* **L-1 (accepted).** If the Devices page is opened while Core already holds an open pairing whose QR this page never drew, the page cancels that pairing instead of showing a blank QR (the code cannot be recovered; it is shown only once). Only this page opens pairings, so this happens after a restart of the app during a pairing.
* **L-2 (accepted).** The first 16 hex digits of a key hash are shown for eyeballing; the full hash is what a phone pins and what Core checks. Showing more would not help a person compare.

## Mutation-style checks run

Each was applied, the Devices tests were run, and the change was reverted: leaving an expired QR on screen (2 tests failed), putting the token in the URL (2 failed), sending wrong digits on Approve (1 failed). All 70 Devices tests pass again after the revert.
