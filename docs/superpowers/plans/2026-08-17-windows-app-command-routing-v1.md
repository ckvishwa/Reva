# Windows App-Command Routing v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Supersedes v1 (2026-08-17).** Changes: `RouteAsync` takes a `CommandSource` and a transcribed `confirm` can no longer close an app (new Task 4 work, new tests); `close explorer` returns `Rejected` instead of falling silently through to the LLM; `CloseMainWindow` races are caught; process work moves off the UI thread; regex anchors changed to `\A`/`\z`; the mis-named 30-second test is fixed; a coverage table replaces the v1 self-review's unverified coverage claim.

**Goal:** Before a composer message reaches the assistant, a deterministic local router recognizes a small set of app open/close commands and executes them through a restricted, allowlisted Windows process executor — never a shell, never arbitrary paths, never LLM-decided, and never confirming a destructive action from speech. Everything else falls through to the existing assistant pipeline with zero behavior change.

**Architecture:** Two new interfaces (`ICommandRouter`, `IAppExecutor`) behind a fixed 7-entry allowlist (`AppAllowlist`). `CommandRouter` owns text matching and a single-slot pending-confirmation state machine (30s expiry via injected `TimeProvider`); it never touches `Process`/`ProcessStartInfo`. `WindowsAppExecutor` is the only file that does, and it does its work on the thread pool. `AssistantViewModel.SendMessageCoreAsync` gets one new call plus a typed-vs-transcribed flag.

**Tech Stack:** C# / .NET (net10.0-windows10.0.19041.0), `System.Diagnostics.Process`, `System.TimeProvider` (BCL, no new package), xUnit.

## Global Constraints

- No arbitrary executable paths — every `ProcessStartInfo.FileName` is one of 7 fixed literals in `AppAllowlist`.
- No raw user input to `Process.Start` — `Arguments` is never set.
- No `cmd.exe`, `powershell.exe`, `pwsh.exe`, or script execution in the allowlist.
- No `Process.Kill()` — close uses `CloseMainWindow()` only.
- No elevation — `Verb` is never `"runas"`.
- No LLM-generated shell commands — the router runs before the assistant is invoked; `NotACommand` is the only way a message reaches the assistant.
- **A destructive close is confirmable only by typed input.** A transcribed `confirm` never resolves a pending action.
- Never closes REVA itself, security tools, system processes, or unknown apps — the close-capable set is 5 named consumer apps.
- Reject chaining, pipes, redirection, and multi-line input — structurally, via exact-alias equality and `\A`/`\z` anchors.
- Log only a canonical action ID, app key, source, and fixed result code — never the user's literal text, a file path, or an exception message.
- Nothing runs `Process.Start` or `Process.GetProcessesByName` on the UI thread.
- Voice transcription, typed chat's non-command path, memory, and TTS are unchanged — verified per-task by the full suite.
- Desktop-only — no `reva_core`/Python changes.

---

## File Structure

- `desktop/src/Reva.Desktop/Services/AppDescriptor.cs` — **new**
- `desktop/src/Reva.Desktop/Services/AppAllowlist.cs` — **new**
- `desktop/src/Reva.Desktop/Services/IAppExecutor.cs` — **new**
- `desktop/src/Reva.Desktop/Services/ICommandRouter.cs` — **new** (includes `CommandSource`)
- `desktop/src/Reva.Desktop/Services/CommandRouter.cs` — **new**
- `desktop/src/Reva.Desktop/Services/WindowsAppExecutor.cs` — **new**. The only file touching `System.Diagnostics.Process`.
- `desktop/src/Reva.Desktop/Services/NullCommandRouter.cs` — **new**
- `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs` — **modify**
- `desktop/src/Reva.Desktop/MainWindow.xaml.cs` — **modify**
- `desktop/src/Reva.Desktop/App.xaml.cs` — **modify**
- `desktop/tests/Reva.Desktop.Tests/Unit/AppAllowlistTests.cs` — **new**
- `desktop/tests/Reva.Desktop.Tests/Unit/CommandRouterTests.cs` — **new**
- `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs` — **modify** (added to, not replaced)

---

### Task 0: Recon — one assumption v1 got wrong

**Files:** none (read-only).

- [ ] **Step 1: Establish how composer text arrives**

Read `AssistantViewModel.cs` and `MainWindow.xaml.cs` and answer, in writing:

1. Where does `ComposerText` get set from a transcript? (Expected: `FinishVoiceInputAsync`'s success branch, appending.)
2. Where does user typing reach the ViewModel? (Expected: `SyncComposerTextFromTextBox`, on the `LostFocus`-gated TwoWay binding.)
3. **Is there any existing way to tell those two apart?** (Expected: no. Task 4 adds it. v1's design assumed the router could be source-agnostic; it can't.)
4. Confirm `SendMessageCoreAsync`'s exact current shape — the trim/pending/empty guard, the `Messages.Add(FromUser(trimmed))` line, the `clearComposer` branch, and the `finally`.
5. Confirm `DesktopLogger.Info`'s signature and whether `Redact` is applied automatically.
6. Confirm `AssistantMessage.FromAssistant` exists and `AssistantMessageRole` has exactly two members.

- [ ] **Step 2: Record findings**

Write them into `docs/superpowers/specs/2026-08-17-app-command-recon.md` and correct any task below that they contradict. Commit the note.

---

### Task 1: Types + allowlist table

**Files:**
- Create: `AppDescriptor.cs`, `AppAllowlist.cs`, `IAppExecutor.cs`, `ICommandRouter.cs`
- Test: `AppAllowlistTests.cs`

**Interfaces:**
- Produces: `AppDescriptor(string Key, string DisplayName, IReadOnlyList<string> Aliases, string OpenTarget, string[]? CloseProcessNames)`; `AppAllowlist.All` and `AppAllowlist.FindByAlias(string normalizedArgument)`; `IAppExecutor` (`OpenAsync`, `IsRunningAsync`, `CloseAsync`); `AppCloseOutcome`; `ICommandRouter.RouteAsync(string, CommandSource, CancellationToken)`; `CommandSource`; `CommandOutcome`; `CommandRouteResult`.

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
    [InlineData("chrome | more")]
    [InlineData("chrome && calc")]
    public void FindByAlias_UnknownOrInjectionLikeArgument_ReturnsNull(string argument)
    {
        Assert.Null(AppAllowlist.FindByAlias(argument));
    }

    [Fact]
    public void All_HasExactlySevenEntries()
    {
        Assert.Equal(7, AppAllowlist.All.Count);
    }

    [Fact]
    public void All_AliasesAreUniqueAcrossEntries()
    {
        // A duplicated alias would make the dictionary build throw at type-init
        // time — a startup crash, not a test failure. Catch it here instead.
        var aliases = AppAllowlist.All.SelectMany(d => d.Aliases).ToList();

        Assert.Equal(aliases.Count, aliases.Distinct().Count());
    }

    [Fact]
    public void All_AliasesAreAlreadyLowercase()
    {
        // FindByAlias uses an Ordinal dictionary against a lowercased argument;
        // an uppercase alias in the table would be permanently unreachable.
        foreach (var alias in AppAllowlist.All.SelectMany(d => d.Aliases))
        {
            Assert.Equal(alias.ToLowerInvariant(), alias);
        }
    }

    [Theory]
    [InlineData("explorer")]
    [InlineData("settings")]
    public void All_ExplorerAndSettings_AreOpenOnly(string key)
    {
        Assert.Null(AppAllowlist.All.Single(d => d.Key == key).CloseProcessNames);
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
    public void All_NoEntryTargetsAShellOrRevaItself()
    {
        var forbidden = new[] { "cmd", "powershell", "pwsh", "wscript", "cscript", "reva" };

        foreach (var descriptor in AppAllowlist.All)
        {
            var target = descriptor.OpenTarget.ToLowerInvariant();
            foreach (var bad in forbidden)
            {
                Assert.False(
                    target.Contains(bad, StringComparison.Ordinal),
                    $"Allowlist entry '{descriptor.Key}' targets '{descriptor.OpenTarget}'.");
            }

            foreach (var processName in descriptor.CloseProcessNames ?? Array.Empty<string>())
            {
                Assert.DoesNotContain(processName.ToLowerInvariant(), forbidden);
            }
        }
    }
}
```

(v1's version of that last test asserted a collection didn't contain a string — it passed vacuously and would not have caught `powershell.exe` in an `OpenTarget`. This one does a substring check in the right direction and also covers close names.)

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AppAllowlistTests`
Expected: FAIL (build error — none of the types exist).

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
/// <see cref="CommandRouter"/> never does.</summary>
public interface IAppExecutor
{
    Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);

    /// <summary>Side-effect-free check — never calls CloseMainWindow.</summary>
    Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);

    /// <summary>The actual close. Only ever called after a typed confirmation.</summary>
    Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);
}
```

`ICommandRouter.cs`:

```csharp
namespace Reva.Desktop.Services;

