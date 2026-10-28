# Automatic Core Lifecycle (Windows Desktop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Double-clicking `Reva.Desktop.exe` with no REVA Core process running reaches `Core Connected` automatically — no manual `python -m reva_core --serve` in PowerShell.

**Architecture:** A new `RevaCoreLifecycle` service owns process lifecycle only (probe existing Core -> attach, or resolve+launch a local Python Core -> wait for health -> wait for `local_auth_token` -> connected), exposes a 4-state machine (`Starting`/`Connected`/`Unavailable`/`AuthorizationUnavailable`) via an event, and runs a background reconnect monitor. `App.xaml.cs` composes it; `ShellViewModel` renders its state; nothing else in the app changes. Core executable resolution (today: repo `.venv\Scripts\python.exe`) is isolated behind `ICoreExecutableLocator` so packaged-app resolution can replace it later without touching the lifecycle state machine.

**Tech Stack:** C# / .NET 10, WinUI 3, xUnit 2.9, existing `Reva.Desktop`/`Reva.Desktop.Tests` projects — no new NuGet packages.

## Global Constraints

- Never put the bearer token on a child process command line or in any log line (existing `DesktopLogger.Redact` already withholds messages containing "token"/"authorization"/"bearer"/"password"/"secret" — new code must not rely on that as its only safeguard; never pass the token to `ProcessStartInfo` at all).
- Never kill a process occupying the configured Core port that isn't REVA's own Core.
- C# owns process lifecycle only. No SQLite access, no ranking, no policy, no memory semantics in C#.
- All Core URLs stay loopback-only (already enforced in `DesktopConfiguration` — do not weaken).
- No DI container is introduced — `App.xaml.cs` stays the explicit composition root.
- Do not build an installer/updater or a packaged-app executable resolver in this slice — only encapsulate the seam (`ICoreExecutableLocator`) so one can be added later.
- xUnit tests must not depend on a real Python/Ollama install, except where a task explicitly says "real process" (those use trivial OS commands like `cmd.exe /c exit N`, never Python).

---

## File Structure

New files (all under `desktop/src/Reva.Desktop/Services/` unless noted):
- `RuntimePaths.cs` — stable per-user data directory default.
- `CoreLifecycleState.cs` — the 4-state enum.
- `CoreExecutableResolution.cs` — result of resolving how to launch Core.
- `ICoreExecutableLocator.cs` / `DeveloperModeCoreExecutableLocator.cs` — developer-mode `.venv` resolution, isolated behind an interface.
- `ICoreProcessLauncher.cs` / `CoreProcessLauncher.cs` / `ICoreProcessHandle.cs` — real `Process` launch, isolated behind an interface for testing.
- `IRevaCoreLifecycle.cs` / `RevaCoreLifecycle.cs` — the state machine.

Modified files:
- `DesktopConfiguration.cs` — default data directory becomes `RuntimePaths.GetDefaultDataDirectory()` instead of `cwd\data`.
- `App.xaml.cs` — composes and starts `RevaCoreLifecycle` before/while showing `MainWindow`.
- `ViewModels/ShellViewModel.cs` — driven by `IRevaCoreLifecycle` state instead of one-shot `GetHealthAsync`.
- `MainWindow.xaml.cs` — 4-way status dot color mapping.

New test files under `desktop/tests/Reva.Desktop.Tests/Unit/`:
- `RuntimePathsTests.cs`, `DeveloperModeCoreExecutableLocatorTests.cs`, `CoreProcessLauncherTests.cs`, `RevaCoreLifecycleTests.cs`.
Modified test files: `DesktopConfigurationTests.cs`, `ShellViewModelTests.cs`.

---

### Task 1: Stable per-user runtime data directory

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/RuntimePaths.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/RuntimePathsTests.cs`
- Modify: `desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs:62-65`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs`

**Interfaces:**
- Produces: `RuntimePaths.GetDefaultDataDirectory() -> string`, a pure function (no env reads) returning `%LOCALAPPDATA%\Reva`.

- [ ] **Step 1: Write the failing test**

```csharp
// desktop/tests/Reva.Desktop.Tests/Unit/RuntimePathsTests.cs
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class RuntimePathsTests
{
    [Fact]
    public void GetDefaultDataDirectory_ReturnsRevaFolderUnderLocalAppData()
    {
        var expected = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Reva");

        var actual = RuntimePaths.GetDefaultDataDirectory();

        Assert.Equal(expected, actual);
    }

    [Fact]
    public void GetDefaultDataDirectory_IsStableAcrossCalls()
    {
        Assert.Equal(RuntimePaths.GetDefaultDataDirectory(), RuntimePaths.GetDefaultDataDirectory());
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test desktop\Reva.Desktop.sln --filter RuntimePathsTests`
Expected: FAIL — `RuntimePaths` does not exist (CS0246).

- [ ] **Step 3: Write minimal implementation**

```csharp
// desktop/src/Reva.Desktop/Services/RuntimePaths.cs
namespace Reva.Desktop.Services;

/// <summary>
/// Deterministic Windows per-user REVA runtime/data location, shared by
/// Desktop and the Python Core it launches. Deliberately reads no
/// environment variables here — <see cref="DesktopConfiguration"/> owns
/// the single REVA_DATA_DIR override read, so tests that manipulate that
/// env var keep working exactly as before.
/// </summary>
public static class RuntimePaths
{
    public static string GetDefaultDataDirectory() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Reva");
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test desktop\Reva.Desktop.sln --filter RuntimePathsTests`
Expected: PASS

- [ ] **Step 5: Replace `DesktopConfiguration`'s fragile default and update its test**

Modify `desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs:62-65` from:

```csharp
        var dataDirOverride = Environment.GetEnvironmentVariable(DataDirectoryEnvironmentVariable);
        var dataDirectory = string.IsNullOrWhiteSpace(dataDirOverride)
            ? Path.Combine(Directory.GetCurrentDirectory(), "data")
            : dataDirOverride;
```

to:

```csharp
        var dataDirOverride = Environment.GetEnvironmentVariable(DataDirectoryEnvironmentVariable);
        var dataDirectory = string.IsNullOrWhiteSpace(dataDirOverride)
            ? RuntimePaths.GetDefaultDataDirectory()
            : dataDirOverride;
```

Also update the `CoreDataDirectory` XML doc comment (lines 19-26) — it currently documents the old `./data` gap; replace with:

```csharp
    /// <summary>
    /// Directory REVA Core's local_auth_token file and SQLite database
    /// live in. Defaults to the stable per-user location
    /// <see cref="RuntimePaths.GetDefaultDataDirectory"/> (same directory
    /// <see cref="RevaCoreLifecycle"/> passes to a Core process it
    /// launches via REVA_DATA_DIR), overridable via REVA_DATA_DIR for
    /// tests/development — see docs/architecture/runtime-model.md.
    /// </summary>
```

Add to `desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs` (after `CreateDefault_UsesLoopbackUrlAndDoesNotThrow`):

