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
