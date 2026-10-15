# Windows executor, Apps & Actions, Activity, confirm card (B3c)

Code: `desktop/src/Reva.Desktop/Actions/`, `reva_core/policy/`, `reva_core/domains/voice_expense.py`.

## How "open VS Code" runs

1. The voice turn routes to `windows.app.open` (B3b). The broker signs a grant and the session sends an `action.proposed` event with the signed order.
2. `ActionCoordinator` hands the order to `AppActionExecutor`. **Before anything starts** it verifies the grant with the Core's public key (`grant_public_key.pem` in the data folder): signature, expiry, that it is for this capability, these canonical arguments, this PC and this owner, and that its idempotency key was not used before. A forged, replayed, expired or substituted grant is refused and nothing launches (`AppActionExecutorTests`; the same signed vectors run in Python and C#: `tests/fixtures/grant_vectors.json`).
3. The launch target is looked up by app key in `AppTargetStore`: fixed literals for the built-in apps, the owner's approved Start Menu shortcut for others. A request can never name a program or a path.
4. Open is `verified` only if a visible top-level window of that app **appeared** (or its already-open window came to the front). A process with no window within 8 s is `unknown`; nothing running at all is `failed`.
5. Close asks each window to close (no kill). It is `verified` only when every process of the app is gone; a window that stays (a save prompt) is `unknown`.
6. The executor reports status + evidence (`pid:N window:0xH`, `pids:N,M exited`). The Core accepts `verified` only if the evidence has that shape, otherwise it records `unknown`. The Core builds the sentence from a template and sends `action.outcome`; the avatar shows a result expression only for a verified outcome.

## Sentences (templates, never model text)

| Status | Open | Close |
|---|---|---|
| verified | "Opened Notepad." | "Closed Spotify." |
| unknown | "I started it but couldn't confirm the window. Check Activity." | "I asked it to close but couldn't confirm it's gone. Check Activity." |
| failed | "That didn't work. Nothing was changed." | same |

## Apps & Actions

Built-in apps (Notepad, Calculator, Chrome, VS Code, Spotify) are always listed. The page scans the Start Menu and reports the names to the Core, where they wait under "Waiting for you". **Allow** adds the app and the spoken names you typed to the allowlist; only a key, a display name and aliases reach the Core (`apps.json`), the shortcut path stays in `app-targets.json` on this PC. A closed app must have been opened by REVA first (so its process name is known) unless it is built in.

## Activity

`GET /v1/activity` lists the action ledger: time, request, source, result, evidence. The ledger holds redacted arguments, so amounts and notes never appear.

## Voice expense

"Add twelve dollars for lunch" → draft → "yes" (a spoken yes only confirms the draft) → the Core proposes `finance.add_transaction` (T2) → the confirm card reads "Add $12.00 for Food · Dining? Confirm on screen." → **Confirm** (a click) → the Kernel commits one transaction → the Core says "Saved." from the Kernel event id. No account, or any Kernel error: "That didn't work. Nothing was changed."