```csharp
    [Fact]
    public void CreateDefault_UsesStableLocalAppDataDirectory_WhenNoEnvironmentOverride()
    {
        var configuration = DesktopConfiguration.CreateDefault();

        Assert.Equal(RuntimePaths.GetDefaultDataDirectory(), configuration.CoreDataDirectory);
    }

    [Fact]
    public void CreateDefault_RespectsDataDirectoryEnvironmentOverride()
    {
        var overridePath = Path.Combine(Path.GetTempPath(), "reva-desktop-config-test-" + Guid.NewGuid());
        Environment.SetEnvironmentVariable("REVA_DATA_DIR", overridePath);
        try
        {
            var configuration = DesktopConfiguration.CreateDefault();

            Assert.Equal(overridePath, configuration.CoreDataDirectory);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_DATA_DIR", null);
        }
    }
```

- [ ] **Step 6: Run full test project to verify no regression**

Run: `dotnet test desktop\Reva.Desktop.sln --filter "RuntimePathsTests|DesktopConfigurationTests"`
Expected: PASS, all tests including the two new ones.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/RuntimePaths.cs desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs desktop/tests/Reva.Desktop.Tests/Unit/RuntimePathsTests.cs desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs
git commit -m "feat(desktop): resolve stable per-user data directory instead of cwd\\data"
```

---

### Task 2: Developer-mode Core executable resolution

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/CoreExecutableResolution.cs`
- Create: `desktop/src/Reva.Desktop/Services/ICoreExecutableLocator.cs`
- Create: `desktop/src/Reva.Desktop/Services/DeveloperModeCoreExecutableLocator.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/DeveloperModeCoreExecutableLocatorTests.cs`

**Interfaces:**
- Produces: `ICoreExecutableLocator.Resolve() -> CoreExecutableResolution`, `CoreExecutableResolution { bool IsAvailable, string? FileName, string? Arguments, string? WorkingDirectory, string? FailureReason }` with factory methods `Available(fileName, arguments, workingDirectory)` / `Unavailable(reason)`.
- Consumes (env vars, both optional overrides): `REVA_CORE_PYTHON_EXE` (explicit full path to a `python.exe`), `REVA_CORE_REPO_ROOT` (explicit repo checkout root to search from instead of `AppContext.BaseDirectory`).

- [ ] **Step 1: Write the failing tests**

```csharp
// desktop/tests/Reva.Desktop.Tests/Unit/DeveloperModeCoreExecutableLocatorTests.cs
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class DeveloperModeCoreExecutableLocatorTests
{
    private static string CreateFakeRepo(string tempRoot)
    {
        var repoRoot = Path.Combine(tempRoot, "fake-repo-" + Guid.NewGuid());
        Directory.CreateDirectory(Path.Combine(repoRoot, "reva_core"));
        Directory.CreateDirectory(Path.Combine(repoRoot, ".venv", "Scripts"));
        File.WriteAllText(Path.Combine(repoRoot, "pyproject.toml"), "[project]\nname = \"reva-core\"\n");
        File.WriteAllText(Path.Combine(repoRoot, ".venv", "Scripts", "python.exe"), "fake");
        return repoRoot;
    }

    [Fact]
    public void Resolve_FindsRepoViaRepoRootOverride_WhenVenvPresent()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-test-" + Guid.NewGuid());
        Directory.CreateDirectory(tempRoot);
        var repoRoot = CreateFakeRepo(tempRoot);
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", repoRoot);
        Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", null);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.True(result.IsAvailable);
            Assert.Equal(Path.Combine(repoRoot, ".venv", "Scripts", "python.exe"), result.FileName);
            Assert.Equal("-m reva_core --serve", result.Arguments);
            Assert.Equal(repoRoot, result.WorkingDirectory);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_FindsRepoBySearchingParentDirectories_FromOverriddenStartDirectory()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-test-" + Guid.NewGuid());
        Directory.CreateDirectory(tempRoot);
        var repoRoot = CreateFakeRepo(tempRoot);
        var nestedStart = Path.Combine(repoRoot, "desktop", "src", "Reva.Desktop", "bin");
        Directory.CreateDirectory(nestedStart);
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", nestedStart);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.True(result.IsAvailable);
            Assert.Equal(repoRoot, result.WorkingDirectory);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_ReturnsUnavailable_WhenNoRepoCheckoutFound()
    {
        var emptyDir = Path.Combine(Path.GetTempPath(), "reva-locator-empty-" + Guid.NewGuid());
        Directory.CreateDirectory(emptyDir);
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", emptyDir);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.False(result.IsAvailable);
            Assert.NotNull(result.FailureReason);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(emptyDir, recursive: true);
        }
    }

    [Fact]
    public void Resolve_ReturnsUnavailable_WhenRepoFoundButVenvMissing()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-test-" + Guid.NewGuid());
        var repoRoot = Path.Combine(tempRoot, "repo-no-venv");
        Directory.CreateDirectory(Path.Combine(repoRoot, "reva_core"));
        File.WriteAllText(Path.Combine(repoRoot, "pyproject.toml"), "[project]\n");
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", repoRoot);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.False(result.IsAvailable);
            Assert.Contains(".venv", result.FailureReason);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_PrefersExplicitPythonExeOverride()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-explicit-" + Guid.NewGuid());
        Directory.CreateDirectory(tempRoot);
        var pythonExe = Path.Combine(tempRoot, "python.exe");
        File.WriteAllText(pythonExe, "fake");
        Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", pythonExe);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.True(result.IsAvailable);
            Assert.Equal(pythonExe, result.FileName);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_ReturnsUnavailable_WhenExplicitPythonExeOverrideMissingFile()
    {
        Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", @"C:\does\not\exist\python.exe");
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.False(result.IsAvailable);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", null);
        }
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop\Reva.Desktop.sln --filter DeveloperModeCoreExecutableLocatorTests`
Expected: FAIL — types do not exist.

- [ ] **Step 3: Write minimal implementation**

```csharp
// desktop/src/Reva.Desktop/Services/CoreExecutableResolution.cs
namespace Reva.Desktop.Services;

/// <summary>How to launch REVA Core, or why that isn't currently possible.</summary>
public sealed record CoreExecutableResolution(
    bool IsAvailable, string? FileName, string? Arguments, string? WorkingDirectory, string? FailureReason)
{
    public static CoreExecutableResolution Available(string fileName, string arguments, string workingDirectory) =>
        new(true, fileName, arguments, workingDirectory, null);

    public static CoreExecutableResolution Unavailable(string reason) =>
        new(false, null, null, null, reason);
}
```

```csharp
// desktop/src/Reva.Desktop/Services/ICoreExecutableLocator.cs
namespace Reva.Desktop.Services;

/// <summary>
/// Resolves how to launch a local REVA Core process. Deliberately a
/// separate seam from <see cref="ICoreProcessLauncher"/>: this slice only
/// ships <see cref="DeveloperModeCoreExecutableLocator"/> (repo .venv);
/// a future packaged-app locator implements this same interface without
/// touching <see cref="RevaCoreLifecycle"/>.
/// </summary>
public interface ICoreExecutableLocator
{
    CoreExecutableResolution Resolve();
}
```

