# Android: asking the PC to act (C2c, first part)

PC side and rules: `docs/architecture/phone-actions.md` (C2a/C2b). This file is the phone's half.

## Parts (`android/app/src/main/java/app/reva/pcrequests/`)

| File | What it does |
|---|---|
| `PcPhrases.kt` | "Open Calculator on my PC" / "close Spotify on my laptop" become a request. Only a sentence that names the PC counts. The app must be exactly a canonical name or an approved alias (same words as the PC's resolver, checked against `rules-cases.json` written by the Python resolver); a guess is never sent |
| `PcGateway.kt` | `SignedPcGateway`: `POST /actions/propose` and `/actions/status` signed with the Keystore device key over method, path, timestamp, nonce, body hash and the pinned gateway key (same wire format as sync). The PC's answer must carry a signature that verifies against the PC's signing key for this request's nonce, or it is not believed |
| `PcRequestTracker.kt` | One request from "asked" to what really happened (below) |
| `language/PolicyReplies.kt` | Runs the shared `authorize()` first (a close is allowed to go only because it will wait for a click on the PC), then hands the request to the tracker and says only "Asking your PC to ..." |
| `ui/talk/TalkScreen.kt` | A card above the status line: what was asked, what the PC is doing, "Stop waiting" or "Dismiss" |

## Rules the tests pin down

- **One id, one time.** A request has one `request_id` and one `issued_at` for its whole life. A dropped connection means "I do not know whether it landed", so the same request is sent again with the same id; the PC treats that as one action. Retries cannot stretch the PC's 120 second window: the phone stops retrying at 110 seconds and says it does not know.
- **No false success.** "Done" appears only when the PC reports `verified`, in the PC's own words. Granted, observed and attempted are "working on it". A status the phone does not know, a `verified` with no words, a lost connection and giving up are all "I don't know", never success. No sentence the phone writes while working contains a success word (checked against the PC's list).
- **The phone never approves.** A close waits for a click on the PC; the phone shows "Waiting for you on your PC: Close Spotify? Approve it on the PC." and can only stop waiting. Stopping says the PC may still act.
- **Refusals are not retried and are said plainly**: not allowed on this PC ("Allow it on the PC, in Devices"), not allowed from a phone, revoked ("Pair again"), too late, too many waiting, PC not ready, unknown app.
- **One request at a time**, so one tap cannot ask twice; a finished request stays on screen until dismissed.
- **A forged, unsigned, or replayed answer is never believed** (wrong key, no signature, a signature for another nonce, malformed signature).

## Not here yet

Phone-side actions (alarm, reminder, calendar, share, open a phone app) are the second part of C2c. Reconnecting after the PC restarts mid-request relies on the PC's status record; a request is lost from the phone's view if the app is killed (the PC still has it and ends it `unknown` when it expires).
