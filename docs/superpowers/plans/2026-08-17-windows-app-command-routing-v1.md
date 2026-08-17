# Windows App-Command Routing v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before a composer message reaches the assistant, a deterministic local router recognizes a small set of app open/close commands and executes them through a restricted, allowlisted Windows process executor — never a shell, never arbitrary paths, never LLM-decided. Everything else (ordinary chat, unrecognized commands, unsupported app names) falls through to the existing assistant pipeline with zero behavior change.

**Architecture:** Two new interfaces (`ICommandRouter`, `IAppExecutor`) behind a fixed 7-entry allowlist table (`AppAllowlist`). `CommandRouter` owns text matching and a single-slot pending-confirmation state machine (30s expiry via injected `TimeProvider`); it never touches `Process`/`ProcessStartInfo` directly. `WindowsAppExecutor` is the only place that does — `Process.Start` with `UseShellExecute = true` for open, `Process.GetProcessesByName` + `CloseMainWindow()` (never `Kill()`) for close. `AssistantViewModel.SendMessageCoreAsync` gets one new call, inserted after the existing user-message-append/composer-clear and before the existing `_coreClient.SendMessageAsync` call — a `NotACommand` result falls through to that unmodified code exactly as today.

**Tech Stack:** C# / .NET (net10.0-windows10.0.19041.0), `System.Diagnostics.Process`, `System.TimeProvider` (BCL, no new package), xUnit — same stack as the transcription-only voice slice this plan follows.

## Global Constraints

- No arbitrary executable paths — every `ProcessStartInfo.FileName` is one of 7 fixed literal strings baked into `AppAllowlist`, never derived from user text beyond an exact-alias lookup.
- No raw user input passed to `Process.Start` — `Arguments` is never set on any `ProcessStartInfo` this plan creates.
- No `cmd.exe`, `powershell.exe`, `pwsh.exe`, or script execution anywhere in the allowlist.
- No `Process.Kill()` anywhere — close uses `CloseMainWindow()` only.
- No elevation — `ProcessStartInfo.Verb` is never set to `"runas"`.
- No LLM-generated shell commands — the router runs entirely before the assistant is invoked for any recognized command; a `NotACommand` result is the *only* way a message reaches the assistant.
- Never closes REVA itself, security tools, system processes, or unknown apps — the close-capable set is a closed list of 5 named consumer apps (verified in Task 1); REVA's own process is never in it.
- Reject command chaining, pipes, redirection, and injection-like input — satisfied structurally: the captured argument must exactly equal a fixed alias string (case-insensitive match, then exact dictionary lookup) or the whole message is `NotACommand`.
- Log only a canonical action ID, app key, and fixed result code via `DesktopLogger.Info("command.state=... action=... app=... result=...")` — never the user's literal typed text, a file path, or an exception message.
- File Explorer and Windows Settings are open-only (no close command) — decided with user 2026-08-17, `explorer.exe`'s shell-adjacent `CloseMainWindow` behavior is out of scope for v1.
- Voice transcription, typed chat's non-command path, memory, and TTS behavior are unchanged — verified per-task by running the full existing suite, not just the new command-routing tests.
- Desktop-only — no `reva_core`/Python changes anywhere in this plan.

---

## File Structure

- `desktop/src/Reva.Desktop/Services/AppDescriptor.cs` — **new**. The allowlist entry record.
- `desktop/src/Reva.Desktop/Services/AppAllowlist.cs` — **new**. The fixed 7-entry table + alias lookup.
- `desktop/src/Reva.Desktop/Services/IAppExecutor.cs` — **new**. `IAppExecutor` interface + `AppCloseOutcome` enum.
- `desktop/src/Reva.Desktop/Services/ICommandRouter.cs` — **new**. `ICommandRouter` interface + `CommandOutcome` enum + `CommandRouteResult` record.
- `desktop/src/Reva.Desktop/Services/CommandRouter.cs` — **new**. Text matching + pending-confirmation state machine. No `Process`/OS types.
- `desktop/src/Reva.Desktop/Services/WindowsAppExecutor.cs` — **new**. The only file that touches `System.Diagnostics.Process`.
- `desktop/src/Reva.Desktop/Services/NullCommandRouter.cs` — **new**. Null-object default (mirrors `UnavailableVoiceDevice`).
- `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs` — **modify**. New optional ctor parameter, one new call site inside `SendMessageCoreAsync`.
- `desktop/src/Reva.Desktop/MainWindow.xaml.cs` — **modify**. Thread the router through the constructor.
- `desktop/src/Reva.Desktop/App.xaml.cs` — **modify**. Construct `WindowsAppExecutor`/`CommandRouter`.
- `desktop/tests/Reva.Desktop.Tests/Unit/AppAllowlistTests.cs` — **new**.
- `desktop/tests/Reva.Desktop.Tests/Unit/CommandRouterTests.cs` — **new**. The bulk of test coverage.
- `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs` — **modify**. New command-routing integration tests, added alongside (not replacing) the existing tests.

---