```csharp
// desktop/src/Reva.Desktop/Services/DeveloperModeCoreExecutableLocator.cs
namespace Reva.Desktop.Services;

/// <summary>
/// Developer-mode resolution only: finds a REVA repository checkout's
/// `.venv\Scripts\python.exe`. Never assume the current working
/// directory or hardcode a machine-specific path — search up from a
/// start directory for the repo markers (`pyproject.toml` + `reva_core\`),
/// bounded so a misconfigured environment fails fast instead of walking
/// to the filesystem root.
/// </summary>
public sealed class DeveloperModeCoreExecutableLocator : ICoreExecutableLocator
{
    public const string PythonExeEnvironmentVariable = "REVA_CORE_PYTHON_EXE";
    public const string RepoRootEnvironmentVariable = "REVA_CORE_REPO_ROOT";
    private const int MaxSearchDepth = 8;

    public CoreExecutableResolution Resolve()
    {
        var explicitPython = Environment.GetEnvironmentVariable(PythonExeEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(explicitPython))
        {
            if (!File.Exists(explicitPython))
            {
                return CoreExecutableResolution.Unavailable(
                    $"REVA_CORE_PYTHON_EXE points to a missing file: {explicitPython}");
            }

            var workingDirectory = Path.GetDirectoryName(explicitPython) ?? Directory.GetCurrentDirectory();
            return CoreExecutableResolution.Available(explicitPython, "-m reva_core --serve", workingDirectory);
        }

        var repoRootOverride = Environment.GetEnvironmentVariable(RepoRootEnvironmentVariable);
        var searchStart = string.IsNullOrWhiteSpace(repoRootOverride) ? AppContext.BaseDirectory : repoRootOverride;

        var repoRoot = FindRepoRoot(searchStart);
        if (repoRoot is null)
        {
            return CoreExecutableResolution.Unavailable(
                "Could not locate a REVA repository checkout with a .venv Python environment. " +
                "Set REVA_CORE_PYTHON_EXE or REVA_CORE_REPO_ROOT to point at one.");
        }

        var pythonExe = Path.Combine(repoRoot, ".venv", "Scripts", "python.exe");
        if (!File.Exists(pythonExe))
        {
            return CoreExecutableResolution.Unavailable(
                $"Found a REVA repository at '{repoRoot}' but .venv\\Scripts\\python.exe is missing. " +
                "Create the virtual environment first.");
        }

        return CoreExecutableResolution.Available(pythonExe, "-m reva_core --serve", repoRoot);
    }

    private static string? FindRepoRoot(string startDirectory)
    {
        var current = Directory.Exists(startDirectory) ? new DirectoryInfo(startDirectory) : null;
        for (var depth = 0; depth < MaxSearchDepth && current is not null; depth++)
        {
            var marker = Path.Combine(current.FullName, "pyproject.toml");
            var coreDir = Path.Combine(current.FullName, "reva_core");
            if (File.Exists(marker) && Directory.Exists(coreDir))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        return null;
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop\Reva.Desktop.sln --filter DeveloperModeCoreExecutableLocatorTests`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/CoreExecutableResolution.cs desktop/src/Reva.Desktop/Services/ICoreExecutableLocator.cs desktop/src/Reva.Desktop/Services/DeveloperModeCoreExecutableLocator.cs desktop/tests/Reva.Desktop.Tests/Unit/DeveloperModeCoreExecutableLocatorTests.cs
git commit -m "feat(desktop): add developer-mode Core executable locator"
```

---

### Task 3: Core process launcher

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/ICoreProcessHandle.cs`
- Create: `desktop/src/Reva.Desktop/Services/ICoreProcessLauncher.cs`
- Create: `desktop/src/Reva.Desktop/Services/CoreProcessLauncher.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/CoreProcessLauncherTests.cs`

**Interfaces:**
- Consumes: `CoreExecutableResolution` (Task 2).
- Produces: `ICoreProcessLauncher.Launch(CoreExecutableResolution resolution, string dataDirectory, int port) -> ICoreProcessHandle`; `ICoreProcessHandle : IDisposable { bool HasExited; int? ExitCode; }`.

- [ ] **Step 1: Write the failing tests**

```csharp
// desktop/tests/Reva.Desktop.Tests/Unit/CoreProcessLauncherTests.cs
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class CoreProcessLauncherTests
{
    // Uses cmd.exe, never python.exe: this test verifies CoreProcessLauncher's
    // *mechanics* (start, environment, no-window, exit tracking), not Core
    // resolution — that is DeveloperModeCoreExecutableLocatorTests's job.
    private static CoreExecutableResolution CmdResolution(string arguments) =>
        CoreExecutableResolution.Available(
            Environment.ExpandEnvironmentVariables(@"%WINDIR%\System32\cmd.exe"),
            arguments,
            Path.GetTempPath());

    [Fact]
    public void Launch_StartsProcess_AndHasExitedIsFalseImmediately()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c ping -n 3 127.0.0.1 >nul"), Path.GetTempPath(), 18756);

        Assert.False(handle.HasExited);
    }

    [Fact]
    public async Task Launch_HasExitedBecomesTrue_AfterProcessExits()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c exit 0"), Path.GetTempPath(), 18756);

        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!handle.HasExited && DateTime.UtcNow < deadline)
        {
            await Task.Delay(50);
        }

        Assert.True(handle.HasExited);
        Assert.Equal(0, handle.ExitCode);
    }

    [Fact]
    public async Task Launch_ExitCodeReflectsNonZeroExit()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c exit 7"), Path.GetTempPath(), 18756);

        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!handle.HasExited && DateTime.UtcNow < deadline)
        {
            await Task.Delay(50);
        }

        Assert.Equal(7, handle.ExitCode);
    }

    [Fact]
    public void Launch_Throws_WhenResolutionUnavailable()
    {
        var launcher = new CoreProcessLauncher();
        var unavailable = CoreExecutableResolution.Unavailable("no repo found");

        Assert.Throws<InvalidOperationException>(() => launcher.Launch(unavailable, Path.GetTempPath(), 18756));
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop\Reva.Desktop.sln --filter CoreProcessLauncherTests`
Expected: FAIL — types do not exist.

- [ ] **Step 3: Write minimal implementation**

```csharp
// desktop/src/Reva.Desktop/Services/ICoreProcessHandle.cs
namespace Reva.Desktop.Services;

/// <summary>A launched Core process. Never exposes the token or command
/// line — only exit-state, which the lifecycle needs for reconnect decisions.</summary>
public interface ICoreProcessHandle : IDisposable
{
    bool HasExited { get; }

    int? ExitCode { get; }
}
```

