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
