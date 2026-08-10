# REVA Desktop (Windows)

Status: **IN PROGRESS** — Phase 1B, Slice 1+2 of 8 (see below)

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

## Manual smoke test (Core connection)

Automated GUI execution isn't wired into CI yet (see Testing below), so
this is currently a manual check:

```powershell
# Terminal 1 — start REVA Core
python -m reva_core --serve

# Terminal 2 — launch the desktop app
dotnet run --project desktop\src\Reva.Desktop\Reva.Desktop.csproj
```

Expected: a window titled "REVA" appears, and within a moment the
status line reads "● Core Connected" (green dot). Stop Core (Ctrl+C in
Terminal 1) and relaunch the app — it should show "○ Core Unavailable"
(gray dot) instead. Both states must come from a real `GET /health`
call — never simulated.

## Configuration

Both driven by environment variables (matching REVA Core's own
conventions), read once at startup:

| Variable | Default | Purpose |
|---|---|---|
| `REVA_DESKTOP_CORE_URL` | `http://127.0.0.1:8756/` | Core base URL. Must be loopback (`localhost`/`127.0.0.1`/`::1`) — a remote URL throws `DesktopConfigurationException` at startup, by design. |
| `REVA_DATA_DIR` | `./data` (relative to the process's working directory) | Where REVA Core's `local_auth_token` file lives. Desktop and Core must currently point at the *same* directory — Core has no fixed per-user app-data location yet (tracked gap, see `docs/architecture/runtime-model.md` in the Python side). |

## Architecture

```text
Views/         XAML + WinUI-typed code (converters, code-behind UI logic)
ViewModels/    Plain C#, no WinUI types — testable without the XAML pipeline
Services/      DesktopConfiguration, ILocalTokenProvider/LocalTokenProvider,
               IRevaCoreClient/RevaCoreClient, DesktopLogger
Contracts/     DTOs mirroring REVA Core's JSON responses (HealthStatus, ...)
State/         ObservableObject — minimal hand-written INotifyPropertyChanged base
```

`Views/`, `Resources/`, `Assets/` only exist once they have real content
in them — see `docs/architecture/module-boundaries.md`'s "no empty
packages" principle in the Python side; the same discipline applies
here.

## Slice plan (Phase 1B)

| Slice | Status | What it adds |
|---|---|---|
| 1 — Solution + CI baseline | **DONE** | Buildable WinUI solution, xUnit test project, CI gates |
| 2 — Core configuration + connection | **DONE** | Loopback-validated config, token provider, `IRevaCoreClient`, honest Core Connected/Unavailable status |
| 3 — Typed assistant | PLANNED | Message composer, send flow, `POST /v1/messages` |
| 4 — Explicit memory creation | PLANNED | "Remember this" action, `POST /v1/memories` |
| 5 — Memories UI | PLANNED | Search + detail view, `GET /v1/memories` |
| 6 — Real Core integration tests | PLANNED | Test harness against a real temporary Python Core |
| 7 — Restart persistence proof | PLANNED | Automated restart-recovery E2E |
| 8 — UI polish | PLANNED | Dark/charcoal/purple visual direction |

## Testing

- **Unit** (`tests/Unit/`): `DesktopConfiguration` loopback validation,
  `LocalTokenProvider` safe-failure behavior, `RevaCoreClient` error
  normalization (connection-refused, timeout, 401, 5xx, malformed
  JSON, unexpected status), `DesktopLogger` token-withholding,
  `ObservableObject` property-change semantics. 36 tests, all passing.
- **Integration** (`tests/Integration/`): PLANNED (Slice 6) — real
  Python Core + real temporary SQLite DB, no mocks.
- **UI** (`tests/UI/`): no automated WinUI GUI execution in CI yet.
  Documented as a **manual smoke test** (above) rather than faked with
  screenshot testing or a skipped/fake automated suite. ViewModels are
  the automated-test surface for UI *logic*; the manual smoke test
  covers the rest until a WinUI UI-testing story is evaluated.
