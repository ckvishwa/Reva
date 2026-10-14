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