```csharp
// desktop/src/Reva.Desktop/Services/ICoreProcessLauncher.cs
namespace Reva.Desktop.Services;

public interface ICoreProcessLauncher
{
    /// <summary>Starts Core. <paramref name="dataDirectory"/> and
    /// <paramref name="port"/> are passed as REVA_DATA_DIR/REVA_API_PORT
    /// environment variables only — never as command-line arguments, and
    /// never the bearer token (Core generates it itself, after startup;
    /// Desktop never has a token to pass at launch time).</summary>
    ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port);
}
```

```csharp
// desktop/src/Reva.Desktop/Services/CoreProcessLauncher.cs
using System.Diagnostics;
using System.Globalization;

namespace Reva.Desktop.Services;

public sealed class CoreProcessLauncher : ICoreProcessLauncher
{
    public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
    {
        if (!resolution.IsAvailable)
        {
            throw new InvalidOperationException($"Cannot launch REVA Core: {resolution.FailureReason}");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = resolution.FileName,
            Arguments = resolution.Arguments,
            WorkingDirectory = resolution.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        // Inherits the current process environment (ProcessStartInfo.Environment
        // is pre-populated from it); only override what Desktop must control so
        // it agrees with Core on data directory and port. Everything else
        // (REVA_ASSISTANT_ORCHESTRATOR, REVA_ADK_MODEL, ...) passes through
        // untouched if the developer already set it before launching Desktop.
        startInfo.Environment["REVA_DATA_DIR"] = dataDirectory;
        startInfo.Environment["REVA_API_PORT"] = port.ToString(CultureInfo.InvariantCulture);

        var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        // Output/error are discarded, not logged: Core's stdout/stderr could
        // in principle contain data an operator wouldn't want in a Desktop
        // log file. Redirecting (rather than leaving un-redirected) is still
        // required so CreateNoWindow doesn't leave the child writing to a
        // closed console handle.
        process.OutputDataReceived += static (_, _) => { };
        process.ErrorDataReceived += static (_, _) => { };

        if (!process.Start())
        {
            throw new InvalidOperationException("Failed to start the REVA Core process.");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        return new CoreProcessHandle(process);
    }

    private sealed class CoreProcessHandle : ICoreProcessHandle
    {
        private readonly Process _process;

        public CoreProcessHandle(Process process) => _process = process;

        public bool HasExited => _process.HasExited;

        public int? ExitCode => _process.HasExited ? _process.ExitCode : null;

        public void Dispose() => _process.Dispose();
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop\Reva.Desktop.sln --filter CoreProcessLauncherTests`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/ICoreProcessHandle.cs desktop/src/Reva.Desktop/Services/ICoreProcessLauncher.cs desktop/src/Reva.Desktop/Services/CoreProcessLauncher.cs desktop/tests/Reva.Desktop.Tests/Unit/CoreProcessLauncherTests.cs
git commit -m "feat(desktop): add real Core process launcher"
```

---

### Task 4: `RevaCoreLifecycle` state machine — probe, attach, launch, wait

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/CoreLifecycleState.cs`
- Create: `desktop/src/Reva.Desktop/Services/IRevaCoreLifecycle.cs`
- Create: `desktop/src/Reva.Desktop/Services/RevaCoreLifecycle.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreLifecycleTests.cs`

**Interfaces:**
- Consumes: `IRevaCoreClient.GetHealthAsync` (existing), `ILocalTokenProvider.GetTokenAsync` (existing), `ICoreExecutableLocator.Resolve` (Task 2), `ICoreProcessLauncher.Launch` (Task 3), `DesktopConfiguration` (existing, for `CoreBaseUrl.Port` and `CoreDataDirectory`).
- Produces:
  ```csharp
  public enum CoreLifecycleState { Starting, Connected, Unavailable, AuthorizationUnavailable }

  public interface IRevaCoreLifecycle
  {
      CoreLifecycleState State { get; }
      string StatusText { get; }
      event EventHandler? StateChanged;
      Task StartAsync(CancellationToken cancellationToken = default);
      void StopMonitoring();
  }
  ```
  `RevaCoreLifecycle` constructor: `RevaCoreLifecycle(IRevaCoreClient coreClient, ILocalTokenProvider tokenProvider, ICoreExecutableLocator executableLocator, ICoreProcessLauncher processLauncher, DesktopConfiguration configuration, Func<TimeSpan, CancellationToken, Task>? delay = null)`. `delay` defaults to `Task.Delay` and is the seam Task 5's reconnect-loop tests use to avoid real waiting.

This task covers the non-reconnect part of the state machine: an explicit, bounded startup sequence. Task 5 adds the background monitor loop and duplicate-launch guard on top of the same class.

- [ ] **Step 1: Write the failing tests (startup sequence only)**

```csharp
// desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreLifecycleTests.cs
using Reva.Desktop.Contracts;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class RevaCoreLifecycleTests
{
    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly Queue<CoreResult<HealthStatus>> _healthResults;

        public FakeCoreClient(params CoreResult<HealthStatus>[] healthResults) =>
            _healthResults = new Queue<CoreResult<HealthStatus>>(healthResults);

        public int HealthCallCount { get; private set; }

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default)
        {
            HealthCallCount++;
            var result = _healthResults.Count > 1 ? _healthResults.Dequeue() : _healthResults.Peek();
            return Task.FromResult(result);
        }

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query, int limit, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }

    private sealed class FakeTokenProvider : ILocalTokenProvider
    {
        private readonly Queue<TokenLoadResult> _results;

        public FakeTokenProvider(params TokenLoadResult[] results) => _results = new Queue<TokenLoadResult>(results);

        public Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default)
        {
            var result = _results.Count > 1 ? _results.Dequeue() : _results.Peek();
            return Task.FromResult(result);
        }
    }

    private sealed class FakeExecutableLocator : ICoreExecutableLocator
    {
        private readonly CoreExecutableResolution _result;

        public FakeExecutableLocator(CoreExecutableResolution result) => _result = result;

        public int ResolveCallCount { get; private set; }

        public CoreExecutableResolution Resolve()
        {
            ResolveCallCount++;
            return _result;
        }
    }

    private sealed class FakeProcessHandle : ICoreProcessHandle
    {
        public bool HasExited { get; set; }
        public int? ExitCode { get; set; }
        public void Dispose() { }
    }

    private sealed class FakeProcessLauncher : ICoreProcessLauncher
    {
        public int LaunchCallCount { get; private set; }
        public FakeProcessHandle LastHandle { get; } = new();

        public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
        {
            LaunchCallCount++;
            return LastHandle;
        }
    }

    private static DesktopConfiguration Configuration() =>
        new(new Uri("http://127.0.0.1:18756/"), Path.Combine(Path.GetTempPath(), "reva-lifecycle-test"), TimeSpan.FromSeconds(5));

    private static HealthStatus Healthy() => new(1, "healthy", 1, DateTimeOffset.UtcNow);

    private static CoreExecutableResolution AvailableResolution() =>
        CoreExecutableResolution.Available("python.exe", "-m reva_core --serve", Path.GetTempPath());

    [Fact]
    public async Task StartAsync_AttachesWithoutLaunching_WhenCoreAlreadyHealthy()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration());

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);
        Assert.Equal(0, launcher.LaunchCallCount);
    }

    [Fact]
    public async Task StartAsync_LaunchesCore_WhenNoneReachable_ThenReachesConnected()
    {
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);
        Assert.Equal(1, launcher.LaunchCallCount);
    }

    [Fact]
    public async Task StartAsync_BecomesUnavailable_WhenExecutableCannotBeResolved()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"));
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Unavailable()),
            new FakeExecutableLocator(CoreExecutableResolution.Unavailable("no repo found")),
            new FakeProcessLauncher(), Configuration(), delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Unavailable, lifecycle.State);
    }

    [Fact]
    public async Task StartAsync_BecomesUnavailable_WithoutLaunching_WhenPortHeldByNonReva()
    {
        // CoreInvalidResponse is what RevaCoreClient normalizes a 200
        // response with unparseable JSON to (see RevaCoreClient.InterpretResponseAsync)
        // — a responding-but-not-REVA listener on the configured port.
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreInvalidResponse, "unexpected response"));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Unavailable()),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Unavailable, lifecycle.State);
        Assert.Equal(0, launcher.LaunchCallCount);
    }

    [Fact]
    public async Task StartAsync_BecomesAuthorizationUnavailable_WhenHealthyButTokenNeverAppears()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Unavailable()),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.AuthorizationUnavailable, lifecycle.State);
    }

    [Fact]
    public async Task StartAsync_RaisesStateChanged_OnEveryTransition()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration());
        var raisedCount = 0;
        lifecycle.StateChanged += (_, _) => raisedCount++;

        await lifecycle.StartAsync();

        Assert.True(raisedCount > 0);
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop\Reva.Desktop.sln --filter RevaCoreLifecycleTests`
Expected: FAIL — types do not exist.

