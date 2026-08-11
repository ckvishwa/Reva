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

    private const string StartLockName = @"Local\Reva.Desktop.CoreLifecycle.Start";
    private static readonly TimeSpan StartLockTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan MonitorInterval = TimeSpan.FromSeconds(5);
    private const int MaxRelaunchAttempts = 3;

    private readonly IRevaCoreClient _coreClient;
    private readonly ILocalTokenProvider _tokenProvider;
    private readonly ICoreExecutableLocator _executableLocator;
    private readonly ICoreProcessLauncher _processLauncher;
    private readonly DesktopConfiguration _configuration;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;

    private ICoreProcessHandle? _ownedProcess;
    private CancellationTokenSource? _monitorCts;
    private int _relaunchAttempts;

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

        using (var startLock = new Mutex(initiallyOwned: false, StartLockName))
        {
            var acquired = startLock.WaitOne(StartLockTimeout);
            try
            {
                // Re-probe after acquiring the lock: whoever got here first may
                // have already finished launching Core while this instance was
                // waiting on the mutex.
                if (acquired)
                {
                    var reprobe = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
                    if (reprobe.IsSuccess)
                    {
                        await FinishConnectingAsync(cancellationToken).ConfigureAwait(true);
                        return;
                    }
                }

                var resolution = _executableLocator.Resolve();
                if (!resolution.IsAvailable)
                {
                    DesktopLogger.Warn($"REVA Core executable resolution failed: {resolution.FailureReason}");
                    SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
                    return;
                }

                _ownedProcess = _processLauncher.Launch(
                    resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
            }
            finally
            {
                if (acquired)
                {
                    startLock.ReleaseMutex();
                }
            }
        }

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
        _monitorCts?.Cancel();
        _monitorCts = null;
    }

    public void Dispose()
    {
        StopMonitoring();
        _ownedProcess?.Dispose();
    }

    private async Task FinishConnectingAsync(CancellationToken cancellationToken)
    {
        var tokenAvailable = await WaitForTokenAsync(cancellationToken).ConfigureAwait(true);
        SetState(
            tokenAvailable ? CoreLifecycleState.Connected : CoreLifecycleState.AuthorizationUnavailable,
            tokenAvailable ? "Core Connected" : "REVA authorization unavailable");

        if (tokenAvailable)
        {
            StartMonitor();
        }
    }

    private void StartMonitor()
    {
        _monitorCts?.Cancel();
        _monitorCts = new CancellationTokenSource();
        // Task.Run (not a bare fire-and-forget call): when _delay resolves
        // synchronously (test doubles), every await in RunMonitorLoopAsync
        // completes without yielding, so the loop body runs inline on
        // whichever thread first calls StartMonitor — blocking StartAsync's
        // caller forever, since nothing else can ever reach _monitorCts.Cancel().
        // Task.Run moves that execution to the thread pool so this method,
        // and therefore StartAsync, always returns promptly.
        _ = Task.Run(() => RunMonitorLoopAsync(_monitorCts.Token));
    }

    private async Task RunMonitorLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            await _delay(MonitorInterval, cancellationToken).ConfigureAwait(true);
            if (cancellationToken.IsCancellationRequested)
            {
                return;
            }

            await RunMonitorIterationAsync().ConfigureAwait(true);
        }
    }

    /// <summary>One reconnect check. Public so tests can drive a single
    /// iteration deterministically instead of racing the real timer loop.</summary>
    public async Task RunMonitorIterationAsync()
    {
        var health = await _coreClient.GetHealthAsync().ConfigureAwait(true);
        if (health.IsSuccess)
        {
            _relaunchAttempts = 0;
            if (State != CoreLifecycleState.Connected)
            {
                await FinishConnectingAsync(CancellationToken.None).ConfigureAwait(true);
            }
            return;
        }

        SetState(CoreLifecycleState.Unavailable, "Core Unavailable");

        // Only relaunch a process this instance owns and watched exit —
        // never touch a Core this instance merely attached to (rule: never
        // kill or replace a process Desktop didn't start).
        if (_ownedProcess is { HasExited: true } && _relaunchAttempts < MaxRelaunchAttempts)
        {
            _relaunchAttempts++;
            var resolution = _executableLocator.Resolve();
            if (resolution.IsAvailable)
            {
                _ownedProcess.Dispose();
                _ownedProcess = _processLauncher.Launch(
                    resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
            }
        }
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