/// <summary>How the text being routed reached the composer. Destructive
/// confirmations are honored only for <see cref="Typed"/> — a spoken word
/// must never be able to discard someone's unsaved work.</summary>
public enum CommandSource
{
    Typed,
    Transcribed,
}

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
/// caller needs — everything else means "do not call the assistant."</summary>
public interface ICommandRouter
{
    Task<CommandRouteResult> RouteAsync(
        string text, CommandSource source, CancellationToken cancellationToken = default);
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
        // older builds use "Calculator". calc.exe is the open target either way.
        new AppDescriptor("calculator", "Calculator", new[] { "calculator", "calc" }, "calc.exe", new[] { "CalculatorApp", "Calculator" }),
        // ShellExecute's App Paths lookup consults HKCU as well as HKLM, so a
        // per-user VS Code install resolves this literal without a hardcoded
        // %LOCALAPPDATA% path. If Task 7 acceptance shows otherwise, add the
        // fallback then — as a recorded finding, not a guess now.
        new AppDescriptor("vscode", "Visual Studio Code", new[] { "vscode", "vs code", "code" }, "Code.exe", new[] { "Code" }),
        new AppDescriptor("explorer", "File Explorer", new[] { "file explorer", "explorer" }, "explorer.exe", null),
        new AppDescriptor("settings", "Windows Settings", new[] { "settings", "windows settings" }, "ms-settings:", null),
    };

    private static readonly IReadOnlyDictionary<string, AppDescriptor> ByAlias = All
        .SelectMany(descriptor => descriptor.Aliases.Select(alias => (alias, descriptor)))
        .ToDictionary(pair => pair.alias, pair => pair.descriptor, StringComparer.Ordinal);

    /// <summary>Exact match only — the argument must already be trimmed and
    /// lowercased by <see cref="CommandRouter"/>. No substring matching: this
    /// is the structural defense against chaining/injection-like input.</summary>
    public static AppDescriptor? FindByAlias(string normalizedArgument) =>
        ByAlias.TryGetValue(normalizedArgument, out var descriptor) ? descriptor : null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AppAllowlistTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/AppDescriptor.cs desktop/src/Reva.Desktop/Services/AppAllowlist.cs desktop/src/Reva.Desktop/Services/IAppExecutor.cs desktop/src/Reva.Desktop/Services/ICommandRouter.cs desktop/tests/Reva.Desktop.Tests/Unit/AppAllowlistTests.cs
git commit -m "feat(desktop): add app-command allowlist and router/executor interfaces"
```

---

### Task 2: `CommandRouter` — matching + source-aware confirmation

The task with the most logic and the most tests. No `Process`/OS calls anywhere in this file.

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/CommandRouter.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/CommandRouterTests.cs`

