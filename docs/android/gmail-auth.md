# Gmail authorization on Android (CON-1)

CON-1 connects the phone app to the owner's Gmail with **read-only** access and proves it with one real API call.
It does not read, parse or store mail. Parsing (CON-2) and Kernel ingestion are later slices.

## What it does

- More > Gmail shows what `gmail.readonly` allows (reading the whole mailbox) before the user taps **Connect Gmail**.
- Google Identity Services' `AuthorizationClient` (`play-services-auth`) asks for exactly one scope:
  `https://www.googleapis.com/auth/gmail.readonly`. Google shows its own account picker and consent screen.
- After a grant, the app calls `users.messages.list` with `maxResults=1&fields=resultSizeEstimate` over HTTPS.
  Only the HTTP status is kept; the body is drained and dropped, and no message id is requested.
- The screen shows **Connected** (with the HTTP status) or an error with an action:
  - consent refused or backed out: *Connect Gmail* again;
  - token rejected (401): the token is cleared in Play services and fetched once more silently, which covers
    expiry; a second 401 or Google asking for the user during a silent check means access was revoked or must be
    granted again (*Connect Gmail*);
  - 403 / 429 / 5xx / network: *Try again*;
  - Play services missing: no action.
- **Disconnect** revokes the grant at Google (`AuthorizationClient.revokeAccess`) and clears the local flag. If Google
  cannot confirm the revoke, the screen says so and points to Google Account > Security > Third-party connections.

## What it keeps, and where

| Data | Where |
|---|---|
| OAuth grant and refresh | Google Play services (not REVA) |
| Access token | Memory, for one request; never stored, logged or shown |
| Account (for revoke) | Memory only |
| "Connected" flag | Private preferences `gmail`, excluded from Android backups |
| Mail content | Nothing is read |

Nothing from Gmail is sent to the PC Core, OpenClaw, analytics or any model. `GmailSourceGuardTest` fails the build if
a write or full-mailbox scope, a client secret or a server auth code appears, if the connector logs, or if anything
but the composition root imports it.

## Google Cloud configuration

Project `reva-personal-assistant`; Android OAuth client for package `app.reva.android` with the debug-keystore SHA-1
of the build machine; audience External, publishing status Testing; one test user. Android clients have no client
secret and no Web client is used. An APK signed with any other key (CI, another PC, release) needs its SHA-1 added
to the OAuth client first, or Google refuses the request.

Testing status limits: only listed test users can connect, Google shows an "unverified app" notice, and refresh
grants for restricted scopes such as `gmail.readonly` expire after about 7 days, after which the screen asks to
connect again. Publishing would require Google's verification and a security assessment for the restricted scope.

## Tests

- `GmailConnectorTest` (JVM): grant, consent, denial, scope missing, expiry (401 then silent refresh), second 401,
  revocation found by a silent check, transient failures and retry, disconnect with and without a confirmed revoke,
  token never in any `toString`.
- `HttpsGmailProbeTest` (JVM): URL, method, bearer header, no redirects, status passthrough, IO failure.
- `GmailSourceGuardTest` (JVM): the guard rails above.
- `GmailScreenComposeTest` (device, fake port): each screen state and its action.
- `GmailLiveAuthTest` (device, opt-in, real Google): refuse consent, grant consent and reach Gmail with HTTP 200,
  disconnect. Run with
  `-Pandroid.testInstrumentationRunnerArguments.class=app.reva.GmailLiveAuthTest -Pandroid.testInstrumentationRunnerArguments.revaGmailLive=true`.
