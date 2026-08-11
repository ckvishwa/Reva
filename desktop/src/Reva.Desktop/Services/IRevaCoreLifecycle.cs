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