**Interfaces:**
- Consumes: `AppAllowlist`, `IAppExecutor`, `AppCloseOutcome`, `CommandSource` (Task 1).
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

    // Hand-rolled rather than adding Microsoft.Extensions.Time.Testing for one
    // double — matches this project's preference for small dependency-free
    // pieces (ObservableObject makes the same call for MVVM).
    private sealed class ManualTimeProvider : TimeProvider
    {
        public DateTimeOffset UtcNow { get; set; } = DateTimeOffset.UtcNow;

        public override DateTimeOffset GetUtcNow() => UtcNow;
    }

    private static Task<CommandRouteResult> Typed(CommandRouter router, string text) =>
        router.RouteAsync(text, CommandSource.Typed);

    private static Task<CommandRouteResult> Spoken(CommandRouter router, string text) =>
        router.RouteAsync(text, CommandSource.Transcribed);

    [Theory]
    [InlineData("hello, how are you?")]
    [InlineData("what's the weather like")]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("start over")]
    [InlineData("let's open a discussion about the roadmap")]
    public async Task RouteAsync_OrdinaryChat_ReturnsNotACommand(string text)
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Typed(router, text);

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.OpenCallCount);
        Assert.Equal(0, executor.IsRunningCallCount);
    }

    [Theory]
    [InlineData("/open chrome")]
    [InlineData("open Chrome")]
    [InlineData("OPEN CHROME")]
    [InlineData("  open   chrome  ")]
    [InlineData("launch Notepad")]
    [InlineData("start Calculator")]
    public async Task RouteAsync_RecognizedOpenCommand_CallsExecutorOnce(string text)
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Typed(router, text);

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.NotNull(result.ResultMessage);
        Assert.Equal(1, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_SpokenOpenCommand_IsHonored()
    {
        // Opening is non-destructive and Send is still the human gate, so a
        // transcribed open is fine. Only confirmation is typing-only.
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Spoken(router, "open chrome");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Equal(1, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_MultiLineMessage_IsNeverACommand()
    {
        // \A/\z anchors: "$" alone would match before a trailing newline and
        // "." doesn't cross newlines, so a multi-line message could otherwise
        // match on its first line only.
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Typed(router, "open chrome\nand summarize my tabs");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_OpenUnsupportedApp_ReturnsNotACommand_NeverCallsExecutor()
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Typed(router, "open Photoshop");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_OpenWithExtraWords_ReturnsNotACommand_NeverCallsExecutor()
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Typed(router, "open Chrome and also do something else");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.OpenCallCount);
    }

    [Fact]
    public async Task RouteAsync_OpenExecutorFails_ReturnsRejected()
    {
        var executor = new FakeAppExecutor { OpenResult = false };
        var router = new CommandRouter(executor);

        var result = await Typed(router, "open chrome");

        Assert.Equal(CommandOutcome.Rejected, result.Outcome);
        Assert.Contains("Chrome", result.ResultMessage);
    }

    [Fact]
    public async Task RouteAsync_CloseOpenOnlyApp_ReturnsRejectedWithExplanation_NotSilentFallthrough()
    {
        // v1 returned NotACommand here, which let the assistant answer "I've
        // closed File Explorer" while nothing happened. Declining out loud is
        // the honest outcome.
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Typed(router, "close explorer");

        Assert.Equal(CommandOutcome.Rejected, result.Outcome);
        Assert.Equal("I can't close File Explorer.", result.ResultMessage);
        Assert.Equal(0, executor.IsRunningCallCount);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_CloseAllowlistedButNotRunning_RepliesImmediately_NoConfirmationNeeded()
    {
        var executor = new FakeAppExecutor { IsRunningResult = false };
        var router = new CommandRouter(executor);

        var result = await Typed(router, "close chrome");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Contains("isn't running", result.ResultMessage);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_CloseRunningApp_AwaitsConfirmation_DoesNotCloseYet()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);

        var result = await Typed(router, "close chrome");

        Assert.Equal(CommandOutcome.AwaitingConfirmation, result.Outcome);
        Assert.Equal("Close Google Chrome? Unsaved work may be lost. Type 'confirm' or 'cancel'.", result.ResultMessage);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_TypedConfirmAfterPendingClose_ClosesExactlyOnce()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        var result = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Equal(1, executor.CloseCallCount);
        Assert.Equal(new[] { "chrome" }, executor.ClosedKeys);
    }

    // ---- The v2 rule: speech cannot confirm a destructive action ----

    [Fact]
    public async Task RouteAsync_TranscribedConfirm_DoesNotClose_AndLeavesPendingIntact()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        var spoken = await Spoken(router, "confirm");

        Assert.Equal(CommandOutcome.NotACommand, spoken.Outcome);
        Assert.Equal(0, executor.CloseCallCount);

        // The pending action survives — a typed confirm still works afterwards.
        var typed = await Typed(router, "confirm");
        Assert.Equal(CommandOutcome.Executed, typed.Outcome);
        Assert.Equal(1, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_TranscribedCancel_DoesNotClearPending()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        var spoken = await Spoken(router, "cancel");

        Assert.Equal(CommandOutcome.NotACommand, spoken.Outcome);

        var typed = await Typed(router, "confirm");
        Assert.Equal(CommandOutcome.Executed, typed.Outcome);
    }

    [Theory]
    [InlineData("Confirm")]
    [InlineData("CONFIRM")]
    [InlineData("  confirm  ")]
    public async Task RouteAsync_TypedConfirmVariants_AreAllHonored(string text)
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        var result = await Typed(router, text);

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
    }

    [Fact]
    public async Task RouteAsync_TypedCancelAfterPendingClose_NeverCloses()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        var result = await Typed(router, "cancel");

        Assert.Equal(CommandOutcome.Cancelled, result.Outcome);
        Assert.Equal("Cancelled.", result.ResultMessage);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_ConfirmWithNoPendingAction_ReturnsNotACommand()
    {
        var executor = new FakeAppExecutor();
        var router = new CommandRouter(executor);

        var result = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_CancelWithNoPendingAction_ReturnsNotACommand()
    {
        var router = new CommandRouter(new FakeAppExecutor());

        Assert.Equal(CommandOutcome.NotACommand, (await Typed(router, "cancel")).Outcome);
    }

    [Fact]
    public async Task RouteAsync_ConfirmAfterExpiry_TreatsAsNotACommand_DoesNotClose()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var time = new ManualTimeProvider();
        var router = new CommandRouter(executor, time);
        await Typed(router, "close chrome");

        time.UtcNow = time.UtcNow.AddSeconds(31);
        var result = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.NotACommand, result.Outcome);
        Assert.Equal(0, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_ConfirmWellInsideTheWindow_StillHonored()
    {
        // v1 named this test "AtExactlyThirtySeconds" and then advanced 29s.
        // Named for what it does now; the boundary itself is the next test.
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var time = new ManualTimeProvider();
        var router = new CommandRouter(executor, time);
        await Typed(router, "close chrome");

        time.UtcNow = time.UtcNow.AddSeconds(29);
        var result = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Equal(1, executor.CloseCallCount);
    }

    [Fact]
    public async Task RouteAsync_ConfirmAtExactlyThirtySeconds_StillHonored()
    {
        // The injected TimeProvider makes the literal boundary instant
        // deterministic — no floating-point excuse needed.
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var time = new ManualTimeProvider();
        var router = new CommandRouter(executor, time);
        await Typed(router, "close chrome");

        time.UtcNow = time.UtcNow.AddSeconds(30);
        var result = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
    }

    [Fact]
    public async Task RouteAsync_NewCloseRequestWhilePendingConfirmation_OverwritesPending()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        await Typed(router, "close notepad");
        await Typed(router, "confirm");

        Assert.Equal(1, executor.CloseCallCount);
        Assert.Equal(new[] { "notepad" }, executor.ClosedKeys);
    }

    [Fact]
    public async Task RouteAsync_TargetExitsBetweenPromptAndConfirm_ReportsNotRunning_DoesNotThrow()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true, CloseResult = AppCloseOutcome.NotRunning };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        var result = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.Executed, result.Outcome);
        Assert.Contains("isn't running", result.ResultMessage);
    }

    [Fact]
    public async Task RouteAsync_CloseExecutorFails_ReturnsRejected()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true, CloseResult = AppCloseOutcome.Failed };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");

        var result = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.Rejected, result.Outcome);
        Assert.Contains("Couldn't close", result.ResultMessage);
    }

    [Fact]
    public async Task RouteAsync_DuplicateConfirm_SecondCallIsNotACommand()
    {
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var router = new CommandRouter(executor);
        await Typed(router, "close chrome");
        await Typed(router, "confirm");

        var second = await Typed(router, "confirm");

        Assert.Equal(CommandOutcome.NotACommand, second.Outcome);
        Assert.Equal(1, executor.CloseCallCount);
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter CommandRouterTests`
Expected: FAIL (build error — `CommandRouter` doesn't exist).

- [ ] **Step 3: Write the implementation**

```csharp
using System.Text.RegularExpressions;

namespace Reva.Desktop.Services;

public sealed class CommandRouter : ICommandRouter
{
    // \A and \z rather than ^ and $: "$" also matches before a trailing
    // newline and "." does not cross newlines, so ^...$ would match the first
    // line of a multi-line message. A multi-line message is never a command.
    private static readonly Regex OpenPattern = new(
        @"\A/?(?:open|launch|start)\s+(.+)\z", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex ClosePattern = new(
        @"\A/?(?:close|quit)\s+(.+)\z", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly TimeSpan ConfirmationWindow = TimeSpan.FromSeconds(30);

    private readonly IAppExecutor _executor;
    private readonly TimeProvider _timeProvider;
    private PendingClose? _pending;

    public CommandRouter(IAppExecutor executor, TimeProvider? timeProvider = null)
    {
        _executor = executor;
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public Task<CommandRouteResult> RouteAsync(
        string text, CommandSource source, CancellationToken cancellationToken = default)
    {
        var trimmed = text.Trim();

        if (string.Equals(trimmed, "confirm", StringComparison.OrdinalIgnoreCase))
        {
            return source == CommandSource.Typed
                ? HandleConfirmAsync(cancellationToken)
                : IgnoredSpokenResolution();
        }

        if (string.Equals(trimmed, "cancel", StringComparison.OrdinalIgnoreCase))
        {
            return source == CommandSource.Typed
                ? Task.FromResult(HandleCancel())
                : IgnoredSpokenResolution();
        }

        var openMatch = OpenPattern.Match(trimmed);
        if (openMatch.Success)
        {
            return HandleOpenAsync(openMatch.Groups[1].Value, source, cancellationToken);
        }

        var closeMatch = ClosePattern.Match(trimmed);
        if (closeMatch.Success)
        {
            return HandleCloseRequestAsync(closeMatch.Groups[1].Value, cancellationToken);
        }

        return NotACommand();
    }

    private static Task<CommandRouteResult> NotACommand() =>
        Task.FromResult(new CommandRouteResult(CommandOutcome.NotACommand, null));

    /// <summary>A spoken "confirm"/"cancel" never resolves a pending
    /// destructive action — the pending action is left untouched to expire or
    /// be resolved by typing. Logged so the user's "I said confirm and nothing
    /// happened" has an explanation in the trace.</summary>
    private static Task<CommandRouteResult> IgnoredSpokenResolution()
    {
        DesktopLogger.Info("command.state=ConfirmIgnored reason=transcribed_source");
        return NotACommand();
    }

    private static string Normalize(string argument) => argument.Trim().ToLowerInvariant();

    private async Task<CommandRouteResult> HandleOpenAsync(
        string argument, CommandSource source, CancellationToken cancellationToken)
    {
        var descriptor = AppAllowlist.FindByAlias(Normalize(argument));
        if (descriptor is null)
        {
            return new CommandRouteResult(CommandOutcome.NotACommand, null);
        }

        DesktopLogger.Info(
            $"command.state=Matched action=Open app={descriptor.Key} source={source.ToString().ToLowerInvariant()}");
        var opened = await _executor.OpenAsync(descriptor, cancellationToken).ConfigureAwait(false);
        DesktopLogger.Info(
            opened
                ? $"command.state=Executed action=Open app={descriptor.Key} result=success"
                : $"command.state=Rejected action=Open app={descriptor.Key} reason=launch_failed");

        return opened
            ? new CommandRouteResult(CommandOutcome.Executed, $"Opened {descriptor.DisplayName}.")
            : new CommandRouteResult(CommandOutcome.Rejected, $"Couldn't open {descriptor.DisplayName}.");
    }

    private async Task<CommandRouteResult> HandleCloseRequestAsync(
        string argument, CancellationToken cancellationToken)
    {
        var descriptor = AppAllowlist.FindByAlias(Normalize(argument));
        if (descriptor is null)
        {
            // Unrecognized app — genuinely ambiguous ("close the loop"), so
            // ordinary chat is the right destination.
            return new CommandRouteResult(CommandOutcome.NotACommand, null);
        }

        if (descriptor.CloseProcessNames is null)
        {
            // Recognized app, deliberately open-only. Declining out loud beats
            // silence: silence lets the assistant invent a confirmation.
            DesktopLogger.Info($"command.state=Rejected action=Close app={descriptor.Key} reason=open_only");
            return new CommandRouteResult(
                CommandOutcome.Rejected, $"I can't close {descriptor.DisplayName}.");
        }

        var running = await _executor.IsRunningAsync(descriptor, cancellationToken).ConfigureAwait(false);
        if (!running)
        {
            DesktopLogger.Info($"command.state=Executed action=Close app={descriptor.Key} result=not_running");
            return new CommandRouteResult(CommandOutcome.Executed, $"{descriptor.DisplayName} isn't running.");
        }

        _pending = new PendingClose(descriptor, _timeProvider.GetUtcNow().Add(ConfirmationWindow));
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
        var outcomeToken = outcome switch
        {
            AppCloseOutcome.CloseRequested => "requested",
            AppCloseOutcome.NotRunning => "not_running",
            _ => "failed",
        };
        DesktopLogger.Info($"command.state=Confirmed action=Close app={descriptor.Key} result={outcomeToken}");

        return outcome switch
        {
            AppCloseOutcome.CloseRequested => new CommandRouteResult(
                CommandOutcome.Executed, $"Closing {descriptor.DisplayName}."),
            AppCloseOutcome.NotRunning => new CommandRouteResult(
                CommandOutcome.Executed, $"{descriptor.DisplayName} isn't running."),
            _ => new CommandRouteResult(
                CommandOutcome.Rejected, $"Couldn't close {descriptor.DisplayName}."),
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

Expiry uses `>` (strictly greater), so the instant at exactly 30.000s is still honored — pinned by `RouteAsync_ConfirmAtExactlyThirtySeconds_StillHonored`, which is deterministic because the `TimeProvider` is injected.

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter CommandRouterTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/CommandRouter.cs desktop/tests/Reva.Desktop.Tests/Unit/CommandRouterTests.cs
git commit -m "feat(desktop): add CommandRouter with source-aware confirm/cancel"
```

---

### Task 3: `WindowsAppExecutor` — the real process launcher

> **Erratum from Task 3 security-boundary review (2026-08-17):** the first Task 3 implementation preserved the security boundary, but `CloseAsync` still had correctness gaps. `CloseMainWindow() == false`, `CloseMainWindow()` `Win32Exception`, and `MainWindowHandle` `Win32Exception` must count as graceful-close failures; `InvalidOperationException` means the process exited during the race and is ignored. Outcome precedence is `CloseRequested` when any request succeeded, otherwise `Failed` when any failure occurred, otherwise `NotRunning`. `IsRunningAsync` treats `MainWindowHandle` `Win32Exception` conservatively as running. Every process handle must be disposed exactly once on every path, and safe UI/log messages must not include exception details.

> **Erratum from physical minimized-window acceptance (2026-08-17):** Chrome, Notepad, and Calculator close correctly while restored/on-screen, but the same allowlisted apps do not close while taskbar-minimized; restoring the minimized window and repeating the command succeeds. Task 3 must refresh process state before inspecting `MainWindowHandle`, keep `CloseMainWindow()` as the primary graceful path, and fall back only for matched allowlisted process IDs by enumerating eligible top-level normal/minimized windows and sending bounded `WM_CLOSE`. This fallback must not restore, focus, activate, kill, shell out, elevate, target unrelated processes, target hidden/background helper windows, or leak window titles/exception details.

Unit tests are now required for the process-runtime boundary because `System.Diagnostics.Process` outcomes are not deterministic enough to cover the review findings directly. Keep the abstraction internal to the Windows execution boundary; never expose it to command text or raw user input.

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/WindowsAppExecutor.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/WindowsAppExecutorTests.cs`

- [ ] **Step 1: Add review-regression tests first**

Cover: `CloseMainWindow()` false -> `Failed`; `CloseMainWindow()` `Win32Exception` -> `Failed`; all matching processes exited -> `NotRunning`; one success plus one failure -> `CloseRequested`; `MainWindowHandle` `Win32Exception` during close -> `Failed`; `MainWindowHandle` `Win32Exception` during `IsRunningAsync` -> `true`; every process disposed exactly once; exception details absent from safe messages/logs; no match remains `NotRunning`; and the existing allowlist/security tests remain green.

- [ ] **Step 2: Implement**

```csharp
using System.ComponentModel;
using System.Diagnostics;

namespace Reva.Desktop.Services;

/// <summary>The only file in the app that touches System.Diagnostics.Process.
/// Every operation runs on the thread pool: Process.Start with
/// UseShellExecute=true blocks while the shell resolves and launches the
/// target, and process enumeration is not instant either — neither belongs on
/// the UI thread.</summary>
public sealed class WindowsAppExecutor : IAppExecutor
{
    public Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                try
                {
                    var startInfo = new ProcessStartInfo
                    {
                        FileName = descriptor.OpenTarget,   // fixed literal, never user input
                        UseShellExecute = true,
                    };
                    using var process = Process.Start(startInfo);

                    // ms-settings: and other shell protocol handlers legitimately
                    // return null from Process.Start even on success, so a null
                    // process is only a failure for entries that launch an exe.
                    return process is not null || IsShellProtocol(descriptor.OpenTarget);
                }
                catch (Exception ex) when (
                    ex is Win32Exception or InvalidOperationException or System.IO.FileNotFoundException)
                {
                    DesktopLogger.Info($"command.state=Rejected action=Open app={descriptor.Key} reason=launch_failed");
                    return false;
                }
            },
            cancellationToken);

    public Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                var matches = FindRunningProcesses(descriptor);
                try
                {
                    return matches.Count > 0;
                }
                finally
                {
                    DisposeAll(matches);
                }
            },
            cancellationToken);

    public Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                var matches = FindRunningProcesses(descriptor);
                if (matches.Count == 0)
                {
                    return AppCloseOutcome.NotRunning;
                }

                try
                {
                    var requested = 0;
                    var failed = 0;
                    foreach (var process in matches)
                    {
                        try
                        {
                            // Polite request only — the target may ignore it or
                            // raise its own "save changes?" prompt. Never Kill().
                            // CloseMainWindow() can return false (no window
                            // handle, or the window is disabled by a modal
                            // dialog) without throwing — that's a genuine
                            // failure to deliver the close, not a success.
                            if (process.CloseMainWindow())
                            {
                                requested++;
                            }
                            else
                            {
                                failed++;
                            }
                        }
                        catch (InvalidOperationException)
                        {
                            // The process exited between enumeration and this
                            // call — up to 30 seconds can pass while the user
                            // decides. Not a failure; just nothing left to close.
                        }
                        catch (Win32Exception)
                        {
                            // Access denied or the window is unresponsive — a
                            // genuine failure to close a process that is still
                            // running, distinct from "already exited."
                            failed++;
                        }
                    }

                    if (requested > 0)
                    {
                        return AppCloseOutcome.CloseRequested;
                    }

                    return failed > 0 ? AppCloseOutcome.Failed : AppCloseOutcome.NotRunning;
                }
                finally
                {
                    DisposeAll(matches);
                }
            },
            cancellationToken);

    private static bool IsShellProtocol(string target) => target.EndsWith(':');

    private static List<Process> FindRunningProcesses(AppDescriptor descriptor)
    {
        var matches = new List<Process>();
        foreach (var name in descriptor.CloseProcessNames ?? Array.Empty<string>())
        {
            foreach (var process in Process.GetProcessesByName(name))
            {
                try
                {
                    if (process.MainWindowHandle != IntPtr.Zero)
                    {
                        matches.Add(process);
                        continue;
                    }
                }
                catch (InvalidOperationException)
                {
                    // Exited while we were enumerating.
                }

                process.Dispose();
            }
        }

        return matches;
    }

    private static void DisposeAll(List<Process> processes)
    {
        foreach (var process in processes)
        {
            process.Dispose();
        }
    }
}
```

Three v1 defects fixed here: the whole class was synchronous-on-the-UI-thread; `CloseMainWindow()` could throw `InvalidOperationException` on a process that exited during the confirmation window, with no catch anywhere up the stack; and non-matching processes returned by `GetProcessesByName` were never disposed (v1 filtered with LINQ and disposed only the survivors).

- [ ] **Step 3: Build and test**

Run: focused `WindowsAppExecutor` tests, command-router tests, complete Desktop suite, and Release build.
Expected: succeeds, 0 failures.

- [ ] **Step 4: Focused re-review**

Review outcome mapping, process disposal, absence of leaked exception details, and unchanged security boundaries: no `Process.Kill`, no shell/PowerShell invocation, no elevation, no raw user input in `ProcessStartInfo`, and no arbitrary paths.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/WindowsAppExecutor.cs desktop/tests/Reva.Desktop.Tests/Unit/WindowsAppExecutorTests.cs
git commit -m "fix(desktop): report graceful app-close failures accurately"
```

---

### Task 4: Composer source tracking

The new work v1 didn't know it needed. Without this, `CommandSource` is a parameter nobody can supply honestly.

**Files:**
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs`

**Interfaces:**
- Produces: `AssistantViewModel.ComposerSource` (`CommandSource`, read-only) — `Transcribed` while the composer holds text that came from STT and has not been edited since; `Typed` otherwise.

- [ ] **Step 1: Write the failing tests**

```csharp
    [Fact]
    public void ComposerSource_Initially_IsTyped()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient());

        Assert.Equal(CommandSource.Typed, viewModel.ComposerSource);
    }

    [Fact]
    public async Task ComposerSource_AfterTranscription_IsTranscribed()
    {
        var client = TranscribingClient("confirm");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(CommandSource.Transcribed, viewModel.ComposerSource);
    }

    [Fact]
    public async Task ComposerSource_AfterUserEditsTranscribedText_ReturnsToTyped()
    {
        // Editing is an act of authorship — once the user has touched the text
        // it is theirs, and a typed confirm should work normally.
        var client = TranscribingClient("confirm");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));
        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        viewModel.ComposerText = "confirm";   // simulates SyncComposerTextFromTextBox

        Assert.Equal(CommandSource.Typed, viewModel.ComposerSource);
    }

    [Fact]
    public async Task ComposerSource_AfterSend_ResetsToTyped()
    {
        // TranscribingClient() can't be reused here — its SendMessageAsync
        // responder deliberately throws, since every other test using it
        // asserts the transcription-only slice never sends. This test needs
        // both paths to succeed: transcribe, then actually send.
        var client = new FakeCoreClient(
            (_, _) => Task.FromResult(CoreResult<TypedMessageResponse>.Success(new TypedMessageResponse("ok"))),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => throw new NotSupportedException());
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));
        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        await viewModel.SendMessageAsync();

        Assert.Equal(CommandSource.Typed, viewModel.ComposerSource);
    }
```

(v1 of this test used `TranscribingClient("hello")`, whose `SendMessageAsync` responder deliberately throws `NotSupportedException` — every other test using that helper asserts the transcription-only slice never sends. This test needs both calls to succeed, so it can't reuse that shared fake; construct a `FakeCoreClient` directly with working responders for both instead. Adapt the exact `FakeCoreClient`/`CoreResult`/`TypedMessageResponse` construction to whatever the current test file's constructor shapes are — check `ImmediateSuccessClient()`'s definition in the same file for the pattern.)

- [ ] **Step 2: Run to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter ComposerSource`
Expected: FAIL to build — no `ComposerSource` property.

- [ ] **Step 3: Implement**

The public `ComposerText` setter marks the composer as typed; transcription writes through a private path that marks it transcribed.

```csharp
    private CommandSource _composerSource = CommandSource.Typed;

    public CommandSource ComposerSource => _composerSource;

    public string ComposerText
    {
        get => _composerText;
        set
        {
            // Any write through the public setter is user authorship — the
            // x:Bind TwoWay path and every test call site land here. This is
            // unconditional, not gated on SetProperty's change-detection:
            // re-typing the same text the transcript just produced (e.g. a
            // TextBox sync firing after a no-op edit) must still count as
            // authorship and pull the source back to Typed, even though the
            // field's value doesn't actually change.
            SetProperty(ref _composerText, value);
            _composerSource = CommandSource.Typed;
        }
    }

    /// <summary>The transcription path's write. Same append semantics as a
    /// user edit, but marks the text as machine-authored so a spoken
    /// "confirm" can't resolve a pending destructive command.</summary>
    private void AppendTranscribedText(string text)
    {
        var merged = string.IsNullOrWhiteSpace(_composerText)
            ? text
            : $"{_composerText.TrimEnd()} {text}";

        SetProperty(ref _composerText, merged, nameof(ComposerText));
        _composerSource = CommandSource.Transcribed;   // after the setter, not before
    }
```

(v1 of this snippet called a `RaiseSendAvailabilityProperties()` — that method does not exist anywhere in the codebase; it was invented for this task's sample without validating it against the file. No property computed today depends on `ComposerText`, so there is nothing for such a call to raise. Both calls are simply omitted; do not add a stub method with undefined behavior to satisfy them. v1's `ComposerText` setter also gated the `_composerSource = Typed` assignment inside `if (SetProperty(...))` — `ObservableObject.SetProperty` returns `false` and no-ops on a same-value reassignment, so re-syncing identical text after a transcription would leave the source stuck at `Transcribed`. The assignment is unconditional here for that reason.)

In `FinishVoiceInputAsync`'s success branch, replace the inline append with `AppendTranscribedText(text);`.

In `SendMessageCoreAsync`, after the existing composer clear, reset `_composerSource = CommandSource.Typed;` — an empty composer has no author.

- [ ] **Step 4: Run to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: PASS — including every pre-existing voice test, since `AppendTranscribedText` reproduces the exact append behavior they already assert.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "feat(desktop): track whether composer text was typed or transcribed"
```

---

### Task 5: `AssistantViewModel` routing integration

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/NullCommandRouter.cs`
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs`

- [ ] **Step 1: Write `NullCommandRouter`**

```csharp
namespace Reva.Desktop.Services;

/// <summary>Null-object default for AssistantViewModel's optional
/// command-router dependency, mirroring UnavailableVoiceDevice — every
/// message is NotACommand, so call sites that don't pass a router behave
/// exactly as before this slice.</summary>
public sealed class NullCommandRouter : ICommandRouter
{
    public Task<CommandRouteResult> RouteAsync(
        string text, CommandSource source, CancellationToken cancellationToken = default) =>
        Task.FromResult(new CommandRouteResult(CommandOutcome.NotACommand, null));
}
```

- [ ] **Step 2: Write the failing tests**

```csharp
    private sealed class FakeCommandRouter : ICommandRouter
    {
        private readonly Func<string, CommandSource, CommandRouteResult> _responder;

        public FakeCommandRouter(Func<string, CommandSource, CommandRouteResult> responder) =>
            _responder = responder;

        public int CallCount { get; private set; }

        public List<(string Text, CommandSource Source)> Received { get; } = new();

        public Task<CommandRouteResult> RouteAsync(
            string text, CommandSource source, CancellationToken cancellationToken = default)
        {
            CallCount++;
            Received.Add((text, source));
            return Task.FromResult(_responder(text, source));
        }
    }

    private static FakeCommandRouter PassthroughRouter() =>
        new((_, _) => new CommandRouteResult(CommandOutcome.NotACommand, null));

    private static FakeCommandRouter RecognizingRouter(CommandOutcome outcome, string message) =>
        new((_, _) => new CommandRouteResult(outcome, message));
```

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
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException("router-recognized command must never reach Core"));
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
    public async Task SendMessageAsync_TypedText_PassesTypedSourceToRouter()
    {
        var router = PassthroughRouter();
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), commandRouter: router)
        {
            ComposerText = "confirm",
        };

        await viewModel.SendMessageAsync();

        Assert.Equal(CommandSource.Typed, router.Received.Single().Source);
    }

    [Fact]
    public async Task SendMessageAsync_TranscribedText_PassesTranscribedSourceToRouter()
    {
        // The end-to-end proof of the v2 rule: a spoken "confirm" reaches the
        // router labelled as speech, and the router (Task 2) refuses to let it
        // resolve a pending close.
        var client = TranscribingClient("confirm");
        var router = PassthroughRouter();
        var viewModel = new AssistantViewModel(
            client,
            new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))),
            commandRouter: router);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();
        await viewModel.SendMessageAsync();

        Assert.Equal(CommandSource.Transcribed, router.Received.Single().Source);
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
    public async Task SendMessageAsync_RouterAwaitingConfirmation_ShowsPrompt_NeverCallsCore()
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
    public async Task SendMessageAsync_RouterRejects_ShowsRejectionInsteadOfAskingTheAssistant()
    {
        var client = new FakeCoreClient((_, _) => throw new NotSupportedException());
        var router = RecognizingRouter(CommandOutcome.Rejected, "I can't close File Explorer.");
        var viewModel = new AssistantViewModel(client, commandRouter: router) { ComposerText = "close explorer" };

        await viewModel.SendMessageAsync();

        Assert.Equal(0, client.CallCount);
        Assert.Equal("I can't close File Explorer.", viewModel.Messages[1].Text);
    }

    [Fact]
    public async Task SendMessageAsync_NoCommandRouterProvided_BehavesExactlyAsBeforeThisSlice()
    {
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

    [Fact]
    public async Task SendMessageAsync_RouterThrows_SurfacesSafeErrorAndClearsPending()
    {
        // WindowsAppExecutor catches its own OS exceptions, but a bug in the
        // router must not leave the UI stuck with Send disabled forever.
        var router = new FakeCommandRouter((_, _) => throw new InvalidOperationException("boom"));
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), commandRouter: router)
        {
            ComposerText = "open chrome",
        };

        await viewModel.SendMessageAsync();

        Assert.False(viewModel.IsPending);
        Assert.NotNull(viewModel.ErrorMessage);
    }
```

- [ ] **Step 3: Run to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: FAIL to build — no 4-arg constructor.

- [ ] **Step 4: Implement**

Add the field and constructor parameter:

```csharp
    private readonly ICommandRouter _commandRouter;

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

        if (_lifecycle is not null)
        {
            _lifecycle.StateChanged += OnLifecycleStateChanged;
        }
    }
```

In `SendMessageCoreAsync`, capture the source **before** the composer is cleared, then insert the router call as the first statement in the existing `try`:

```csharp
        var source = _composerSource;   // captured before the clear below resets it
        // ... existing Messages.Add(FromUser(trimmed)) and composer clear ...

        try
        {
            var routeResult = await _commandRouter.RouteAsync(trimmed, source, cancellationToken)
                .ConfigureAwait(true);
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

            ErrorMessage = result.Error!.SafeMessage;
            return null;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            ErrorMessage = "Something went wrong sending that message. Try again.";
            return null;
        }
        finally
        {
            IsPending = false;
            RaiseVoiceAvailabilityProperties();
        }
```

`ConfigureAwait(true)` on the router call is deliberate: `Messages` is bound to the UI and must be mutated on the UI thread. `WindowsAppExecutor` already moved its blocking work to the pool, so the UI thread is only parked, not busy.

**Ordering note.** `source` must be read before the composer clear, because the clear resets `_composerSource` to `Typed`. Reading it after would label every transcribed message as typed and silently defeat this entire slice's safety rule.

(v1 of the catch clause above called `SetSafeError()` — that method does not exist anywhere in the codebase, and its described filter semantics were self-contradictory with this task's own `SendMessageAsync_RouterThrows_SurfacesSafeErrorAndClearsPending` test, which requires `SendMessageAsync` to complete normally rather than propagate. Replaced with a standard two-catch block matching the exact convention already used elsewhere in this class, e.g. `FinishVoiceInputAsync`.)

- [ ] **Step 5: Run to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: PASS — every pre-existing test plus the new ones.

- [ ] **Step 6: Full suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/NullCommandRouter.cs desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "feat(desktop): route recognized app-commands before the assistant pipeline"
```

---

### Task 6: Wire the composition root

**Files:**
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml.cs`, `desktop/src/Reva.Desktop/App.xaml.cs`

- [ ] **Step 1: `MainWindow.xaml.cs`**

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

```csharp
        var commandRouter = new CommandRouter(new WindowsAppExecutor());

        _window = new MainWindow(coreClient, lifecycle, new WindowsVoiceDevice(), commandRouter);
```

- [ ] **Step 3: Build and run the full suite**

Run: `dotnet build desktop/Reva.Desktop.sln` then `dotnet test desktop/Reva.Desktop.sln`
Expected: both succeed, 0 failures.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/Reva.Desktop/MainWindow.xaml.cs desktop/src/Reva.Desktop/App.xaml.cs
git commit -m "feat(desktop): wire CommandRouter/WindowsAppExecutor into the composition root"
```

---

### Task 7: Physical acceptance run

**Files:** none (verification task).

- [ ] **Step 1: Full automated suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures. Green before touching a real process.

- [ ] **Step 2: Build Release and run it**

`dotnet build desktop/Reva.Desktop.sln -c Release`, then run the produced `Reva.Desktop.exe` with `reva_core` reachable (same setup as the transcription slice's Task 9).

- [ ] **Step 3: Open acceptance — one per allowlist entry**

For each of `/open chrome`, `open Chrome`, `launch Notepad`, `start Calculator`, `open Edge`, `open VS Code`, `open File Explorer`, `open Settings`: type it, press Send. Confirm the typed text appears as a "You" message, a "REVA" message follows ("Opened X."), the target window actually appears, and **no** `v1/messages` POST hits Core for that turn.

Record `open VS Code` specifically: if it fails, the design's HKCU App Paths assumption is wrong and the `%LOCALAPPDATA%` fallback goes into the descriptor as a recorded finding.

- [ ] **Step 4: UI responsiveness during a cold launch**

Close Chrome entirely, then `open chrome` from a cold start. **The REVA window must stay responsive while Chrome launches** — drag the window, scroll the message list. A freeze here means `Task.Run` didn't take effect and Task 3 needs revisiting.

- [ ] **Step 5: Close + typed confirm**

With Chrome running, type `close Chrome` → confirm the prompt appears → type `confirm` → Chrome's window closes (or prompts to save) and "Closing Google Chrome." appears.

- [ ] **Step 6: Close + cancel**

Open Notepad, type `close Notepad`, then `cancel`. Notepad stays open; "Cancelled." appears.

- [ ] **Step 7: THE SPOKEN-CONFIRM CHECK — the reason this plan is v2**

With Notepad open **and unsaved text in it**, type `close Notepad` and wait for the prompt. Then use Hold-to-Talk and say "confirm". Release, and press Send.

Confirm: **Notepad does not close.** The message goes to the assistant as ordinary chat. `command.state=ConfirmIgnored reason=transcribed_source` appears in the desktop log. Then type `confirm` and verify it *does* close, proving the pending action survived the spoken attempt.

If Notepad closes on the spoken confirm, stop — Task 4's source tracking or Task 5's capture-before-clear ordering is wrong, and that is the one defect in this slice that destroys user data.

- [ ] **Step 8: Race check — target closed during the window**

Open Calculator, type `close Calculator`, then close Calculator yourself with the mouse, then type `confirm`. Expect "Calculator isn't running." and **no unhandled exception dialog**. This is the v1 crash path.

- [ ] **Step 9: Not-running, fallthrough, and open-only**

- No Calculator open → `close Calculator` → immediate "Calculator isn't running.", no prompt.
- `open Photoshop` → ordinary assistant reply (watch for the `v1/messages` request).
- `close explorer` and `close settings` → "I can't close File Explorer." / "I can't close Windows Settings.", **not** an assistant reply. (v1 expected fallthrough here; v2 deliberately changed it.)

- [ ] **Step 10: Report**

Which of the 8 opens succeeded; the confirm/cancel/not-running/fallthrough/open-only results; the spoken-confirm result from Step 7 verbatim; the race result from Step 8; UI responsiveness from Step 4; and confirmation that no `reva_core` request occurred for any routed command (cross-check Core's request log for the window).

- [ ] **Step 11: Commit any last-mile fixes**

```bash
git status
git add -A
git commit -m "fix(desktop): address app-command acceptance findings"
```

---

## Coverage table

Replaces v1's prose self-review, which asserted full coverage without demonstrating it.

| Requirement | Test / step | Task |
|---|---|---|
| Allowlist is exactly 7 fixed entries | `All_HasExactlySevenEntries` | 1 |
| No shell or REVA in the allowlist | `All_NoEntryTargetsAShellOrRevaItself` | 1 |
| Aliases unique and lowercase | `All_AliasesAreUnique…`, `All_AliasesAreAlreadyLowercase` | 1 |
| Exact-alias matching (injection defense) | `FindByAlias_UnknownOrInjectionLike…`, `RouteAsync_OpenWithExtraWords…` | 1, 2 |
| Multi-line input is never a command | `RouteAsync_MultiLineMessage_IsNeverACommand` | 2 |
| Open verbs + `/` prefix + case-insensitivity | `RouteAsync_RecognizedOpenCommand…` (6 cases) | 2 |
| Open failure is reported safely | `RouteAsync_OpenExecutorFails_ReturnsRejected` | 2 |
| Close on a running app prompts first | `RouteAsync_CloseRunningApp_AwaitsConfirmation…` | 2 |
| Close on a stopped app answers immediately | `RouteAsync_CloseAllowlistedButNotRunning…` | 2 |
| Open-only apps decline out loud | `RouteAsync_CloseOpenOnlyApp_ReturnsRejected…`, Step 9 | 2, 7 |
| **Spoken confirm cannot close** | `RouteAsync_TranscribedConfirm…`, `…TranscribedCancel…`, `SendMessageAsync_TranscribedText_PassesTranscribedSource…`, **Step 7** | 2, 5, 7 |
| Spoken open is still honored | `RouteAsync_SpokenOpenCommand_IsHonored` | 2 |
| 30s expiry boundary | `…AfterExpiry…`, `…WellInsideTheWindow…`, `…AtExactlyThirtySeconds…` | 2 |
| Last-write-wins on a new close | `RouteAsync_NewCloseRequestWhilePending…` | 2 |
| Duplicate confirm is inert | `RouteAsync_DuplicateConfirm…` | 2 |
| Target exits during the window | `…TargetExitsBetweenPromptAndConfirm…`, **Step 8** | 2, 7 |
| Graceful close failure mapping | `WindowsAppExecutorTests` false/Win32/handle-failure/mixed-result cases | 3 |
| Minimized allowlisted windows close gracefully | `CloseAsync_MinimizedEligibleWindow_ReceivesBoundedCloseRequest`, physical minimized-window acceptance | 3, 7 |
| Fallback targets only matched app windows | `CloseAsync_UnrelatedProcessWindows_AreNeverTargeted`, `CloseAsync_HiddenOrOwnedHelperWindows_AreNeverTargeted` | 3 |
| Process handles disposed once | `CloseAsync_EveryEnumeratedProcess_DisposedExactlyOnce`, `OpenAsync_ReturnedProcessHandle_DisposedExactlyOnce` | 3 |
| Window wrappers disposed once | `CloseAsync_EveryEnumeratedWindow_DisposedExactlyOnce` | 3 |
| Inaccessible `MainWindowHandle` is running | `IsRunningAsync_MainWindowHandleThrowsWin32Exception_ReturnsTrue` | 3 |
| Never `Kill()` | Code review of `WindowsAppExecutor`; Step 5 (save prompt appears) | 3, 7 |
| No UI-thread process work | Step 4 | 3, 7 |
| Source tracking typed/transcribed/edited/reset | 4 `ComposerSource_*` tests | 4 |
| Recognized command never reaches Core | `SendMessageAsync_RouterRecognizesCommand_NeverCallsCore`, Step 3 | 5, 7 |
| Non-command path unchanged | `…FallsThroughToCoreUnchanged`, `…NoCommandRouterProvided…`, full suite each task | 5 |
| Router bug can't wedge the UI | `SendMessageAsync_RouterThrows…` | 5 |

**Not covered by automated tests, by design:** real OS process behavior such as whether `Code.exe`/`CalculatorApp` resolve on this specific machine and whether launched windows appear/respond physically (Task 7). The deterministic `WindowsAppExecutor` outcome mapping and disposal rules are covered through the internal process-runtime boundary.

**Commit granularity:** seven tasks, seven commits, each independently revertible. Task 3's executor has no compile-time dependents until Task 6; Task 4's source tracking is additive and useful on its own; Task 5's ViewModel change is an optional parameter, so reverting it alone leaves Tasks 1-4 intact.