- [ ] **Step 3: Write minimal implementation**

```csharp
// desktop/src/Reva.Desktop/Services/CoreLifecycleState.cs
namespace Reva.Desktop.Services;

/// <summary>The 4 UI-truthful states Desktop can be in with respect to Core.</summary>
public enum CoreLifecycleState
{
    Starting,
    Connected,
    Unavailable,
    AuthorizationUnavailable,
}
```

```csharp
// desktop/src/Reva.Desktop/Services/IRevaCoreLifecycle.cs
namespace Reva.Desktop.Services;

public interface IRevaCoreLifecycle
{
    CoreLifecycleState State { get; }

    /// <summary>The exact UI-facing text for <see cref="State"/> — one of
    /// "Starting Core…", "Core Connected", "Core Unavailable",
    /// "REVA authorization unavailable".</summary>
    string StatusText { get; }

    event EventHandler? StateChanged;

    Task StartAsync(CancellationToken cancellationToken = default);

    void StopMonitoring();
}
```

```csharp
// desktop/src/Reva.Desktop/Services/RevaCoreLifecycle.cs
namespace Reva.Desktop.Services;

/// <summary>
/// Owns Core process lifecycle only — no memory/policy/agent semantics.
/// StartAsync: probe an existing Core first; attach if healthy; otherwise
/// resolve and launch a local Core, then wait for health and for
/// local_auth_token to appear. See Task 5 (this same class) for the
/// background reconnect monitor and duplicate-launch guard.
/// </summary>
public sealed class RevaCoreLifecycle : IRevaCoreLifecycle, IDisposable
{
    private static readonly TimeSpan HealthPollInterval = TimeSpan.FromMilliseconds(250);
    private static readonly TimeSpan HealthTimeout = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan TokenPollInterval = TimeSpan.FromMilliseconds(200);
    private static readonly TimeSpan TokenTimeout = TimeSpan.FromSeconds(10);

    private readonly IRevaCoreClient _coreClient;
    private readonly ILocalTokenProvider _tokenProvider;
    private readonly ICoreExecutableLocator _executableLocator;
    private readonly ICoreProcessLauncher _processLauncher;
    private readonly DesktopConfiguration _configuration;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;

    private ICoreProcessHandle? _ownedProcess;

    public RevaCoreLifecycle(
        IRevaCoreClient coreClient,
        ILocalTokenProvider tokenProvider,
        ICoreExecutableLocator executableLocator,
        ICoreProcessLauncher processLauncher,
        DesktopConfiguration configuration,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _coreClient = coreClient;
        _tokenProvider = tokenProvider;
        _executableLocator = executableLocator;
        _processLauncher = processLauncher;
        _configuration = configuration;
        _delay = delay ?? ((span, token) => Task.Delay(span, token));
    }

    public CoreLifecycleState State { get; private set; } = CoreLifecycleState.Starting;

    public string StatusText { get; private set; } = "Starting Core…";

    public event EventHandler? StateChanged;

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        SetState(CoreLifecycleState.Starting);

        var probe = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
        if (probe.IsSuccess)
        {
            await FinishConnectingAsync(cancellationToken).ConfigureAwait(true);
            return;
        }

        if (probe.Error!.Kind != CoreErrorKind.CoreUnavailable && probe.Error.Kind != CoreErrorKind.CoreTimeout)
        {
            // Something responded on the configured port but not with a
            // shape RevaCoreClient recognizes as REVA Core (CoreInvalidResponse),
            // or Core rejected auth unexpectedly at /health (which never
            // requires auth) — either way, fail safe: never launch a second
            // process against an already-occupied port (rule: never kill or
            // collide with a non-REVA listener).
            SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
            return;
        }

        var resolution = _executableLocator.Resolve();
        if (!resolution.IsAvailable)
        {
            DesktopLogger.Warn($"REVA Core executable resolution failed: {resolution.FailureReason}");
            SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
            return;
        }

        _ownedProcess = _processLauncher.Launch(resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);

        var becameHealthy = await WaitForHealthAsync(cancellationToken).ConfigureAwait(true);
        if (!becameHealthy)
        {
            SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
            return;
        }

        await FinishConnectingAsync(cancellationToken).ConfigureAwait(true);
    }

    public void StopMonitoring()
    {
        // Task 5 fills this in with real monitor-loop cancellation.
    }

    public void Dispose() => _ownedProcess?.Dispose();

    private async Task FinishConnectingAsync(CancellationToken cancellationToken)
    {
        var tokenAvailable = await WaitForTokenAsync(cancellationToken).ConfigureAwait(true);
        SetState(
            tokenAvailable ? CoreLifecycleState.Connected : CoreLifecycleState.AuthorizationUnavailable,
            tokenAvailable ? "Core Connected" : "REVA authorization unavailable");
    }

    private async Task<bool> WaitForHealthAsync(CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + HealthTimeout;
        while (DateTimeOffset.UtcNow < deadline)
        {
            var result = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
            if (result.IsSuccess)
            {
                return true;
            }

            await _delay(HealthPollInterval, cancellationToken).ConfigureAwait(true);
        }

        return false;
    }

    private async Task<bool> WaitForTokenAsync(CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + TokenTimeout;
        while (DateTimeOffset.UtcNow < deadline)
        {
            var result = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(true);
            if (result.IsAvailable)
            {
                return true;
            }

            await _delay(TokenPollInterval, cancellationToken).ConfigureAwait(true);
        }

        return false;
    }

    private void SetState(CoreLifecycleState state, string? statusText = null)
    {
        State = state;
        StatusText = statusText ?? state switch
        {
            CoreLifecycleState.Starting => "Starting Core…",
            CoreLifecycleState.Connected => "Core Connected",
            CoreLifecycleState.Unavailable => "Core Unavailable",
            CoreLifecycleState.AuthorizationUnavailable => "REVA authorization unavailable",
            _ => "Starting Core…",
        };
        StateChanged?.Invoke(this, EventArgs.Empty);
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop\Reva.Desktop.sln --filter RevaCoreLifecycleTests`
Expected: PASS (all 6 tests). Note: `StartAsync_LaunchesCore_WhenNoneReachable_ThenReachesConnected` relies on `FakeCoreClient` returning its 2nd queued result once its 1-item-remaining queue is drained (`_healthResults.Count > 1 ? Dequeue() : Peek()`) — the first `GetHealthAsync` call (initial probe) dequeues the failure, every call after (inside `WaitForHealthAsync`) peeks the success repeatedly.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/CoreLifecycleState.cs desktop/src/Reva.Desktop/Services/IRevaCoreLifecycle.cs desktop/src/Reva.Desktop/Services/RevaCoreLifecycle.cs desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreLifecycleTests.cs
git commit -m "feat(desktop): add RevaCoreLifecycle startup state machine"
```

---

### Task 5: Duplicate-launch guard and reconnect monitor

**Files:**
- Modify: `desktop/src/Reva.Desktop/Services/RevaCoreLifecycle.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreLifecycleTests.cs`

**Interfaces:**
- Produces (additions to `RevaCoreLifecycle`): a background monitor started at the end of a successful `StartAsync` (state `Connected` or `AuthorizationUnavailable` — both mean Core is up), stopped by `StopMonitoring()` or `Dispose()`. Uses the same injected `_delay` seam as Task 4 so tests control iteration without real waiting.
- A process-scoped `System.Threading.Mutex` named `Local\Reva.Desktop.CoreLifecycle.Start` guards the launch decision itself, so two Desktop instances starting at the same moment don't both decide "unreachable, launch" and race two `python -m reva_core --serve` processes onto the same port.

- [ ] **Step 1: Write the failing tests**

Add to `RevaCoreLifecycleTests.cs`:

```csharp
    [Fact]
    public async Task StartAsync_SecondConcurrentLifecycle_DoesNotLaunchASecondProcess()
    {
        // Simulates two Desktop instances starting at once: both see
        // CoreUnavailable on their first probe. The first to acquire the
        // start-lock launches; the second must re-probe after releasing
        // the lock and attach to what the first one started, never launch
        // its own second process.
        var sharedLaunchCount = 0;
        var client1 = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var client2 = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var launcher1 = new CountingLauncher(() => sharedLaunchCount++);
        var launcher2 = new CountingLauncher(() => sharedLaunchCount++);
        var lifecycle1 = new RevaCoreLifecycle(
            client1, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher1, Configuration(),
            delay: (_, _) => Task.CompletedTask);
        var lifecycle2 = new RevaCoreLifecycle(
            client2, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher2, Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await Task.WhenAll(lifecycle1.StartAsync(), lifecycle2.StartAsync());

        Assert.Equal(1, sharedLaunchCount);
    }

    private sealed class CountingLauncher : ICoreProcessLauncher
    {
        private readonly Action _onLaunch;
        public CountingLauncher(Action onLaunch) => _onLaunch = onLaunch;
        public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
        {
            _onLaunch();
            return new FakeProcessHandle();
        }
    }

    [Fact]
    public async Task Monitor_RelaunchesOwnedProcess_AfterItExitsUnexpectedly()
    {
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var firstHandle = new FakeProcessHandle();
        var launcher = new SequencedLauncher(firstHandle, new FakeProcessHandle());
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);
        await lifecycle.StartAsync();
        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);

        firstHandle.HasExited = true;
        firstHandle.ExitCode = 1;
        client.QueueHealthFailureThenSuccess();
        await lifecycle.RunMonitorIterationAsync();

        Assert.Equal(2, launcher.LaunchCallCount);
        lifecycle.StopMonitoring();
    }

    private sealed class SequencedLauncher : ICoreProcessLauncher
    {
        private readonly Queue<ICoreProcessHandle> _handles;
        public int LaunchCallCount { get; private set; }
        public SequencedLauncher(params ICoreProcessHandle[] handles) => _handles = new Queue<ICoreProcessHandle>(handles);
        public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
        {
            LaunchCallCount++;
            return _handles.Count > 1 ? _handles.Dequeue() : _handles.Peek();
        }
    }