### Task 1: Types + allowlist table

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/AppDescriptor.cs`
- Create: `desktop/src/Reva.Desktop/Services/AppAllowlist.cs`
- Create: `desktop/src/Reva.Desktop/Services/IAppExecutor.cs`
- Create: `desktop/src/Reva.Desktop/Services/ICommandRouter.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/AppAllowlistTests.cs`

**Interfaces:**
- Produces: `AppDescriptor(string Key, string DisplayName, IReadOnlyList<string> Aliases, string OpenTarget, string[]? CloseProcessNames)`; `AppAllowlist.All` (`IReadOnlyList<AppDescriptor>`) and `AppAllowlist.FindByAlias(string normalizedArgument)` (`AppDescriptor?`, exact-match lookup, argument must already be trimmed+lowercased by the caller); `IAppExecutor` with `OpenAsync`, `IsRunningAsync`, `CloseAsync`; `AppCloseOutcome { NotRunning, CloseRequested, Failed }`; `ICommandRouter.RouteAsync(string text, CancellationToken)`; `CommandOutcome { NotACommand, Executed, AwaitingConfirmation, Cancelled, Rejected }`; `CommandRouteResult(CommandOutcome Outcome, string? ResultMessage)`.

- [ ] **Step 1: Write the failing test**

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class AppAllowlistTests
{
    [Theory]
    [InlineData("chrome", "chrome")]
    [InlineData("google chrome", "chrome")]
    [InlineData("edge", "edge")]
    [InlineData("microsoft edge", "edge")]
    [InlineData("notepad", "notepad")]
    [InlineData("calculator", "calculator")]
    [InlineData("calc", "calculator")]
    [InlineData("vscode", "vscode")]
    [InlineData("vs code", "vscode")]
    [InlineData("code", "vscode")]
    [InlineData("file explorer", "explorer")]
    [InlineData("explorer", "explorer")]
    [InlineData("settings", "settings")]
    [InlineData("windows settings", "settings")]
    public void FindByAlias_KnownAlias_ReturnsExpectedDescriptor(string alias, string expectedKey)
    {
        var descriptor = AppAllowlist.FindByAlias(alias);

        Assert.NotNull(descriptor);
        Assert.Equal(expectedKey, descriptor!.Key);
    }

    [Theory]
    [InlineData("photoshop")]
    [InlineData("chrome and tell me about tabs")]
    [InlineData("")]
    [InlineData("chrome; rm -rf")]
    public void FindByAlias_UnknownOrInjectionLikeArgument_ReturnsNull(string argument)
    {
        Assert.Null(AppAllowlist.FindByAlias(argument));
    }

    [Fact]
    public void All_HasExactlySevenEntries()
    {
        Assert.Equal(7, AppAllowlist.All.Count);
    }

    [Theory]
    [InlineData("explorer")]
    [InlineData("settings")]
    public void All_ExplorerAndSettings_AreOpenOnly(string key)
    {
        var descriptor = AppAllowlist.All.Single(d => d.Key == key);

        Assert.Null(descriptor.CloseProcessNames);
    }

    [Theory]
    [InlineData("chrome")]
    [InlineData("edge")]
    [InlineData("notepad")]
    [InlineData("calculator")]
    [InlineData("vscode")]
    public void All_ConsumerApps_SupportClose(string key)
    {
        var descriptor = AppAllowlist.All.Single(d => d.Key == key);

        Assert.NotNull(descriptor.CloseProcessNames);
        Assert.NotEmpty(descriptor.CloseProcessNames!);
    }

    [Fact]
    public void All_NeverContainsRevaOrAShell()
    {
        var forbidden = new[] { "reva", "cmd", "powershell", "pwsh" };

        foreach (var descriptor in AppAllowlist.All)
        {
            Assert.DoesNotContain(descriptor.Key, forbidden);
            Assert.DoesNotContain(descriptor.OpenTarget.ToLowerInvariant(), forbidden.Select(f => f + ".exe"));
        }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AppAllowlistTests`
Expected: FAIL (build error — none of `AppDescriptor`/`AppAllowlist`/`IAppExecutor`/`ICommandRouter` exist yet).

- [ ] **Step 3: Write the types**

`AppDescriptor.cs`:

```csharp
namespace Reva.Desktop.Services;

/// <summary>One entry in the fixed app-command allowlist. Every field is a
/// literal constant supplied by <see cref="AppAllowlist"/> — never
/// constructed from user input.</summary>
public sealed record AppDescriptor(
    string Key,
    string DisplayName,
    IReadOnlyList<string> Aliases,
    string OpenTarget,
    string[]? CloseProcessNames);
```

`IAppExecutor.cs`:

```csharp
namespace Reva.Desktop.Services;

public enum AppCloseOutcome
{
    NotRunning,
    CloseRequested,
    Failed,
}

/// <summary>The only seam that touches <see cref="System.Diagnostics.Process"/>.
/// <see cref="CommandRouter"/> never does. The real implementation is
/// <see cref="WindowsAppExecutor"/>.</summary>
public interface IAppExecutor
{
    Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);

    /// <summary>Side-effect-free check — never calls CloseMainWindow.</summary>
    Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);

    /// <summary>The actual close. Only ever called after the user confirms.</summary>
    Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);
}
```

`ICommandRouter.cs`:

```csharp
namespace Reva.Desktop.Services;

public enum CommandOutcome
{
    NotACommand,
    Executed,
    AwaitingConfirmation,
    Cancelled,
    Rejected,
}

public sealed record CommandRouteResult(CommandOutcome Outcome, string? ResultMessage);

/// <summary>Deterministic, local, pre-assistant command interception. A
/// <see cref="CommandOutcome.NotACommand"/> result is the only signal the
/// caller needs — everything else means "do not call the assistant for
/// this message."</summary>
public interface ICommandRouter
{
    Task<CommandRouteResult> RouteAsync(string text, CancellationToken cancellationToken = default);
}
```

`AppAllowlist.cs`:

