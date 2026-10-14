# Open screens follow the data (SYNC-1e)

Before alpha.3, a screen that was already open did not show what a sync changed until you switched
tabs. This note says why, and how the fix works on both apps.

## Why it happened

| App | What loaded the screens | What was missing |
|---|---|---|
| PC (WinUI) | `MainWindow.OnNavigationPropertyChanged` reloaded Finance or Today when the section was **opened**. The only timer on the Finance page re-read the conflict banner every 10 s. | Nothing told an open page that a phone sync had applied events. |
| Phone (Compose) | `RevaRoot` reloaded a tab when it was **entered**, and the manual Sync button's callback reloaded both view models. | No signal for any other change, and no automatic sync at all. |

## The signal: a change counter

One integer per domain that moves whenever committed data changes. It holds no data.

* **Core** (`reva_core/domains/service.py`): `DomainService.note_change(domain)` is called after
  every committed local write (create, update, delete, conflict resolve, mark-paid, and an import
  that accepted rows) and after every pushed sync batch that applied events (`gateway/service.py`).
  A refused command, a dry-run import, a read, a pull and a resent batch with nothing new do not move it.
* **Phone** (`FinanceRepository.changes`): a `StateFlow<Long>` that moves after the same kinds of
  writes, and, through `SyncEngine.onApplied`, after a sync that applied events from the PC.

The counter is kept by the host (Core, the phone repository), not inside the Rust Kernel, because
every write already passes through one of those two entry points; the Kernel and its bindings are
unchanged.

## PC: `GET /v1/domains/changes`

`?domain=finance&since=<n>&timeout=<0..30>` waits until the counter differs from `since` (or the
timeout passes) and answers `{"domain","counter","changed"}`. Bearer token required, `Cache-Control:
no-store`, no data in the reply. At most 8 waiters at once (HTTP 429 beyond). A counter lower than
`since` counts as a change, so a Core restart makes the app reload once.

`DomainChangeWatcher` (WinUI) runs the long-poll on a pool thread, treats the first answer as a
baseline, debounces bursts into one reload (300 ms), backs off 1 s to 30 s when Core fails, and hands
the reload to the UI thread through a `DispatcherQueue`. The open Finance page or Today card reloads
quietly (no progress ring). The Devices page now reads "Synced 5 min ago".

## Phone: reactive view models and automatic sync

* `FinanceViewModel` and `TodayViewModel` collect `changes`, debounce 300 ms, and reload quietly once
  they have loaded. The counter value at construction is the baseline, so a change that lands before
  collection starts is not lost.
* `AutoSyncController`: sync when the app comes to the front, then every 60 s while it stays there;
  only when a PC is paired and the setting is on (default on; switch on Devices). One sync at a time
  (`SyncEngine` holds a mutex), so a manual tap never overlaps an automatic one. A failure is quiet
  and retried; a 401 (the PC removed this phone) stops the retries and says so until a manual sync
  works or the phone is paired again.
* Today and Finance show "Synced just now / x min ago", ticking every 30 s.
* The manifest still has only INTERNET and CAMERA. There is no network-state permission, so "on
  Wi-Fi" means "the PC's LAN address answers". Every request is signed and goes only to a server
  that presents the pinned TLS key, so a different network cannot receive one.

## What is deliberately not here

* No push from the PC to the phone. The phone asks (foreground and every 60 s); the PC cannot reach
  it. A change made on the PC therefore reaches an open phone screen within about a minute.
* No background sync when the app is closed (no service, no notification).
