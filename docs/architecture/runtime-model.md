# Runtime Model

## Core lifecycle

`reva_core.orchestration.lifecycle.CoreLifecycle` has three operations:

- `startup()` — opens the SQLite connection, applies any pending
  migrations, ensures a primary device row exists
  (`storage/repositories/device_repository.py`), ensures the local
  auth token exists (`security/local_token.py`), records a start
  timestamp, returns `HealthStatus`.
- `health()` — returns the current `HealthStatus` without side effects.
- `shutdown()` — closes the SQLite connection, logs a stop event.

`local_token` and `primary_device_id` are properties on `CoreLifecycle`
that raise `StorageError` if read before `startup()` — same pattern as
`connection`.

`python -m reva_core` (no flags) runs startup → logs healthy → shutdown
→ exits 0. This is intentional: the default invocation is a **smoke
test**, not a long-running server, so `python -m reva_core` always
terminates cleanly and can be scripted in CI without a kill signal.

`python -m reva_core --serve` additionally builds the FastAPI app and
calls `uvicorn.run(...)`, which blocks until interrupted (Ctrl+C /
SIGINT), then falls through to the same clean shutdown path. This is
the mode a future desktop client would launch Core in.

## Future desktop-process relationship

The PySide6 desktop UI (PLANNED, `desktop/`) is a separate OS process
from REVA Core. It will start Core (or connect to an already-running
Core instance), then talk to it exclusively through the loopback API.
The UI process must never open the SQLite file directly — that would
let a client bypass storage transaction boundaries and orchestration
entirely.

## Local communication

HTTP over loopback TCP (`127.0.0.1`), JSON bodies. As of Phase 1A,
every `/v1/*` route requires `Authorization: Bearer <token>` — see
`docs/security/security-invariants.md` and
`reva_core/security/local_token.py`. `/health` and `/version` stay
unauthenticated because they carry no user data, secrets, or
operationally sensitive detail — PRD §9's "authenticated localhost
API/IPC boundaries" requirement is now met for every route that
actually needs it.

## Crash recovery intention

SQLite in WAL mode tolerates a crash between statements without
corruption (the WAL file replays or is discarded on next open).
`CoreLifecycle.startup()` is idempotent: calling it again after an
unclean shutdown re-opens the same database, re-runs the migration
check (a no-op if the schema is current), and reports healthy. There is
no separate crash-recovery code path in Phase 0 because none is needed
yet — recovery *is* re-running startup.

## Database lifecycle

One SQLite file per install, at `<data_dir>/reva.db` (`data_dir`
defaults to `./data` in dev; a real Windows install would point this at
a per-user app-data directory — not yet wired up, tracked as a Phase 1
packaging concern). The file, its `-wal` and `-shm` siblings, and the
local auth token file (`<data_dir>/local_auth_token`) are all
git-ignored and never committed.

## Background runtime model

Phase 0 has no background scheduler, no polling loop, and no timers.
`CoreLifecycle` does exactly what is asked of it, when asked. Future
phases add: a reminder due-time scanner (Phase 3), a voice session
loop (Phase 2), and a sync reconciliation loop (Phase 5) — none of
which exist yet, and none of which will be built as a generic
"background job runner" (see `future-expansion-policy.md`).