```csharp
namespace Reva.Desktop.Services;

public static class AppAllowlist
{
    public static readonly IReadOnlyList<AppDescriptor> All = new[]
    {
        new AppDescriptor("chrome", "Google Chrome", new[] { "chrome", "google chrome" }, "chrome.exe", new[] { "chrome" }),
        new AppDescriptor("edge", "Microsoft Edge", new[] { "edge", "microsoft edge" }, "msedge.exe", new[] { "msedge" }),
        new AppDescriptor("notepad", "Notepad", new[] { "notepad" }, "notepad.exe", new[] { "notepad" }),
        // Windows 11 ships Calculator as a packaged app (process "CalculatorApp");
        // older builds/some installs still use the legacy "Calculator" process
        // name. calc.exe is the fixed open target either way (App Execution
        // Alias resolves it on modern Windows). Both names are checked on close.
        new AppDescriptor("calculator", "Calculator", new[] { "calculator", "calc" }, "calc.exe", new[] { "CalculatorApp", "Calculator" }),
        // Code.exe resolves via the registered "App Paths" entry when VS Code's
        // installer has run (the common case); WindowsAppExecutor's open path
        // still surfaces a safe "couldn't open" message rather than throwing
        // if it isn't installed — no plan-time guess about install location
        // is baked in beyond this fixed literal.
        new AppDescriptor("vscode", "Visual Studio Code", new[] { "vscode", "vs code", "code" }, "Code.exe", new[] { "Code" }),
        new AppDescriptor("explorer", "File Explorer", new[] { "file explorer", "explorer" }, "explorer.exe", null),
        new AppDescriptor("settings", "Windows Settings", new[] { "settings", "windows settings" }, "ms-settings:", null),
    };

    private static readonly IReadOnlyDictionary<string, AppDescriptor> ByAlias = All
        .SelectMany(descriptor => descriptor.Aliases.Select(alias => (alias, descriptor)))
        .ToDictionary(pair => pair.alias, pair => pair.descriptor, StringComparer.Ordinal);

    /// <summary>Exact match only — <paramref name="normalizedArgument"/> must
    /// already be trimmed and lowercased by the caller
    /// (<see cref="CommandRouter"/>). No substring/contains matching: this is
    /// the structural defense against chaining/injection-like input.</summary>
    public static AppDescriptor? FindByAlias(string normalizedArgument) =>
        ByAlias.TryGetValue(normalizedArgument, out var descriptor) ? descriptor : null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AppAllowlistTests`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/AppDescriptor.cs desktop/src/Reva.Desktop/Services/AppAllowlist.cs desktop/src/Reva.Desktop/Services/IAppExecutor.cs desktop/src/Reva.Desktop/Services/ICommandRouter.cs desktop/tests/Reva.Desktop.Tests/Unit/AppAllowlistTests.cs
git commit -m "feat(desktop): add app-command allowlist and router/executor interfaces"
```

---

### Task 2: `CommandRouter` — matching + confirmation state machine

This is the task with the most logic and the most tests. No `Process`/OS calls anywhere in this file — everything is driven through the injected `IAppExecutor` fake.

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/CommandRouter.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/CommandRouterTests.cs`

**Interfaces:**
- Consumes: `AppAllowlist`, `IAppExecutor`, `AppCloseOutcome` (Task 1).
- Produces: `CommandRouter(IAppExecutor executor, TimeProvider? timeProvider = null) : ICommandRouter`.

