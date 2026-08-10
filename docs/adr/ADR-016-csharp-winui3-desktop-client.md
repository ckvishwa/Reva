# ADR-016: C# / WinUI 3 for the Windows Desktop Client

**Status:** Accepted (Phase 1B, in progress). Supersedes ADR-002 (PySide6).

## Context

REVA's Windows desktop client needs to be genuinely native-feeling,
performant, and maintainable long-term. ADR-002 originally chose
PySide6 to keep the whole stack in one language. Before any client
code was written, the direction changed to C#-first for the desktop,
Python-first for Core — a thin native client talking to Core only
over the existing loopback HTTP API (PRD §10 architecture already
describes this exact boundary; only the client's implementation
language changed).

## Decision

The Windows desktop client is C#/.NET 10, WinUI 3, XAML, with a small
hand-written MVVM structure (no CommunityToolkit.Mvvm — three-ish
services and a couple of ViewModels don't need a source generator).

## Toolchain validation performed before committing to this

Concrete build-tooling risk was retired empirically, not assumed:

- Confirmed VS2022's Windows App SDK 1.6 MSBuild targets hard-require
  `Microsoft.Build.Packaging.Pri.Tasks.dll`/`Microsoft.Build.AppxPackage.dll`,
  which only ship via a Visual Studio workload (not the .NET SDK, not
  NuGet) — reproduced as an MSB4062 failure on a disposable probe
  project.
- Confirmed the same failure persists under Visual Studio 2026
  (MSBuild 18) with WindowsAppSDK 1.6, and confirmed the *mechanism*:
  `dotnet build` resolves `$(MSBuildExtensionsPath)` under the .NET
  SDK's own tree, which structurally never ships that VS-exclusive
  folder — no VS installation state changes that.
- Confirmed **WindowsAppSDK 2.3.1** (the current stable release,
  replacing the older monolithic 1.6 package with a modular one) does
  **not** hit this failure at all for an unpackaged
  (`WindowsPackageType=None`) app: plain `dotnet build` and `dotnet
  test` both succeed with zero warnings/errors, no
  `AppxMSBuildToolsPath` override, no VS-path hardcoded anywhere.
- Verified with both a disposable throwaway probe project (outside
  the repo, deleted after) and the real `Reva.Desktop.sln`.

## Alternatives considered

- **PySide6** (ADR-002's original choice) — same language as Core, but
  Qt-for-Python's native-Windows feel and long-term WinUI-equivalent
  polish were judged weaker than a real native WinUI 3 client, and the
  product now explicitly wants a C#-first desktop.
- **Electron** — heavy runtime footprint conflicts with the "idle
  memory under 500MB" target (PRD §13); rejected in ADR-002 already,
  still rejected.
- **Tauri** — lighter than Electron but still a from-scratch web-shell
  stack; no compelling reason over a real native toolkit.
- **WPF** — the explicit fallback if WinUI 3 had a concrete tooling
  blocker. It didn't, once WindowsAppSDK 2.3.1 was probed instead of
  the outdated 1.6 baseline — so WPF was not needed.

## Consequences

- Desktop and Core are two languages now (C# and Python), each doing
  what it's suited for — native UI vs. domain logic. The API boundary
  (already required by the architecture regardless of client language)
  is the only coupling between them; ADR-007's localhost/auth boundary
  is unchanged.
- `net10.0-windows10.0.19041.0` / `TargetPlatformMinVersion
  10.0.17763.0` / `WindowsAppSDK 2.3.1` / `WindowsPackageType=None` is
  the confirmed-working baseline; CI (`windows-latest`) has the needed
  MSBuild components preinstalled, so no CI-side workaround is needed
  either.
- ViewModels are kept free of WinUI types specifically so they can be
  unit-tested without pulling in the XAML compiler pipeline (see
  `desktop/README.md`).

## Security implications

Unchanged from ADR-002's original assessment: the client talks to Core
only through the authenticated localhost API boundary, never embeds
domain logic, SQL, or policy decisions, and never accesses SQLite
directly — enforced by module boundary discipline (`desktop/README.md`),
not by the language choice itself.
