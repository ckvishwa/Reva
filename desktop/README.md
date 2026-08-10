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

## E2E gate (automated, real Core + real app + real UI Automation)

The typed-assistant flow proven manually in Slice 3 is now automated
and repeatable:

```powershell
powershell -ExecutionPolicy Bypass -File desktop\tests\E2E\Run-TypedAssistantE2E.ps1
```

Build the desktop app first (`dotnet build desktop\Reva.Desktop.sln
--configuration Release`) — the script doesn't build it for you.

This drives the **actual compiled `Reva.Desktop.exe`** via
`System.Windows.Automation`, against a **real** `python -m reva_core
--serve` process, in an isolated temp data directory and on a
non-default loopback port (`18756`, so it never collides with a
developer's own manually-running Core on the default `8756`). It is
not a unit test, not a mocked-HTTP test, not a ViewModel test, and not
a manually-clicked check.

Proves, in order: Core becomes healthy (bounded poll, no arbitrary
sleep), the real window and its real controls (`ComposerBox`,
`SendButton`, `MessageList`, `CoreStatusText` — all located by
`AutomationId`) are found, the app shows a real "Core Connected"
status, typing + sending renders both the user message and Core's real
reply, the composer clears, and — the part a UI-only check can't prove
— Core's own authenticated `GET /v1/audit-events` shows exactly one
matching `typed_request_received` event with the correct content
length and zero `memory_created`/`memory_create_requested` events
(ordinary messages never create memory). Also asserts, statically, that
no SQLite reference exists anywhere in `desktop/`.

Cleanup (stop the app, stop Core, unregister log-forwarding handles)
runs in a `finally` block — it happens whether the run passes or
fails. On success the isolated temp directory is deleted; on failure
it's preserved and its path is printed, along with Core's captured
stdout/stderr, the app's pre-cleanup process state, and the last known
UI text dump. Exit code `0` on full pass, `1` otherwise. Verified
repeatable across multiple consecutive runs, each with a fresh
correlation-bearing test message so stale audit/UI data can't produce
a false positive.

### Two real bugs this caught (both fixed, both now regression-tested)

1. **`ShellViewModel.RefreshCoreStatusAsync` used `ConfigureAwait(false)`.**
   Found during Slice 3's manual proof. The continuation (setting
   `IsCoreConnected`/`CoreStatusText`) resumed on a thread-pool thread
   instead of the UI thread — no exception, no crash, the status
   silently never reached the UI, stuck on "Checking REVA Core..."
   forever even against a healthy Core. Fixed by removing
   `ConfigureAwait(false)`; any ViewModel method that mutates UI-bound
   state after an `await` must not use it. Regression-tested in
   `ShellViewModelTests.RefreshCoreStatusAsync_ResumesOnCallingSynchronizationContext`,
   which installs a recording `SynchronizationContext` and fails if the
   continuation bypasses it — empirically verified to actually catch
   the bug (reintroduced it, watched the test fail, reverted, watched
   it pass) before trusting it as a regression guard.
2. **`x:Bind`'s `TwoWay` binding for `TextBox.Text` only commits on
   `LostFocus`, not on every keystroke.** Found while building this
   E2E script: `InvokePattern.Invoke()` (unlike a real mouse click)
   doesn't reliably shift keyboard focus first, so `Assistant.ComposerText`
   could still hold stale (often empty) content when Send fired,
   hitting the ViewModel's correctly-working empty-input guard and
   silently no-op'ing the whole send. This wasn't just a test artifact
   — it affects the real Enter-to-send path too, since pressing Enter
   never blurs the composer either. Fixed in `MainWindow.xaml.cs` by
   reading `ComposerBox.Text` directly before acting on Send
   (`SyncComposerTextFromTextBox`), rather than trusting the binding's
   commit timing.

### Manual exploratory run

For interactive poking around (not needed to verify correctness — the
E2E gate above covers that):

```powershell
# Terminal 1
python -m reva_core --serve
# Terminal 2 (same REVA_DATA_DIR as Core if you overrode it)
dotnet run --project desktop\src\Reva.Desktop\Reva.Desktop.csproj
```

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
  equality, no token exposure), `ShellViewModel` (initial/success/failure
  state, plus the `ConfigureAwait` regression guard above),
  `DesktopLogger` token-withholding, `ObservableObject` property-change
  semantics. 59 tests, all passing.
- **Integration** (`tests/Integration/`): PLANNED (Slice 6) — real
  Python Core + real temporary SQLite DB, no mocks, but exercised
  through `RevaCoreClient`/repositories directly rather than the full
  compiled app + UI.
- **E2E** (`tests/E2E/`): `Run-TypedAssistantE2E.ps1` — see "E2E gate"
  above. Real app, real Core, real UI Automation, real audit-trail
  corroboration. Currently local-only; see CI status below for why.

### CI status for the E2E gate

**Not added to CI. This is a deliberate, documented limitation, not an
oversight or something faked to look green.** GitHub Actions'
`windows-latest` runners are real Windows Server VMs and can build
WinUI apps fine (see the existing `csharp-desktop` job), but whether a
GUI window they create can be reliably located, activated, and driven
via UI Automation in that hosted, service-account, non-interactive-by-
default session is a genuine open question this environment cannot
verify — there is no way to push to GitHub Actions and observe the
result from here. Rather than guess and risk either a flaky red job
for infrastructure reasons unrelated to code correctness, or silently
downgrading the "real E2E" claim into a service-level check to force a
green checkmark (explicitly not acceptable), the gate stays local-only
for now. `dotnet build`/`dotnet test` (unit-level) remain the CI-level
gate; the E2E script is the authoritative pre-merge/pre-release check
a developer runs locally. Revisit this once someone can actually
validate a `windows-latest` UIA job empirically.