- [ ] **Step 1: Write the failing tests**

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class CommandRouterTests
{
    private sealed class FakeAppExecutor : IAppExecutor
    {
        public bool OpenResult { get; set; } = true;
        public bool IsRunningResult { get; set; } = true;
        public AppCloseOutcome CloseResult { get; set; } = AppCloseOutcome.CloseRequested;

        public int OpenCallCount { get; private set; }
        public int IsRunningCallCount { get; private set; }
        public int CloseCallCount { get; private set; }
        public List<string> OpenedKeys { get; } = new();
        public List<string> ClosedKeys { get; } = new();

        public Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
        {
            OpenCallCount++;
            OpenedKeys.Add(descriptor.Key);
            return Task.FromResult(OpenResult);
        }

        public Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
        {
            IsRunningCallCount++;
            return Task.FromResult(IsRunningResult);
        }

        public Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
        {
            CloseCallCount++;
            ClosedKeys.Add(descriptor.Key);
            return Task.FromResult(CloseResult);
        }
    }

    // Hand-rolled rather than pulling in Microsoft.Extensions.Time.Testing
    // for one test double — matches this project's stated preference for
    // small, dependency-free pieces over an extra package (ObservableObject's
    // own doc comment makes the same call for MVVM).
    private sealed class ManualTimeProvider : TimeProvider
    {
        public DateTimeOffset UtcNow { get; set; } = DateTimeOffset.UtcNow;

        public override DateTimeOffset GetUtcNow() => UtcNow;
    }

    [Theory]
    [InlineData("hello, how are you?")]
    [InlineData("what's the weather like")]
    [InlineData("")]
    [InlineData("   ")]
    public async Task RouteAsync_OrdinaryChat_ReturnsNotACommand(string text)
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync(text);

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.OpenCallCount);
        Assert.Equal(0, executor.IsRunningCallCount);
    }

    [Theory]
    [InlineData("/open chrome")]
    [InlineData("open Chrome")]
    [InlineData("OPEN CHROME")]
    [InlineData("launch Notepad")]
    [InlineData("start Calculator")]
    public async Task RouteAsync_RecognizedOpenCommand_CallsExecutorOnceAndReturnsExecuted(string text)
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync(text);

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.NotNull(result.ResultMessage);
        Assert.Equal(1, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_OpenUnsupportedApp_ReturnsNotACommand_NeverCallsExecutor()
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("open Photoshop");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_OpenWithExtraWords_ReturnsNotACommand_NeverCallsExecutor()
    {
        // Injection/chaining defense: the captured argument must be an exact
        // alias match, not a prefix/contains match.
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("open Chrome and also do something else");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_OpenExecutorFails_ReturnsRejected()
    {
        var executor = new FakeAppExecutor { OpenResult = false };
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("open chrome");

        Assert.Equal(CommandOutcome.Rejected, result.Outcome);
        Assert.Contains("Chrome", result.ResultMessage);
    }

    [Fact]
    public async Task RouteAsync_CloseAllowlistedButNotRunning_ExecutesImmediately_NoConfirmationNeeded()
    {
        var executor = new FakeAppExecutor { IsRunningResult = false };
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("close chrome");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Contains("isn't running", result.ResultMessage);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_CloseExplorer_ReturnsNotACommand_OpenOnlyAppHasNoCloseSupport()
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("close explorer");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.IsRunningCallCount);
    }

    [Fact]
    public async Task RouteAsync_CloseRunningApp_AwaitsConfirmation_DoesNotCloseYet()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("close chrome");

        Assert.Equal(CommandOutcome.AwaitingConfirmation, result.Outcome);
        Assert.Equal("Close Google Chrome? Unsaved work may be lost. Type 'confirm' or 'cancel'.", result.ResultMessage);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_ConfirmAfterPendingClose_ClosesExactlyOnce()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true, CloseResult = AppCloseOutcome.CloseRequested };
        var router = new CommandRouter(executor);
        await router.RouteAsync("close chrome");

        var result = await router.RouteAsync("confirm");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Equal(1, executor.CloseCallCount);
        Assert.Equal(new[] { "chrome" }, executor.ClosedKeys);
    }

    [Fact]
    public async Task RouteAsync_CancelAfterPendingClose_NeverCloses()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await router.RouteAsync("close chrome");

        var result = await router.RouteAsync("cancel");

        Assert.Equal(CommandOutcome.Cancelled, result.Outcome);
        Assert.Equal("Cancelled.", result.ResultMessage);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_ConfirmWithNoPendingAction_ReturnsNotACommand()
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("confirm");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_CancelWithNoPendingAction_ReturnsNotACommand()
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await router.RouteAsync("cancel");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
    }

    [Fact]
    public async Task RouteAsync_ConfirmAfterExpiry_TreatsAsNotACommand_DoesNotClose()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var time = new ManualTimeProvider();
        var router = new CommandRouter(executor, time);
        await router.RouteAsync("close chrome");

        time.UtcNow = time.UtcNow.AddSeconds(31);
        var result = await router.RouteAsync("confirm");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_ConfirmAtExactlyThirtySeconds_StillHonored()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var time = new ManualTimeProvider();
        var router = new CommandRouter(executor, time);
        await router.RouteAsync("close chrome");

        time.UtcNow = time.UtcNow.AddSeconds(29);
        var result = await router.RouteAsync("confirm");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Equal(1, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_NewCloseRequestWhilePendingConfirmation_OverwritesPending()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await router.RouteAsync("close chrome");

        await router.RouteAsync("close notepad");
        var result = await router.RouteAsync("confirm");

        Assert.Equal(1, executor.CloseCallCount);
        Assert.Equal(new[] { "notepad" }, executor.ClosedKeys);
    }

    [Fact]
    public async Task RouteAsync_TargetExitsBetweenPromptAndConfirm_ReportsNotRunning_DoesNotThrow()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true, CloseResult = AppCloseOutcome.NotRunning };
        var router = new CommandRouter(executor);
        await router.RouteAsync("close chrome");

        var result = await router.RouteAsync("confirm");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Contains("isn't running", result.ResultMessage);
    }

    [Fact]
    public async Task RouteAsync_DuplicateConfirm_SecondCallIsNotACommand()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await router.RouteAsync("close chrome");
        await router.RouteAsync("confirm");

        var second = await router.RouteAsync("confirm");

        Assert.Equal(CommandOutcome.NotACommand, second.Outcome);
        Assert.Equal(1, executor.CloseCallCount);
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter CommandRouterTests`
Expected: FAIL (build error — `CommandRouter` doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```csharp
using System.Text.RegularExpressions;

namespace Reva.Desktop.Services;

