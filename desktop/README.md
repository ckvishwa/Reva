# REVA Desktop (Windows)

Status: **IN PROGRESS** — Phase 1B, Slice 1-3 of 8 (see below)

A thin native Windows client for REVA Core. C#/.NET, WinUI 3, XAML,
small explicit MVVM. It talks to REVA Core exclusively over the
loopback HTTP API — it never opens the SQLite database directly, and
it never implements memory/AI/policy/audit/provider/sync/tool logic
itself. All of that stays in Python (`reva_core/`).

Supersedes the Phase 0/1A placeholder that named PySide6 as the
desktop stack — see ADR-002 (superseded) and the Phase 1B session for
why C#/WinUI 3 was chosen instead and the concrete toolchain probing
that confirmed it builds with plain `dotnet build`/`dotnet test`, no
Visual Studio path hardcoded anywhere.

## Toolchain

- C#, .NET 10
- WinUI 3 (`Microsoft.WindowsAppSDK` 2.3.1) + XAML
- `TargetFramework`: `net10.0-windows10.0.19041.0`
- `TargetPlatformMinVersion`: `10.0.17763.0`
- `WindowsPackageType=None` (unpackaged — no MSIX)
- xUnit for tests

## Build and run (Windows PowerShell)

```powershell
dotnet restore desktop\Reva.Desktop.sln
dotnet build desktop\Reva.Desktop.sln --configuration Release
dotnet test desktop\Reva.Desktop.sln --configuration Release

dotnet run --project desktop\src\Reva.Desktop\Reva.Desktop.csproj
```

No `AppxMSBuildToolsPath` override, no hardcoded Visual Studio install
path — confirmed working with WindowsAppSDK 2.3.1 via both plain
`dotnet build` and Visual Studio 2026's MSBuild.

## Manual smoke test (Core connection + typed assistant)

Automated GUI execution isn't wired into CI yet (see Testing below), so
this is currently a manual check:

```powershell
# Terminal 1 — start REVA Core
python -m reva_core --serve

# Terminal 2 — launch the desktop app (same REVA_DATA_DIR as Core if
# you overrode it, so the desktop can find the same local_auth_token)
dotnet run --project desktop\src\Reva.Desktop\Reva.Desktop.csproj
```

Expected: a window titled "REVA" appears, and within a moment the
status line reads "Core Connected" (green dot). Stop Core (Ctrl+C in
Terminal 1) and relaunch the app — it should show "Core Unavailable"
(gray dot) instead. Both states must come from a real `GET /health`
call — never simulated.

Type a message in the composer and press Enter (or click Send): it
should appear immediately under "You", the composer clears, Send
disables while the request is in flight, and REVA Core's real reply
appears under "REVA" a moment later. `GET /v1/audit-events` (with the
real bearer token) will show a matching `typed_request_received` event
with no `memory_created` — ordinary messages never create memory.

This exact flow was verified during Slice 3 development using real UI
Automation (`System.Windows.Automation` from PowerShell) driving the
real built exe against a real running Core — not simulated. That
session also caught a real bug: `ShellViewModel.RefreshCoreStatusAsync`
used to await with `ConfigureAwait(false)`, so the status update landed
on a thread-pool thread and silently never reached the UI (no crash,
no exception — just stuck on "Checking REVA Core..." forever, even
against a healthy Core). Fixed by removing it; any ViewModel method
that mutates UI-bound state after an `await` must not use
`ConfigureAwait(false)`.

## Configuration

Both driven by environment variables (matching REVA Core's own
conventions), read once at startup:

