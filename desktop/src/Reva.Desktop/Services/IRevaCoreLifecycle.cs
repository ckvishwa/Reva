namespace Reva.Desktop.Services;

public interface IRevaCoreLifecycle
{
    CoreLifecycleState State { get; }

    /// <summary>Whether this instance owns the Core process it is
    /// connected to (launched it) or merely attached to one it found
    /// already running. See <see cref="CoreOwnership"/>.</summary>
    CoreOwnership Ownership { get; }

    /// <summary>The exact UI-facing text for <see cref="State"/> — one of
    /// "Starting Core…", "Core Connected", "Core Unavailable",
    /// "REVA authorization unavailable".</summary>
    string StatusText { get; }

    event EventHandler? StateChanged;

    Task StartAsync(CancellationToken cancellationToken = default);

    void StopMonitoring();

    /// <summary>Cancels all pending lifecycle work (monitor loop, any
    /// in-flight recovery), awaits it actually stopping, then — only if
    /// <see cref="Ownership"/> is <see cref="CoreOwnership.Owned"/> — stops
    /// the Core process. The real app-shutdown path; see the implementing
    /// type's synchronous <c>Dispose</c> for the test-only fallback.</summary>
    Task ShutdownAsync();
}
