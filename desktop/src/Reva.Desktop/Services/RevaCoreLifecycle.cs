using System.Diagnostics;

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
    private Task? _monitorLoopTask;
    private int _relaunchAttempts;
    private bool _disposed;

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

    /// <summary>Defaults to <see cref="CoreOwnership.External"/> — the safe
    /// value — until <see cref="StartAsync"/> decides otherwise at its one
    /// attach-or-launch decision point.</summary>
    public CoreOwnership Ownership { get; private set; } = CoreOwnership.External;

    public string StatusText { get; private set; } = "Starting Core…";

    public event EventHandler? StateChanged;

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        var opId = NewOperationId("start");
        DesktopLogger.Info("startup begin", opId);
        SetState(CoreLifecycleState.Starting);

        var probe = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
        DesktopLogger.Info($"health check (initial probe): {(probe.IsSuccess ? "pass" : $"fail ({probe.Error!.Kind})")}", opId);
        if (probe.IsSuccess)
        {
            Ownership = CoreOwnership.External;
            await FinishConnectingAsync(cancellationToken, opId).ConfigureAwait(true);
            DesktopLogger.Info("startup end (attached, no launch)", opId);
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
            DesktopLogger.Info("startup end (unavailable: non-ambiguous probe failure)", opId);
            return;
        }

        using (var startLock = new Mutex(initiallyOwned: false, StartLockName))
        {
            var acquired = startLock.WaitOne(StartLockTimeout);
            if (!acquired)
            {
                // Could not confirm exclusive ownership of the launch decision
                // within the timeout — fail safe rather than risk launching a
                // second process against an already-occupied port (the whole
                // point of this lock).
                DesktopLogger.Warn("Timed out waiting for the Core start lock; treating Core as unavailable.", opId);
                SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
                return;
            }

            try
            {
                // Re-probe after acquiring the lock: whoever got here first may
                // have already finished launching Core while this instance was
                // waiting on the mutex.
                var reprobe = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
                DesktopLogger.Info($"health check (post-lock reprobe): {(reprobe.IsSuccess ? "pass" : $"fail ({reprobe.Error!.Kind})")}", opId);
                if (reprobe.IsSuccess)
                {
                    Ownership = CoreOwnership.External;
                    await FinishConnectingAsync(cancellationToken, opId).ConfigureAwait(true);
                    DesktopLogger.Info("startup end (attached after lock race, no launch)", opId);
                    return;
                }

                var resolution = _executableLocator.Resolve();
                if (!resolution.IsAvailable)
                {
                    DesktopLogger.Warn($"REVA Core executable resolution failed: {resolution.FailureReason}", opId);
                    SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
                    DesktopLogger.Info("startup end (unavailable: executable not resolved)", opId);
                    return;
                }

                try
                {
                    _ownedProcess = _processLauncher.Launch(
                        resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
                    Ownership = CoreOwnership.Owned;
                    DesktopLogger.Info($"launched owned Core process (pid={_ownedProcess.Pid?.ToString() ?? "unknown"})", opId);
                }
                catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // Process.Start can fail for reasons outside our control
                    // (AV blocking, path-length limits, permissions) — degrade
                    // to Unavailable rather than crashing the app via the
                    // unhandled exception this would otherwise become inside
                    // App.OnLaunched's async void.
                    DesktopLogger.Warn($"Failed to launch REVA Core: {ex.Message}", opId);
                    SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
                    DesktopLogger.Info("startup end (unavailable: launch failed)", opId);
                    return;
                }
            }
            finally
            {
                startLock.ReleaseMutex();
            }
        }

        var becameHealthy = await WaitForHealthAsync(cancellationToken).ConfigureAwait(true);
        if (!becameHealthy)
        {
            SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
            DesktopLogger.Info("startup end (unavailable: launched Core never became healthy)", opId);
            return;
        }

        await FinishConnectingAsync(cancellationToken, opId).ConfigureAwait(true);
        DesktopLogger.Info("startup end (connected)", opId);
    }

    public void StopMonitoring()
    {
        var cts = _monitorCts;
        _monitorCts = null;
        if (cts is not null)
        {
            DesktopLogger.Info("monitor loop stop requested");
            cts.Cancel();
        }
    }

    /// <summary>
    /// Synchronous best-effort shutdown for <see cref="IDisposable"/>
    /// callers (test convenience, `using var`). Real app shutdown should
    /// call <see cref="ShutdownAsync"/> instead — it additionally awaits
    /// the monitor loop's actual exit before stopping the owned process,
    /// closing the gap where a loop iteration mid-flight when Dispose is
    /// called could still be deciding to relaunch. Order matters here too:
    /// cancel first, then stop — stopping first would let the still-running
    /// monitor observe the exit and race to relaunch before it sees cancellation.
    /// </summary>
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        var opId = NewOperationId("shutdown");
        DesktopLogger.Info("shutdown begin", opId);
        _disposed = true;
        StopMonitoring();
        StopOwnedProcessIfAny();
        DesktopLogger.Info("shutdown end", opId);
    }

    /// <summary>The real shutdown path: cancels the lifecycle's background
    /// work first, awaits the monitor loop's actual exit (so a relaunch
    /// decision already in flight cannot race a subsequent Stop()), then
    /// stops the owned process. See <see cref="Dispose"/> for the
    /// synchronous best-effort fallback used by tests.</summary>
    public async Task ShutdownAsync()
    {
        if (_disposed)
        {
            return;
        }

        var opId = NewOperationId("shutdown");
        DesktopLogger.Info("shutdown begin", opId);
        _disposed = true;
        StopMonitoring();

        var loopTask = _monitorLoopTask;
        if (loopTask is not null)
        {
            await loopTask.ConfigureAwait(true);
        }

        StopOwnedProcessIfAny();
        DesktopLogger.Info("shutdown end", opId);
    }

    private void StopOwnedProcessIfAny()
    {
        // Ownership gates every stop/kill path (rule: never touch a Core
        // this instance merely attached to) — explicit check, not an
        // inferred null-check on _ownedProcess.
        if (Ownership != CoreOwnership.Owned || _ownedProcess is null)
        {
            return;
        }

        DesktopLogger.Info($"stopping owned Core process (pid={_ownedProcess.Pid?.ToString() ?? "unknown"})");
        _ownedProcess.Stop();
        _ownedProcess.Dispose();
        _ownedProcess = null;
    }

    private static string NewOperationId(string prefix) => $"{prefix}-{Guid.NewGuid().ToString("N")[..8]}";

    private async Task FinishConnectingAsync(CancellationToken cancellationToken, string? opId = null)
    {
        var tokenAvailable = await WaitForTokenAsync(cancellationToken).ConfigureAwait(true);
        SetState(
            tokenAvailable ? CoreLifecycleState.Connected : CoreLifecycleState.AuthorizationUnavailable,
            tokenAvailable ? "Core Connected" : "REVA authorization unavailable");
        DesktopLogger.Info($"token wait: {(tokenAvailable ? "available" : "timed out")}", opId);

        if (tokenAvailable)
        {
            StartMonitor();
        }
    }

    private void StartMonitor()
    {
        _monitorCts?.Cancel();
        _monitorCts = new CancellationTokenSource();
        DesktopLogger.Info("monitor loop starting");
        _monitorLoopTask = RunMonitorLoopAsync(_monitorCts.Token);
    }

    private async Task RunMonitorLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested && !_disposed)
        {
            // Task.Yield (not just _delay): guarantees this loop always
            // suspends and returns control to whoever called StartMonitor,
            // even when _delay resolves synchronously (test doubles) —
            // without it, every await in this method completes inline and
            // the loop runs forever on the calling thread before StartMonitor
            // (and therefore StartAsync) ever returns, since nothing else can
            // reach _monitorCts.Cancel() to end it.
            //
            // Deliberately NOT Task.Run: that would detach the loop from the
            // caller's SynchronizationContext (the UI thread's dispatcher in
            // production), so RunMonitorIterationAsync's SetState/StateChanged
            // would fire on a thread-pool thread — MainWindow's status-dot
            // update touches a WinUI object and requires the UI thread.
            // Task.Yield's continuation is posted back through
            // SynchronizationContext.Current when one is installed, so the
            // loop keeps running on the UI thread across iterations.
            await Task.Yield();
            if (cancellationToken.IsCancellationRequested)
            {
                return;
            }

            try
            {
                await _delay(MonitorInterval, cancellationToken).ConfigureAwait(true);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // Real Task.Delay throws on cancellation rather than just
                // returning — ShutdownAsync awaits this method's Task, so an
                // uncaught cancellation here would fault it and rethrow into
                // whatever called ShutdownAsync (an async void event handler
                // in production), silently aborting shutdown before it ever
                // reached the code that actually stops the owned process.
                // Found via a real physical repro: the window never closed.
                return;
            }

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
        if (_disposed)
        {
            // Cancellation/disposal always wins over restart — never act on
            // a stray callback that raced Desktop shutdown.
            return;
        }

        var health = await _coreClient.GetHealthAsync().ConfigureAwait(true);
        DesktopLogger.Info($"health check (monitor): {(health.IsSuccess ? "pass" : $"fail ({health.Error!.Kind})")}");
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
        // kill or replace a process Desktop didn't start). Gated on the
        // explicit Ownership state, not an inferred null-check: an External
        // Core that stops responding is never adopted as Owned — REVA never
        // launched it, so REVA never relaunches it (Task 3, Slice 8A).
        var ownedProcessExited = Ownership == CoreOwnership.Owned && _ownedProcess is { HasExited: true };
        if (ownedProcessExited)
        {
            DesktopLogger.Info($"process exit observed (pid={_ownedProcess!.Pid?.ToString() ?? "unknown"}, exitCode={_ownedProcess.ExitCode?.ToString() ?? "unknown"})");
        }

        if (ownedProcessExited && _relaunchAttempts < MaxRelaunchAttempts)
        {
            var opId = NewOperationId("recover");
            DesktopLogger.Info($"recovery begin (attempt {_relaunchAttempts + 1}/{MaxRelaunchAttempts})", opId);
            _relaunchAttempts++;
            var resolution = _executableLocator.Resolve();
            if (resolution.IsAvailable)
            {
                _ownedProcess!.Dispose();
                try
                {
                    _ownedProcess = _processLauncher.Launch(
                        resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
                    DesktopLogger.Info($"recovery end (relaunched, pid={_ownedProcess.Pid?.ToString() ?? "unknown"})", opId);
                }
                catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // A relaunch failure must not fault this method — it runs
                    // inside the background monitor loop, and an unobserved
                    // exception there would silently end all future reconnect
                    // attempts with no user-visible indication.
                    DesktopLogger.Warn($"Failed to relaunch REVA Core: {ex.Message}", opId);
                    _ownedProcess = null;
                    DesktopLogger.Info("recovery end (relaunch failed)", opId);
                }
            }
            else
            {
                DesktopLogger.Info("recovery end (executable not resolved)", opId);
            }
        }
    }

    private async Task<bool> WaitForHealthAsync(CancellationToken cancellationToken)
    {
        // Elapsed time adds the poll interval logically (never a real
        // Task.Delay wait when a test injects a no-op _delay, which would
        // defeat the seam's whole purpose — see ctor doc comment) PLUS the
        // call's own measured duration, so a slow-but-not-instantly-failing
        // GetHealthAsync still counts toward the bound instead of being
        // free, which could otherwise stretch this well past HealthTimeout.
        var elapsed = TimeSpan.Zero;
        while (elapsed < HealthTimeout)
        {
            var callStart = Stopwatch.GetTimestamp();
            var result = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
            elapsed += Stopwatch.GetElapsedTime(callStart);
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
        // See WaitForHealthAsync: elapsed adds the poll interval logically
        // plus the call's own measured duration.
        var elapsed = TimeSpan.Zero;
        while (elapsed < TokenTimeout)
        {
            var callStart = Stopwatch.GetTimestamp();
            var result = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(true);
            elapsed += Stopwatch.GetElapsedTime(callStart);
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
