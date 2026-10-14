# SYNC-1e review: open screens follow the data

Scope: `GET /v1/domains/changes` and the change counter in Core (`reva_core/domains/`,
`reva_core/gateway/service.py`), the WinUI watcher (`desktop/.../Finance/DomainChanges.cs`, wiring
in `App.xaml.cs` and `MainWindow.xaml.cs`), and the Android change flow, `AutoSyncController`,
and `SyncEngine` changes. Design: `docs/architecture/domain-changes.md`.

Result: **no blocking finding open.** Two defects were found by the new tests and fixed in-slice,
two gaps were found by review and fixed, and four items are residual risk.

## Threat table

| Threat | Asset | Control | Evidence |
|---|---|---|---|
| Spoofing: another local process calls the long-poll | change timing | Bearer token required; same token as every `/v1` route | `test_the_route_requires_the_bearer_token`, `test_v1_auth_required.py` |
| Spoofing: a fake PC receives the phone's signed requests during auto sync | signed sync traffic | TLS key pinned from the QR; the handshake fails before any request body is sent | `GatewayTransport` / SYNC-1d review |
| Tampering: a request writes through the changes route | Finance data | The route only reads a counter; the route allow-list tests list it as GET | `test_no_tool_endpoint.py`, `test_api_boundary.py` |
| Information disclosure: the reply leaks data | Finance data | Reply is `{domain, counter, changed}` only, `Cache-Control: no-store` | `test_the_reply_carries_no_data_and_is_not_cached` |
| Information disclosure: probing which domains exist | domain list | Pattern-validated name; unknown name is 404 (the list is public at `/v1/domains` anyway) | `test_unknown_domains_and_bad_parameters_are_refused` |
| Denial of service: many open long-polls | Core | At most 8 waiters, 429 beyond; wait capped at 30 s; waiters are futures, not threads; a cancelled waiter releases its slot | `test_the_number_of_waiters_is_bounded`, `test_a_cancelled_waiter_releases_its_slot` |
| Denial of service: reload storms | UI | Debounce 300 ms on both apps; back-off 1 to 30 s when Core fails; the PC reload is quiet | `ChangeRefreshTest`, `DomainChangeWatcherTests` |
| Elevation: auto sync widens the app's permissions | phone | Manifest unchanged: INTERNET and CAMERA only | `ManifestTest` (JVM suite) |
| Repudiation / noise: a revoked phone keeps calling the PC | PC audit log | After a 401 the controller stops retrying until a manual sync works or the phone is paired again | `a_pc_that_removed_this_phone_stops_the_retries...` |

## Findings

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| S-1 | Medium (correctness) | The view models skipped the first emission of the change flow (`drop(1)`), so a change that landed before collection started was swallowed and the screen stayed stale. Found by the tests (5 failed). | The counter at construction is the baseline; `dropWhile { it == seen }`. `ChangeRefreshTest` |
| S-2 | Low (noise, UX) | After the PC revoked a phone, auto sync would retry a 401 every minute and show nothing. Found in review. | Stop retrying that grant, say "Sync stopped: the PC no longer trusts this phone. Open Devices.", resume after a manual success or a new pairing. |
| S-3 | Low (UX) | A background reload showed the loading spinner on every sync. | `showLoading=false` for change-driven reloads on both apps. `a_background_reload_does_not_flash_the_spinner` |
| S-4 | Low (testing) | My first back-off test was racy (released a delay before the watcher requested the next one). | Waits for the request before releasing; 5 consecutive runs pass. |

## Residual risks (accepted)

| ID | Risk | Why accepted |
|---|---|---|
| R-1 | A process holding the Core token can hold all 8 long-poll slots, making the app's own watcher get 429 and back off. | That process already has full read/write access with the same token. |
| R-2 | The phone cannot be told by the PC to sync; a PC-side change reaches an open phone screen within about a minute (foreground interval). | By design: the PC cannot reach the phone. A push channel is a separate decision. |
| R-3 | Without a network-state permission, auto sync also tries on mobile data. The attempt goes to a private LAN address, fails fast, and sends nothing (the pin check fails first). | Adding the permission would change a security-relevant manifest invariant; the cost is a failed connect per minute. |
| R-4 | The Core counter resets on restart. | A counter lower than the caller's baseline counts as a change, so the app reloads once. Tested. |

## Pre-existing, noted

* `RevaCoreLifecycleTests.Monitor_TransientFailureThenPass_...` failed once in one full desktop run
  and passed in 8 later runs and alone. It is timing-sensitive and unrelated to this slice.