| Variable | Default | Purpose |
|---|---|---|
| `REVA_DESKTOP_CORE_URL` | `http://127.0.0.1:8756/` | Core base URL. Must be loopback (`localhost`/`127.0.0.1`/`::1`) — a remote URL throws `DesktopConfigurationException` at startup, by design. |
| `REVA_DATA_DIR` | `./data` (relative to the process's working directory) | Where REVA Core's `local_auth_token` file lives. Desktop and Core must currently point at the *same* directory — Core has no fixed per-user app-data location yet (tracked gap, see `docs/architecture/runtime-model.md` in the Python side). |

## Architecture

```text
ViewModels/    Plain C#, no WinUI types — testable without the XAML pipeline
               (ShellViewModel, AssistantViewModel)
Services/      DesktopConfiguration, ILocalTokenProvider/LocalTokenProvider,
               IRevaCoreClient/RevaCoreClient, DesktopLogger
Contracts/     DTOs mirroring REVA Core's JSON responses (HealthStatus,
               VersionInfo, TypedMessageRequest/Response, ...)
State/         ObservableObject (base), AssistantMessage (session-only
               conversation entry — no persistence in this slice)
```

`Views/`, `Resources/`, `Assets/` only exist once they have real content
in them — see `docs/architecture/module-boundaries.md`'s "no empty
packages" principle in the Python side; the same discipline applies
here. (A `Views/StatusBrushConverter.cs` existed briefly in Slice 2 and
was removed — see the WinUI codegen bug note below.)

**A known WinUI 3 XAML-compiler limitation**: an `x:Bind` using an
`IValueConverter` referenced via `{StaticResource}` fails to compile
(`CS1503`, `SetConverterLookupRoot` expects a `FrameworkElement`) when
the page root is a `Window` rather than a `Page`/`UserControl` — `Window`
doesn't derive from `FrameworkElement`. Worked around throughout by
exposing plain, converter-free properties from ViewModels/models
instead (`AssistantMessage.RoleLabel`, `AssistantViewModel.IsNotPending`)
and setting the one genuinely visual-only value (the status dot's
color) imperatively in code-behind.

## Slice plan (Phase 1B)

| Slice | Status | What it adds |
|---|---|---|
| 1 — Solution + CI baseline | **DONE** | Buildable WinUI solution, xUnit test project, CI gates |
| 2 — Core configuration + connection | **DONE** | Loopback-validated config, token provider, `IRevaCoreClient`, honest Core Connected/Unavailable status |
| 3 — Typed assistant | **DONE** | Message composer, send flow, `POST /v1/messages`, real UI-Automation-verified against a real Core |
| 4 — Explicit memory creation | PLANNED | "Remember this" action, `POST /v1/memories` |
| 5 — Memories UI | PLANNED | Search + detail view, `GET /v1/memories` |
| 6 — Real Core integration tests | PLANNED | Test harness against a real temporary Python Core |
| 7 — Restart persistence proof | PLANNED | Automated restart-recovery E2E |
| 8 — UI polish | PLANNED | Dark/charcoal/purple visual direction |

## Testing

- **Unit** (`tests/Unit/`): `DesktopConfiguration` loopback validation,
  `LocalTokenProvider` safe-failure behavior, `RevaCoreClient` error
  normalization and the typed-message request/response path (POST
  target, Bearer header, body content, no-request-when-unauthorized),
  `AssistantViewModel` (initial state, whitespace rejection, one
  request per submit, immediate user-message append, pending state,
  duplicate-send blocking, success/failure outcomes, exact safe-error
  equality, no token exposure), `DesktopLogger` token-withholding,
  `ObservableObject` property-change semantics. 55 tests, all passing.
- **Integration** (`tests/Integration/`): PLANNED (Slice 6) — real
  Python Core + real temporary SQLite DB, no mocks.
- **UI** (`tests/UI/`): no automated WinUI GUI execution in CI yet.
  Documented as a **manual smoke test** (above) rather than faked with
  screenshot testing or a skipped/fake automated suite. That manual
  test has itself been performed with real UI Automation (not just
  eyeballing) during Slice 2 and Slice 3 development — see the manual
  smoke test section above for what it caught. ViewModels remain the
  primary automated-test surface for UI *logic*.