public sealed class CommandRouter : ICommandRouter
{
    private static readonly Regex OpenPattern = new(
        @"^/?(?:open|launch|start)\s+(.+)$", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex ClosePattern = new(
        @"^/?(?:close|quit)\s+(.+)$", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private readonly IAppExecutor _executor;
    private readonly TimeProvider _timeProvider;
    private PendingClose? _pending;

    public CommandRouter(IAppExecutor executor, TimeProvider? timeProvider = null)
    {
        _executor = executor;
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public Task<CommandRouteResult> RouteAsync(string text, CancellationToken cancellationToken = default)
    {
        var trimmed = text.Trim();

        if (string.Equals(trimmed, "confirm", StringComparison.OrdinalIgnoreCase))
        {
            return HandleConfirmAsync(cancellationToken);
        }

        if (string.Equals(trimmed, "cancel", StringComparison.OrdinalIgnoreCase))
        {
            return Task.FromResult(HandleCancel());
        }

        var openMatch = OpenPattern.Match(trimmed);
        if (openMatch.Success)
        {
            return HandleOpenAsync(openMatch.Groups[1].Value, cancellationToken);
        }

        var closeMatch = ClosePattern.Match(trimmed);
        if (closeMatch.Success)
        {
            return HandleCloseRequestAsync(closeMatch.Groups[1].Value, cancellationToken);
        }

        return Task.FromResult(new CommandRouteResult(CommandOutcome.NotACommand, null));
    }

    private static string Normalize(string argument) => argument.Trim().ToLowerInvariant();

    private async Task<CommandRouteResult> HandleOpenAsync(string argument, CancellationToken cancellationToken)
    {
        var descriptor = AppAllowlist.FindByAlias(Normalize(argument));
        if (descriptor is null)
        {
            return new CommandRouteResult(CommandOutcome.NotACommand, null);
        }

        DesktopLogger.Info($"command.state=Matched action=Open app={descriptor.Key}");
        var opened = await _executor.OpenAsync(descriptor, cancellationToken).ConfigureAwait(false);
        DesktopLogger.Info($"command.state=Executed action=Open app={descriptor.Key} result={(opened ? "success" : "failed")}");

        return opened
            ? new CommandRouteResult(CommandOutcome.Executed, $"Opened {descriptor.DisplayName}.")
            : new CommandRouteResult(CommandOutcome.Rejected, $"Couldn't open {descriptor.DisplayName}.");
    }

    private async Task<CommandRouteResult> HandleCloseRequestAsync(string argument, CancellationToken cancellationToken)
    {
        var descriptor = AppAllowlist.FindByAlias(Normalize(argument));
        if (descriptor is null || descriptor.CloseProcessNames is null)
        {
            return new CommandRouteResult(CommandOutcome.NotACommand, null);
        }

        var running = await _executor.IsRunningAsync(descriptor, cancellationToken).ConfigureAwait(false);
        if (!running)
        {
            DesktopLogger.Info($"command.state=Executed action=Close app={descriptor.Key} result=not_running");
            return new CommandRouteResult(CommandOutcome.Executed, $"{descriptor.DisplayName} isn't running.");
        }

        _pending = new PendingClose(descriptor, _timeProvider.GetUtcNow().AddSeconds(30));
        DesktopLogger.Info($"command.state=AwaitingConfirmation action=Close app={descriptor.Key}");
        return new CommandRouteResult(
            CommandOutcome.AwaitingConfirmation,
            $"Close {descriptor.DisplayName}? Unsaved work may be lost. Type 'confirm' or 'cancel'.");
    }

    private async Task<CommandRouteResult> HandleConfirmAsync(CancellationToken cancellationToken)
    {
        if (_pending is null || _timeProvider.GetUtcNow() > _pending.ExpiresAtUtc)
        {
            _pending = null;
            return new CommandRouteResult(CommandOutcome.NotACommand, null);
        }

        var descriptor = _pending.App;
        _pending = null;
        var outcome = await _executor.CloseAsync(descriptor, cancellationToken).ConfigureAwait(false);
        DesktopLogger.Info($"command.state=Confirmed action=Close app={descriptor.Key} result={outcome}");

        return outcome switch
        {
            AppCloseOutcome.CloseRequested => new CommandRouteResult(CommandOutcome.Executed, $"Closing {descriptor.DisplayName}."),
            AppCloseOutcome.NotRunning => new CommandRouteResult(CommandOutcome.Executed, $"{descriptor.DisplayName} isn't running."),
            _ => new CommandRouteResult(CommandOutcome.Rejected, $"Couldn't close {descriptor.DisplayName}."),
        };
    }

    private CommandRouteResult HandleCancel()
    {
        if (_pending is null)
        {
            return new CommandRouteResult(CommandOutcome.NotACommand, null);
        }

        var descriptor = _pending.App;
        _pending = null;
        DesktopLogger.Info($"command.state=Cancelled action=Close app={descriptor.Key}");
        return new CommandRouteResult(CommandOutcome.Cancelled, "Cancelled.");
    }

    private sealed record PendingClose(AppDescriptor App, DateTimeOffset ExpiresAtUtc);
}
```

Note the expiry comparison is `>` (strictly greater), not `>=` — at exactly 30.000...0s the action is still honored (`RouteAsync_ConfirmAtExactlyThirtySeconds_StillHonored` pins this; the 29-second test in that case is deliberately inside the window, not testing the exact boundary tick — floating-point/timer precision makes testing the literal instant unreliable, 29s inside vs 31s outside is what actually matters).

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter CommandRouterTests`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/CommandRouter.cs desktop/tests/Reva.Desktop.Tests/Unit/CommandRouterTests.cs
git commit -m "feat(desktop): add CommandRouter with confirm/cancel state machine"
```

---

### Task 3: `WindowsAppExecutor` — the real process launcher

No unit tests — same established precedent as `WindowsVoiceDevice` (real OS/`Process` dependency, verified only by the physical acceptance run in Task 6, not xUnit).

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/WindowsAppExecutor.cs`

**Interfaces:**
- Consumes: `IAppExecutor`, `AppDescriptor`, `AppCloseOutcome` (Task 1).
- Produces: `WindowsAppExecutor : IAppExecutor` — the only file touching `System.Diagnostics.Process`.

- [ ] **Step 1: Implement**

```csharp
using System.ComponentModel;
using System.Diagnostics;

namespace Reva.Desktop.Services;

public sealed class WindowsAppExecutor : IAppExecutor
{
    public Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
    {
        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = descriptor.OpenTarget,
                UseShellExecute = true,
            };
            using var process = Process.Start(startInfo);
            return Task.FromResult(process is not null);
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or System.IO.FileNotFoundException)
        {
            DesktopLogger.Info($"command.state=Rejected action=Open app={descriptor.Key} reason=launch_failed");
            return Task.FromResult(false);
        }
    }

    public Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
    {
        var matches = FindRunningProcesses(descriptor);
        try
        {
            return Task.FromResult(matches.Count > 0);
        }
        finally
        {
            foreach (var process in matches)
            {
                process.Dispose();
            }
        }
    }

    public Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
    {
        var matches = FindRunningProcesses(descriptor);
        if (matches.Count == 0)
        {
            return Task.FromResult(AppCloseOutcome.NotRunning);
        }

        try
        {
            foreach (var process in matches)
            {
                // Polite request only — the target app can ignore it or prompt
                // its own "save changes?" dialog. Never Kill().
                process.CloseMainWindow();
            }

            return Task.FromResult(AppCloseOutcome.CloseRequested);
        }
        finally
        {
            foreach (var process in matches)
            {
                process.Dispose();
            }
        }
    }

    private static List<Process> FindRunningProcesses(AppDescriptor descriptor) =>
        (descriptor.CloseProcessNames ?? Array.Empty<string>())
            .SelectMany(Process.GetProcessesByName)
            .Where(process => process.MainWindowHandle != IntPtr.Zero)
            .ToList();
}
```

- [ ] **Step 2: Build to confirm it compiles**

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds, 0 errors.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/WindowsAppExecutor.cs
git commit -m "feat(desktop): add WindowsAppExecutor (Process.Start/CloseMainWindow only)"
```

---

### Task 4: `AssistantViewModel` integration

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/NullCommandRouter.cs`
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs`

**Interfaces:**
- Consumes: `ICommandRouter`, `CommandOutcome`, `CommandRouteResult` (Task 1/2).
- Produces: `AssistantViewModel(IRevaCoreClient coreClient, IVoiceDevice? voiceDevice = null, IRevaCoreLifecycle? lifecycle = null, ICommandRouter? commandRouter = null)`.

- [ ] **Step 1: Write `NullCommandRouter`**

```csharp
namespace Reva.Desktop.Services;

/// <summary>Null-object default for <see cref="AssistantViewModel"/>'s
/// optional command-router dependency, mirroring
/// <see cref="UnavailableVoiceDevice"/>'s precedent — every message is
/// NotACommand, so existing call sites that don't pass a router keep
/// behaving exactly as before this slice.</summary>
public sealed class NullCommandRouter : ICommandRouter
{
    public Task<CommandRouteResult> RouteAsync(string text, CancellationToken cancellationToken = default) =>
        Task.FromResult(new CommandRouteResult(CommandOutcome.NotACommand, null));
}
```

- [ ] **Step 2: Write the failing tests**

Add to `AssistantViewModelTests.cs`, alongside the existing `FakeCoreClient`/`FakeVoiceDevice`/`FakeCoreLifecycle` nested classes (same file, same idiom):

```csharp
    private sealed class FakeCommandRouter : ICommandRouter
    {
        private readonly Func<string, CommandRouteResult> _responder;

        public FakeCommandRouter(Func<string, CommandRouteResult> responder) => _responder = responder;

        public int CallCount { get; private set; }

        public List<string> ReceivedText { get; } = new();

        public Task<CommandRouteResult> RouteAsync(string text, CancellationToken cancellationToken = default)
        {
            CallCount++;
            ReceivedText.Add(text);
            return Task.FromResult(_responder(text));
        }
    }

    private static FakeCommandRouter PassthroughRouter() =>
        new(_ => new CommandRouteResult(CommandOutcome.NotACommand, null));

    private static FakeCommandRouter RecognizingRouter(CommandOutcome outcome, string message) =>
        new(_ => new CommandRouteResult(outcome, message));
```

And these facts (place near the other `SendMessageAsync`/`SendMessageCoreAsync` tests):

```csharp
    [Fact]
    public async Task SendMessageAsync_RouterReturnsNotACommand_FallsThroughToCoreUnchanged()
    {
        var client = ImmediateSuccessClient("Received: hello");
        var router = PassthroughRouter();
        var viewModel = new AssistantViewModel(client, commandRouter: router) { ComposerText = "hello REVA" };

        await viewModel.SendMessageAsync();

        Assert.Equal(1, router.CallCount);
        Assert.Equal(1, client.CallCount);
        Assert.Equal(2, viewModel.Messages.Count);
        Assert.Equal("Received: hello", viewModel.Messages[1].Text);
    }

    [Fact]
    public async Task SendMessageAsync_RouterRecognizesCommand_NeverCallsCore()
    {
        var client = new FakeCoreClient((_, _) => throw new NotSupportedException("router-recognized command must never reach Core"));
        var router = RecognizingRouter(CommandOutcome.Executed, "Opened Google Chrome.");
        var viewModel = new AssistantViewModel(client, commandRouter: router) { ComposerText = "open Chrome" };

        await viewModel.SendMessageAsync();

        Assert.Equal(0, client.CallCount);
        Assert.Equal(2, viewModel.Messages.Count);
        Assert.Equal(AssistantMessageRole.User, viewModel.Messages[0].Role);
        Assert.Equal("open Chrome", viewModel.Messages[0].Text);
        Assert.Equal(AssistantMessageRole.Assistant, viewModel.Messages[1].Role);
        Assert.Equal("Opened Google Chrome.", viewModel.Messages[1].Text);
    }

    [Fact]
    public async Task SendMessageAsync_RouterRecognizesCommand_ComposerStillClears()
    {
        var client = new FakeCoreClient((_, _) => throw new NotSupportedException());
        var router = RecognizingRouter(CommandOutcome.Executed, "Opened Notepad.");
        var viewModel = new AssistantViewModel(client, commandRouter: router) { ComposerText = "open Notepad" };

        await viewModel.SendMessageAsync();

        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task SendMessageAsync_RouterAwaitingConfirmation_ShowsPromptAsAssistantMessage_NeverCallsCore()
    {
        var client = new FakeCoreClient((_, _) => throw new NotSupportedException());
        var router = RecognizingRouter(
            CommandOutcome.AwaitingConfirmation,
            "Close Google Chrome? Unsaved work may be lost. Type 'confirm' or 'cancel'.");
        var viewModel = new AssistantViewModel(client, commandRouter: router) { ComposerText = "close Chrome" };

        await viewModel.SendMessageAsync();

        Assert.Equal(0, client.CallCount);
        Assert.Equal(
            "Close Google Chrome? Unsaved work may be lost. Type 'confirm' or 'cancel'.",
            viewModel.Messages[1].Text);
    }

    [Fact]
    public async Task SendMessageAsync_NoCommandRouterProvided_BehavesExactlyAsBeforeThisSlice()
    {
        // Default-constructed AssistantViewModel (no commandRouter arg) —
        // every pre-existing test/call site in this file that doesn't pass
        // one must keep working unchanged.
        var client = ImmediateSuccessClient("Received: hi");
        var viewModel = new AssistantViewModel(client) { ComposerText = "open Chrome" };

        await viewModel.SendMessageAsync();

        Assert.Equal(1, client.CallCount);
        Assert.Equal("Received: hi", viewModel.Messages[1].Text);
    }

    [Fact]
    public async Task SendMessageAsync_IsPending_ResetsAfterCommandRouted()
    {
        var client = new FakeCoreClient((_, _) => throw new NotSupportedException());
        var router = RecognizingRouter(CommandOutcome.Executed, "Opened Notepad.");
        var viewModel = new AssistantViewModel(client, commandRouter: router) { ComposerText = "open Notepad" };

        await viewModel.SendMessageAsync();

        Assert.False(viewModel.IsPending);
    }
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: FAIL to build — no 4-arg constructor, `ICommandRouter` not consumed yet.

- [ ] **Step 4: Implement**

In `AssistantViewModel.cs`:

1. Add a field: `private readonly ICommandRouter _commandRouter;`
2. Update the constructor:

```csharp
    public AssistantViewModel(
        IRevaCoreClient coreClient,
        IVoiceDevice? voiceDevice = null,
        IRevaCoreLifecycle? lifecycle = null,
        ICommandRouter? commandRouter = null)
    {
        _coreClient = coreClient;
        _voiceDevice = voiceDevice ?? new UnavailableVoiceDevice();
        _lifecycle = lifecycle;
        _commandRouter = commandRouter ?? new NullCommandRouter();
        _isVoiceAvailable = _voiceDevice.IsAvailable;
        _voiceState = _isVoiceAvailable
            ? (IsCoreConnected ? VoiceUiState.ReadyToTalk : VoiceUiState.SttUnavailable)
            : VoiceUiState.CheckingMicrophone;
        _voiceStatusText = VoiceUiStateText.For(_voiceState);

        if (_lifecycle is not null)
        {
            _lifecycle.StateChanged += OnLifecycleStateChanged;
        }
    }
```

3. In `SendMessageCoreAsync` (currently lines 451-491), insert the router check as the first statement inside the existing `try` block, before the `_coreClient.SendMessageAsync` call:

```csharp
        try
        {
            var routeResult = await _commandRouter.RouteAsync(trimmed, cancellationToken).ConfigureAwait(true);
            if (routeResult.Outcome != CommandOutcome.NotACommand)
            {
                if (!string.IsNullOrEmpty(routeResult.ResultMessage))
                {
                    Messages.Add(AssistantMessage.FromAssistant(routeResult.ResultMessage));
                }

                return null;
            }

            var result = await _coreClient.SendMessageAsync(trimmed, cancellationToken);
            if (result.IsSuccess)
            {
                var reply = result.Value!.Reply;
                Messages.Add(AssistantMessage.FromAssistant(reply));
                return reply;
            }
            else
            {
                ErrorMessage = result.Error!.SafeMessage;
                return null;
            }
        }
        finally
        {
            IsPending = false;
            RaiseVoiceAvailabilityProperties();
        }
```

Everything before this (`ErrorMessage = null; IsPending = true; RaiseVoiceAvailabilityProperties(); Messages.Add(AssistantMessage.FromUser(trimmed)); if (clearComposer) { ComposerText = string.Empty; }`) and the `finally` block are unchanged — this is a pure insertion inside the existing `try`, not a rewrite.

- [ ] **Step 5: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: PASS — every pre-existing test (none pass a `commandRouter`, so `NullCommandRouter` preserves current behavior identically) plus the new command-routing tests.

- [ ] **Step 6: Run the full suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures — confirms voice-turn tests (which never call `SendMessageCoreAsync`) and memory-panel tests are untouched.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/NullCommandRouter.cs desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "feat(desktop): route recognized app-commands before the assistant pipeline"
```

---

### Task 5: Wire the composition root

**Files:**
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml.cs`
- Modify: `desktop/src/Reva.Desktop/App.xaml.cs`

**Interfaces:**
- Consumes: `WindowsAppExecutor`, `CommandRouter` (Tasks 2-3).

- [ ] **Step 1: `MainWindow.xaml.cs`**

Change the constructor signature and the `AssistantViewModel` construction:

```csharp
    public MainWindow(
        IRevaCoreClient coreClient,
        IRevaCoreLifecycle lifecycle,
        IVoiceDevice? voiceDevice = null,
        ICommandRouter? commandRouter = null)
    {
        InitializeComponent();
        Shell = new ShellViewModel(lifecycle);
        Assistant = new AssistantViewModel(coreClient, voiceDevice, lifecycle, commandRouter);
        Memory = new MemoryViewModel(coreClient);
        Shell.PropertyChanged += OnShellPropertyChanged;
        ApplyStatusDotColor();
        RegisterVoicePointerHandlers();
        Closed += MainWindow_Closed;
    }
```

- [ ] **Step 2: `App.xaml.cs`**

Between the existing `lifecycle` construction and `new MainWindow(...)`:

```csharp
        var commandRouter = new CommandRouter(new WindowsAppExecutor());

        _window = new MainWindow(coreClient, lifecycle, new WindowsVoiceDevice(), commandRouter);
```

- [ ] **Step 3: Build**

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds, 0 errors.

- [ ] **Step 4: Run the full suite one more time**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/MainWindow.xaml.cs desktop/src/Reva.Desktop/App.xaml.cs
git commit -m "feat(desktop): wire CommandRouter/WindowsAppExecutor into the composition root"
```

---

### Task 6: Physical open/confirmed-close acceptance run

**Files:** none (verification task).

- [ ] **Step 1: Full automated suite, one last time**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures.

- [ ] **Step 2: Build Release, run it**

Run: `dotnet build desktop/Reva.Desktop.sln -c Release`, then run the produced `Reva.Desktop.exe` with `reva_core` reachable (same setup as the transcription-only voice slice's Task 9).

- [ ] **Step 3: Open acceptance — one per allowlist entry**

For each of: `/open chrome`, `open Chrome`, `launch Notepad`, `start Calculator`, `open Edge`, `open VS Code`, `open File Explorer`, `open Settings` — type it, press Send. Confirm: the typed text appears as a "You" message, a "REVA" message follows ("Opened X."), the target application's window actually appears, and no request hits `reva_core` (watch its logs/audit for the correlation window — no `v1/messages` POST for these turns).

- [ ] **Step 4: Close + confirm acceptance**

With Chrome running (from Step 3), type `close Chrome`. Confirm the "Close Google Chrome? Unsaved work may be lost. Type 'confirm' or 'cancel'." message appears. Type `confirm`. Confirm Chrome's window closes (or prompts to save, if it has unsaved state — `CloseMainWindow` was issued, not `Kill`) and a "Closing Google Chrome." message appears.

- [ ] **Step 5: Close + cancel acceptance**

Open Notepad (Step 3's flow), type `close Notepad`, then type `cancel` instead of `confirm`. Confirm Notepad's window is still open and a "Cancelled." message appears.

- [ ] **Step 6: Not-running acceptance**

With no Calculator window open, type `close Calculator`. Confirm the immediate reply is "Calculator isn't running." with no confirmation prompt.

- [ ] **Step 7: Unsupported command falls through to ordinary chat**

Type `open Photoshop`. Confirm it behaves exactly like typing any other chat message — it goes to the assistant (watch for the `v1/messages` request in Core's logs) and gets a normal assistant reply, not a router message.

- [ ] **Step 8: Explorer/Settings close-not-supported check**

Type `close explorer` and `close settings`. Confirm both fall through to ordinary chat (per Step 7's check) rather than producing any router response — they were deliberately excluded from the close allowlist.

- [ ] **Step 9: Report**

Summarize which of the 8 open commands and the confirm/cancel/not-running/fallthrough behaviors were verified, any deviations, and confirm no `reva_core` request occurred for any successfully-routed command (cross-check Core's own request logs for the run's time window).

- [ ] **Step 10: Commit any last-mile fixes**

```bash
git status
git add -A
git commit -m "fix(desktop): address app-command acceptance findings"
```

(Skip if `git status` is clean.)

---

## Self-Review Notes

- **Spec coverage:** flow steps 1-9 (Task 4's insertion point + Task 2's routing), commands table (Task 2's regex + Task 1's allowlist aliases), initial allowlist (Task 1), security boundaries (Global Constraints, each verified against Task 1-3's actual code), opening mechanics (Task 3), closing mechanics + confirm/cancel/expiry (Task 2), physical acceptance (Task 6).
- **No placeholders:** every allowlist entry has a concrete literal `OpenTarget`/`CloseProcessNames` (including the documented Calculator dual-process-name handling, decided in-plan rather than left TBD); every regex is the actual pattern, not a description of one.
- **Small, independently revertible commits:** each of the 6 tasks is one commit (Task 1: types+allowlist, Task 2: router, Task 3: executor, Task 4: ViewModel integration, Task 5: DI wiring, Task 6: any acceptance fixes) — reverting any one doesn't require reverting another (Task 3's executor has no compile-time dependents until Task 5 wires it in; Task 4's ViewModel change is additive/optional-parameter, so reverting it alone doesn't break Tasks 1-3).
- **Existing behavior confirmed unchanged:** Task 4 Step 5's full-suite run and the explicit `SendMessageAsync_NoCommandRouterProvided_BehavesExactlyAsBeforeThisSlice`/`RouterReturnsNotACommand_FallsThroughToCoreUnchanged` tests directly verify typed chat's non-command path is untouched; the voice-turn code path (`FinishVoiceInputAsync`) never calls `SendMessageCoreAsync` at all (confirmed by recon), so it cannot be affected by this insertion; memory (`MemoryViewModel`) and TTS (already dead code post-voice-slice) are in files this plan never touches.
- **Type consistency:** `AppDescriptor`/`ICommandRouter`/`IAppExecutor`/enums (Task 1) used identically by `CommandRouter` (Task 2), `WindowsAppExecutor` (Task 3), and `AssistantViewModel` (Task 4). `CommandRouter`'s constructor signature (Task 2) matches exactly what `App.xaml.cs` calls (Task 5).
