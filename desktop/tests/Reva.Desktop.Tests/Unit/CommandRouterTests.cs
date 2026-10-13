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