```

Extend `FakeCoreClient` in the same file with a helper the relaunch test above uses:

```csharp
        public void QueueHealthFailureThenSuccess()
        {
            _healthResults.Clear();
            _healthResults.Enqueue(CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"));
            _healthResults.Enqueue(CoreResult<HealthStatus>.Success(Healthy()));
        }
```
(`_healthResults` must change from `readonly` to a mutable field reference to support `.Clear()`/`.Enqueue()` from this helper — keep the `Queue<T>` field itself non-`readonly`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop\Reva.Desktop.sln --filter RevaCoreLifecycleTests`
Expected: FAIL — `RunMonitorIterationAsync` does not exist; duplicate-launch test likely also launches 2 (no guard yet).

- [ ] **Step 3: Extend `RevaCoreLifecycle` with the guard and monitor**

Add to `RevaCoreLifecycle.cs` (inside the class):

```csharp
    private const string StartLockName = @"Local\Reva.Desktop.CoreLifecycle.Start";
    private static readonly TimeSpan StartLockTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan MonitorInterval = TimeSpan.FromSeconds(5);
    private const int MaxRelaunchAttempts = 3;

    private CancellationTokenSource? _monitorCts;
    private int _relaunchAttempts;
```

Replace the `resolution.IsAvailable` launch block inside `StartAsync` (between the port-occupied check and `WaitForHealthAsync`) with a mutex-guarded version:

```csharp
        using var startLock = new Mutex(initiallyOwned: false, StartLockName);
        var acquired = startLock.WaitOne(StartLockTimeout);
        try
        {
            // Re-probe after acquiring the lock: whoever got here first may
            // have already finished launching Core while this instance was
            // waiting on the mutex.
            if (acquired)
            {
                var reprobe = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
                if (reprobe.IsSuccess)
                {
                    await FinishConnectingAsync(cancellationToken).ConfigureAwait(true);
                    return;
                }
            }

            var resolution = _executableLocator.Resolve();
            if (!resolution.IsAvailable)
            {
                DesktopLogger.Warn($"REVA Core executable resolution failed: {resolution.FailureReason}");
                SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
                return;
            }

            _ownedProcess = _processLauncher.Launch(
                resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
        }
        finally
        {
            if (acquired)
            {
                startLock.ReleaseMutex();
            }
        }
```

(This replaces the earlier plain `var resolution = _executableLocator.Resolve(); ...; _ownedProcess = _processLauncher.Launch(...);` block from Task 4 — same outcome on the non-contended path, now additionally safe under two-instance contention.)

At the end of `FinishConnectingAsync`, after `SetState(...)`, start the monitor for both terminal-but-alive states:

```csharp
        if (tokenAvailable)
        {
            StartMonitor();
        }
```

Add the monitor loop and the test-visible single-iteration method:

```csharp
    private void StartMonitor()
    {
        _monitorCts?.Cancel();
        _monitorCts = new CancellationTokenSource();
        _ = RunMonitorLoopAsync(_monitorCts.Token);
    }

    public void StopMonitoring()
    {
        _monitorCts?.Cancel();
        _monitorCts = null;
    }

    private async Task RunMonitorLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            await _delay(MonitorInterval, cancellationToken).ConfigureAwait(true);
            if (cancellationToken.IsCancellationRequested)
            {
                return;
            }

            await RunMonitorIterationAsync().ConfigureAwait(true);
        }
    }

    /// <summary>One reconnect check. Public so tests can drive a single
    /// iteration deterministically instead of racing the real timer loop.</summary>
    public async Task RunMonitorIterationAsync()
    {
        var health = await _coreClient.GetHealthAsync().ConfigureAwait(true);
        if (health.IsSuccess)
        {
            _relaunchAttempts = 0;
            if (State != CoreLifecycleState.Connected)
            {
                await FinishConnectingAsync(CancellationToken.None).ConfigureAwait(true);
            }
            return;
        }

        SetState(CoreLifecycleState.Unavailable, "Core Unavailable");

        // Only relaunch a process this instance owns and watched exit —
        // never touch a Core this instance merely attached to (rule: never
        // kill or replace a process Desktop didn't start).
        if (_ownedProcess is { HasExited: true } && _relaunchAttempts < MaxRelaunchAttempts)
        {
            _relaunchAttempts++;
            var resolution = _executableLocator.Resolve();
            if (resolution.IsAvailable)
            {
                _ownedProcess.Dispose();
                _ownedProcess = _processLauncher.Launch(
                    resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
            }
        }
    }
```

Remove the now-superseded standalone `public void StopMonitoring()` stub added in Task 4 (replaced by the implementation above — keep only one definition).

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop\Reva.Desktop.sln --filter RevaCoreLifecycleTests`
Expected: PASS (all 8 tests, including the two new ones).

- [ ] **Step 5: Run the full C# test project to check for regressions**

Run: `dotnet test desktop\Reva.Desktop.sln --configuration Release`
Expected: PASS, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/RevaCoreLifecycle.cs desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreLifecycleTests.cs
git commit -m "feat(desktop): add duplicate-launch guard and Core reconnect monitor"
```

---

### Task 6: Wire `RevaCoreLifecycle` into app startup and `ShellViewModel`

**Files:**
- Modify: `desktop/src/Reva.Desktop/App.xaml.cs`
- Modify: `desktop/src/Reva.Desktop/ViewModels/ShellViewModel.cs`
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/ShellViewModelTests.cs`

**Interfaces:**
- Consumes: `IRevaCoreLifecycle` (Task 5).
- Produces: `ShellViewModel(IRevaCoreLifecycle lifecycle)` — replaces the old `ShellViewModel(IRevaCoreClient coreClient)` constructor. `IsCoreConnected` and `CoreStatusText` keep their existing names/types (no breaking change to `MainWindow.xaml`'s bindings), now derived from the lifecycle's state instead of a one-shot health call.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `desktop/tests/Reva.Desktop.Tests/Unit/ShellViewModelTests.cs`:

```csharp
using Reva.Desktop.Services;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class ShellViewModelTests
{
    private sealed class FakeLifecycle : IRevaCoreLifecycle
    {
        public CoreLifecycleState State { get; set; } = CoreLifecycleState.Starting;
        public string StatusText { get; set; } = "Starting Core…";
        public event EventHandler? StateChanged;
        public Task StartAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public void StopMonitoring() { }

        public void Raise(CoreLifecycleState state, string statusText)
        {
            State = state;
            StatusText = statusText;
            StateChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    [Fact]
    public void InitialState_IsStartingAndNotConnected()
    {
        var viewModel = new ShellViewModel(new FakeLifecycle());

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("Starting Core…", viewModel.CoreStatusText);
    }

    [Fact]
    public void ReflectsLifecycle_Connected()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);

        lifecycle.Raise(CoreLifecycleState.Connected, "Core Connected");

        Assert.True(viewModel.IsCoreConnected);
        Assert.Equal("Core Connected", viewModel.CoreStatusText);
    }

    [Fact]
    public void ReflectsLifecycle_Unavailable()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);

        lifecycle.Raise(CoreLifecycleState.Unavailable, "Core Unavailable");

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("Core Unavailable", viewModel.CoreStatusText);
    }

    [Fact]
    public void ReflectsLifecycle_AuthorizationUnavailable()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);

        lifecycle.Raise(CoreLifecycleState.AuthorizationUnavailable, "REVA authorization unavailable");

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("REVA authorization unavailable", viewModel.CoreStatusText);
        Assert.Equal(CoreLifecycleState.AuthorizationUnavailable, viewModel.LifecycleState);
    }

    [Fact]
    public void RaisesPropertyChanged_OnLifecycleTransition()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);
        var raised = new List<string?>();
        viewModel.PropertyChanged += (_, e) => raised.Add(e.PropertyName);

        lifecycle.Raise(CoreLifecycleState.Connected, "Core Connected");

        Assert.Contains(nameof(ShellViewModel.IsCoreConnected), raised);
        Assert.Contains(nameof(ShellViewModel.CoreStatusText), raised);
        Assert.Contains(nameof(ShellViewModel.LifecycleState), raised);
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop\Reva.Desktop.sln --filter ShellViewModelTests`
Expected: FAIL — `ShellViewModel(IRevaCoreLifecycle)` constructor and `LifecycleState` property do not exist.

- [ ] **Step 3: Rewrite `ShellViewModel`**

Replace `desktop/src/Reva.Desktop/ViewModels/ShellViewModel.cs` entirely:

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Backs the main window's honest Core-connection status. Sourced from
/// <see cref="IRevaCoreLifecycle"/>'s state machine (probe/launch/health/
/// token/reconnect) — this class does no Core I/O of its own.
///
/// Deliberately has no WinUI/XAML type dependency (no Brush, no Color) so
/// it can be unit-tested from a plain class library test project without
/// pulling in the WinUI XAML build pipeline. Color/visual mapping lives
/// in the View (MainWindow.xaml.cs).
/// </summary>
public sealed class ShellViewModel : ObservableObject
{
    private readonly IRevaCoreLifecycle _lifecycle;

    public ShellViewModel(IRevaCoreLifecycle lifecycle)
    {
        _lifecycle = lifecycle;
        _lifecycle.StateChanged += OnLifecycleStateChanged;
    }

    public CoreLifecycleState LifecycleState => _lifecycle.State;

    public bool IsCoreConnected => _lifecycle.State == CoreLifecycleState.Connected;

    public string CoreStatusText => _lifecycle.StatusText;

    private void OnLifecycleStateChanged(object? sender, EventArgs e)
    {
        OnPropertyChanged(nameof(LifecycleState));
        OnPropertyChanged(nameof(IsCoreConnected));
        OnPropertyChanged(nameof(CoreStatusText));
    }
}
```

