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
            $"command.state=Executed action=Open app={descriptor.Key} result={(opened ? "success" : "failed")}");

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
        DesktopLogger.Info($"command.state=Confirmed action=Close app={descriptor.Key} result={outcome}");

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
