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
        // Elapsed time is tracked logically (accumulated poll interval),
        // never via real wall-clock (DateTimeOffset.UtcNow deadline) — a
        // wall-clock deadline would keep this loop spinning for the full
        // real HealthTimeout even when a test injects a no-op _delay,
        // defeating the seam's entire purpose (see ctor doc comment).
        var elapsed = TimeSpan.Zero;
        while (elapsed < HealthTimeout)
        {
            var result = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
            if (result.IsSuccess)
            {
                return true;
            }

            await _delay(HealthPollInterval, cancellationToken).ConfigureAwait(true);
            elapsed += HealthPollInterval;
        }

        return false;
    }

    private async Task<bool> WaitForTokenAsync(CancellationToken cancellationToken)
    {
        // See WaitForHealthAsync: elapsed is logical, not wall-clock, so the
        // injected _delay seam genuinely avoids real waiting in tests.
        var elapsed = TimeSpan.Zero;
        while (elapsed < TokenTimeout)
        {
            var result = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(true);
            if (result.IsAvailable)
            {
                return true;
            }

            await _delay(TokenPollInterval, cancellationToken).ConfigureAwait(true);
            elapsed += TokenPollInterval;
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