Check `desktop/src/Reva.Desktop/ViewModels/ObservableObject.cs` for the exact protected member name used to raise `PropertyChanged` without a backing-field `SetProperty` call (it's used only via `SetProperty` elsewhere in the codebase) — if `ObservableObject` does not already expose a protected `OnPropertyChanged(string)` method, add one:

```csharp
    protected void OnPropertyChanged(string propertyName) =>
        PropertyChanged?.Invoke(this, new System.ComponentModel.PropertyChangedEventArgs(propertyName));
```

(Confirm this against the real file before assuming — `SetProperty` in the existing class almost certainly already calls a private equivalent; expose it as `protected` if it is currently `private`.)

- [ ] **Step 4: Update `App.xaml.cs` composition root**

Replace `desktop/src/Reva.Desktop/App.xaml.cs`'s `OnLaunched`:

```csharp
    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        var configuration = DesktopConfiguration.CreateDefault();
        var tokenProvider = new LocalTokenProvider(configuration);
        var httpClient = new System.Net.Http.HttpClient
        {
            BaseAddress = configuration.CoreBaseUrl,
            Timeout = configuration.RequestTimeout,
        };
        var coreClient = new RevaCoreClient(httpClient, tokenProvider);
        var lifecycle = new RevaCoreLifecycle(
            coreClient, tokenProvider, new DeveloperModeCoreExecutableLocator(), new CoreProcessLauncher(), configuration);

        _window = new MainWindow(coreClient, lifecycle);
        _window.Activate();

        // Deliberately started after Activate(), not awaited before it: the
        // window (and its "Starting Core…" initial state) must appear
        // immediately rather than leaving Windows showing nothing while
        // Core boots — confirmed necessary during manual smoke testing of
        // the equivalent one-shot health check in Slice 3.
        await lifecycle.StartAsync();
    }
```

Add `private IRevaCoreLifecycle? _lifecycle;` is not needed — `MainWindow` owns the `Shell` view model which owns the lifecycle reference via `ShellViewModel`; `App` does not need to keep it alive beyond the local variable's closure captured by `lifecycle.StartAsync()`'s continuation and `MainWindow`'s constructor — but to prevent the `RevaCoreLifecycle` (which implements `IDisposable`) from being garbage-collected while its background monitor task is still running, store it on `App`:

```csharp
    private Window? _window;
    private RevaCoreLifecycle? _lifecycle;
```

and assign `_lifecycle = lifecycle;` right after constructing it, before `_window = new MainWindow(...)`.

- [ ] **Step 5: Update `MainWindow` constructor and status-dot mapping**

Modify `desktop/src/Reva.Desktop/MainWindow.xaml.cs`:

```csharp
    public MainWindow(IRevaCoreClient coreClient, IRevaCoreLifecycle lifecycle)
    {
        InitializeComponent();
        Shell = new ShellViewModel(lifecycle);
        Assistant = new AssistantViewModel(coreClient);
        Memory = new MemoryViewModel(coreClient);
        Shell.PropertyChanged += OnShellPropertyChanged;
        ApplyStatusDotColor();
    }

    private void OnShellPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(ShellViewModel.LifecycleState))
        {
            ApplyStatusDotColor();
        }
    }

    private void ApplyStatusDotColor()
    {
        var color = Shell.LifecycleState switch
        {
            CoreLifecycleState.Connected => Colors.LimeGreen,
            CoreLifecycleState.Starting => Colors.Gold,
            CoreLifecycleState.AuthorizationUnavailable => Colors.OrangeRed,
            _ => Colors.Gray,
        };
        StatusDot.Fill = new SolidColorBrush(color);
    }
```

(Removes the now-obsolete `_ = Shell.RefreshCoreStatusAsync();` call and its explanatory comment — `RevaCoreLifecycle.StartAsync()` in `App.xaml.cs` is what drives status now, and `ShellViewModel` reacts to it via `StateChanged`, not a fire-and-forget health call of its own.)

- [ ] **Step 6: Run the full C# test suite**

Run: `dotnet build desktop\Reva.Desktop.sln --configuration Release` then `dotnet test desktop\Reva.Desktop.sln --configuration Release`
Expected: build succeeds, all tests PASS (including the 5 new `ShellViewModelTests`).

- [ ] **Step 7: Manual smoke test**

Run: launch `Reva.Desktop.exe` from a clean shell with no Core process running and `REVA_CORE_REPO_ROOT` unset (so the locator's `AppContext.BaseDirectory`-relative search finds the checkout naturally if running from a build under the repo, or set `REVA_CORE_REPO_ROOT=D:\Projects\Reva` explicitly for this manual check).
Expected: window shows "Starting Core…", then (after the Python process boots) "Core Connected", with no PowerShell/manual `python -m reva_core` step.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/Reva.Desktop/App.xaml.cs desktop/src/Reva.Desktop/ViewModels/ShellViewModel.cs desktop/src/Reva.Desktop/ViewModels/ObservableObject.cs desktop/src/Reva.Desktop/MainWindow.xaml.cs desktop/tests/Reva.Desktop.Tests/Unit/ShellViewModelTests.cs
git commit -m "feat(desktop): wire RevaCoreLifecycle into app startup and Shell status"
```

---

## Self-Review Notes (already applied above)

- Spec coverage: automatic startup (Task 6), stable data directory (Task 1), developer-mode resolution encapsulated behind `ICoreExecutableLocator` without a packaged-mode implementation (Task 2, per scope constraint), duplicate-process prevention (Task 5 mutex), port-occupied-by-non-REVA fail-safe (Task 4), never-kill-arbitrary-process (Task 5 only relaunches `_ownedProcess`), reconnect (Task 5 monitor), token never logged/never on command line (Task 3 — `Arguments` is a fixed literal; `DesktopLogger` redaction is defense-in-depth, not relied on as primary control), truthful 4-state UI (Tasks 4 & 6).
- No placeholders: every step has literal code, not "add error handling" prose.
- Type consistency checked: `IRevaCoreLifecycle`/`RevaCoreLifecycle`/`CoreLifecycleState` names and members are identical across Tasks 4, 5, 6.
