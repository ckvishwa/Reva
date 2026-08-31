using System.Diagnostics;

namespace Reva.Desktop.Services;

/// <summary>
/// Owns Core process lifecycle only — no memory/policy/agent semantics.
/// StartAsync: probe an existing Core first; attach if healthy; otherwise
/// resolve and launch a local Core, then wait for health and for
/// local_auth_token to appear. Also runs the background reconnect monitor
/// and the duplicate-launch guard (a process-scoped named Mutex).
///
/// Root-cause fix (Slice 8A): a single ambiguous health-probe result
/// (CoreTimeout, or CoreUnavailable while a sibling Desktop instance's
/// freshly-launched Core is still booting) used to be treated as proof
/// Core was gone — both at startup (causing a duplicate process launched
/// against an already-occupied port) and in the steady-state monitor
/// (causing Connected/Unavailable to flap on every isolated slow health
/// poll, respawning the monitor loop each time). Both paths now require
/// <see cref="ConsecutiveFailureThreshold"/> consecutive ambiguous
/// failures before concluding Core is actually gone. A genuine owned-
/// process exit (<see cref="ICoreProcessHandle.HasExited"/>) is real
/// evidence and still acts immediately, bypassing the threshold.
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
    private static readonly TimeSpan ProbeRetryInterval = TimeSpan.FromMilliseconds(300);

    /// <summary>How many consecutive ambiguous (CoreUnavailable/CoreTimeout)
    /// health results are required before Core is classified as actually
    /// gone. A single such result proves nothing — Core may just be slow,
    /// or (during startup racing) still booting.</summary>
    private const int ConsecutiveFailureThreshold = 3;

    /// <summary>Bounded exponential backoff applied before each relaunch of
    /// a genuinely-exited owned process. Once exhausted, automatic
    /// restarting stops and Core is left in the safe (never falsely
    /// "Connected") Unavailable status.</summary>
    private static readonly TimeSpan[] RelaunchBackoffSchedule =
    {
        TimeSpan.FromSeconds(1),
        TimeSpan.FromSeconds(2),
        TimeSpan.FromSeconds(5),
        TimeSpan.FromSeconds(10),
        TimeSpan.FromSeconds(30),
    };

    /// <summary>How long a connection must stay healthy before a prior
    /// restart streak is forgiven. Prevents a Core that crashes, recovers
    /// briefly, then crashes again from getting a full fresh backoff
    /// budget for what is really one ongoing failure.</summary>
    private static readonly TimeSpan StableConnectionInterval = TimeSpan.FromSeconds(30);

    private readonly IRevaCoreClient _coreClient;
    private readonly ILocalTokenProvider _tokenProvider;
    private readonly ICoreExecutableLocator _executableLocator;
    private readonly ICoreProcessLauncher _processLauncher;
    private readonly DesktopConfiguration _configuration;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly TimeProvider _timeProvider;

    private ICoreProcessHandle? _ownedProcess;
    private CancellationTokenSource? _monitorCts;
    private int _consecutiveHealthFailures;
    private DateTimeOffset? _recoveredAt;
    private bool _disposed;

    public RevaCoreLifecycle(
        IRevaCoreClient coreClient,
        ILocalTokenProvider tokenProvider,
        ICoreExecutableLocator executableLocator,
        ICoreProcessLauncher processLauncher,
        DesktopConfiguration configuration,
        Func<TimeSpan, CancellationToken, Task>? delay = null,
        TimeProvider? timeProvider = null)
    {
        _coreClient = coreClient;
        _tokenProvider = tokenProvider;
        _executableLocator = executableLocator;
        _processLauncher = processLauncher;
        _configuration = configuration;
        _delay = delay ?? ((span, token) => Task.Delay(span, token));
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public CoreLifecycleState State { get; private set; } = CoreLifecycleState.Starting;

    public string StatusText { get; private set; } = "Starting Core…";

    /// <summary>Number of relaunch attempts made against the current
    /// failure streak. Exposed for diagnostics and for tests proving
    /// bounded backoff / stable-interval reset — not part of
    /// <see cref="IRevaCoreLifecycle"/>, since callers outside this class
    /// have no legitimate use for it.</summary>
    public int RestartAttemptCount { get; private set; }

    public event EventHandler? StateChanged;

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        SetState(CoreLifecycleState.Starting);

        var probe = await ProbeReachabilityAsync(cancellationToken).ConfigureAwait(true);
        if (probe.IsSuccess)
        {
            await FinishConnectingAsync(cancellationToken).ConfigureAwait(true);
            return;
        }

        if (!probe.IsAmbiguous)
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
            if (!acquired)
            {
                // Could not confirm exclusive ownership of the launch decision
                // within the timeout — fail safe rather than risk launching a
                // second process against an already-occupied port (the whole
                // point of this lock).
                DesktopLogger.Warn("Timed out waiting for the Core start lock; treating Core as unavailable.");
                SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
                return;
            }

            try
            {
                // Re-probe after acquiring the lock: whoever got here first may
                // have already finished launching Core (or still be booting
                // it) while this instance was waiting on the mutex — retried
                // with the same threshold as the initial probe, since "still
                // booting" looks identical to "not started" for one attempt.
                var reprobe = await ProbeReachabilityAsync(cancellationToken).ConfigureAwait(true);
                if (reprobe.IsSuccess)
                {
                    await FinishConnectingAsync(cancellationToken).ConfigureAwait(true);
                    return;
                }

                if (!reprobe.IsAmbiguous)
                {
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

                try
                {
                    _ownedProcess = _processLauncher.Launch(
                        resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
                    DesktopLogger.Info($"Core lifecycle: launched owned Core (pid={_ownedProcess.Pid?.ToString() ?? "unknown"}).");
                }
                catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // Process.Start can fail for reasons outside our control
                    // (AV blocking, path-length limits, permissions) — degrade
                    // to Unavailable rather than crashing the app via the
                    // unhandled exception this would otherwise become inside
                    // App.OnLaunched's async void.
                    DesktopLogger.Warn($"Failed to launch REVA Core: {ex.Message}");
                    SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
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
            return;
        }

        await FinishConnectingAsync(cancellationToken).ConfigureAwait(true);
    }

    private readonly record struct ReachabilityProbeResult(bool IsSuccess, bool IsAmbiguous);

    /// <summary>
    /// Root-cause fix: a single ambiguous health result (CoreUnavailable or
    /// CoreTimeout) proves nothing — Core may be merely slow, or (during a
    /// startup race between two Desktop instances) still booting. Retries
    /// up to <see cref="ConsecutiveFailureThreshold"/> times before
    /// concluding Core is actually not reachable. A non-ambiguous failure
    /// (something else is listening on the port, or a real server error)
    /// returns immediately — retrying that would not change the classification.
    /// </summary>
    private async Task<ReachabilityProbeResult> ProbeReachabilityAsync(CancellationToken cancellationToken)
    {
        for (var attempt = 1; attempt <= ConsecutiveFailureThreshold; attempt++)
        {
            var result = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(true);
            if (result.IsSuccess)
            {
                return new ReachabilityProbeResult(IsSuccess: true, IsAmbiguous: false);
            }

            var ambiguous = result.Error!.Kind is CoreErrorKind.CoreUnavailable or CoreErrorKind.CoreTimeout;
            if (!ambiguous)
            {
                return new ReachabilityProbeResult(IsSuccess: false, IsAmbiguous: false);
            }

            if (attempt < ConsecutiveFailureThreshold)
            {
                await _delay(ProbeRetryInterval, cancellationToken).ConfigureAwait(true);
            }
        }

        return new ReachabilityProbeResult(IsSuccess: false, IsAmbiguous: true);
    }

    public void StopMonitoring()
    {
        var cts = _monitorCts;
        _monitorCts = null;
        if (cts is not null)
        {
            cts.Cancel();
            cts.Dispose();
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        StopMonitoring();

        // Only ever stop a process this instance itself launched — never an
        // externally-started Core it merely attached to (rule: Desktop may
        // stop/restart only an owned Core).
        if (_ownedProcess is not null)
        {
            DesktopLogger.Info($"Core lifecycle: stopping owned Core (pid={_ownedProcess.Pid?.ToString() ?? "unknown"}) on shutdown.");
            _ownedProcess.Stop();
            _ownedProcess.Dispose();
            _ownedProcess = null;
        }
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
        if (_disposed)
        {
            return;
        }

        StopMonitoring();
        _monitorCts = new CancellationTokenSource();
        _ = RunMonitorLoopAsync(_monitorCts.Token);
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
        if (_disposed)
        {
            // Cancellation/disposal always wins over restart — never act on
            // a stray callback that raced Desktop shutdown.
            return;
        }

        var health = await _coreClient.GetHealthAsync().ConfigureAwait(true);
        if (health.IsSuccess)
        {
            _consecutiveHealthFailures = 0;
            MaybeForgiveRestartStreak();
            if (State != CoreLifecycleState.Connected)
            {
                await FinishConnectingAsync(CancellationToken.None).ConfigureAwait(true);
            }
            return;
        }

        // Real evidence the process is gone, independent of the health-probe
        // threshold below: HasExited is not a guess.
        var ownedProcessExited = _ownedProcess is { HasExited: true };
        if (!ownedProcessExited)
        {
            _consecutiveHealthFailures++;
            if (_consecutiveHealthFailures < ConsecutiveFailureThreshold)
            {
                // Root-cause fix: one (or two) isolated slow/failed health
                // polls do not prove Core is dead — a process we know
                // nothing changed about keeps showing its last-known state
                // instead of flapping to Unavailable and back.
                DesktopLogger.Info(
                    $"Core lifecycle: health check failed ({health.Error!.Kind}), " +
                    $"{_consecutiveHealthFailures}/{ConsecutiveFailureThreshold} consecutive — not yet classifying as dead.");
                return;
            }
        }

        SetState(CoreLifecycleState.Unavailable, "Core Unavailable");
        _recoveredAt = null;

        // Only relaunch a process this instance owns and watched exit —
        // never touch a Core this instance merely attached to (rule: never
        // kill or replace a process Desktop didn't start).
        if (ownedProcessExited && RestartAttemptCount < RelaunchBackoffSchedule.Length)
        {
            var backoff = RelaunchBackoffSchedule[RestartAttemptCount];
            RestartAttemptCount++;
            DesktopLogger.Info(
                $"Core lifecycle: owned Core exited (exit code={_ownedProcess!.ExitCode?.ToString() ?? "unknown"}), " +
                $"restart attempt {RestartAttemptCount}/{RelaunchBackoffSchedule.Length}, backoff={backoff}.");

            await _delay(backoff, CancellationToken.None).ConfigureAwait(true);
            if (_disposed)
            {
                return;
            }

            var resolution = _executableLocator.Resolve();
            if (resolution.IsAvailable)
            {
                _ownedProcess.Dispose();
                try
                {
                    _ownedProcess = _processLauncher.Launch(
                        resolution, _configuration.CoreDataDirectory, _configuration.CoreBaseUrl.Port);
                    DesktopLogger.Info($"Core lifecycle: relaunched owned Core (pid={_ownedProcess.Pid?.ToString() ?? "unknown"}).");
                }
                catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // A relaunch failure must not fault this method — it runs
                    // inside the background monitor loop, and an unobserved
                    // exception there would silently end all future reconnect
                    // attempts with no user-visible indication.
                    DesktopLogger.Warn($"Failed to relaunch REVA Core: {ex.Message}");
                    _ownedProcess = null;
                }
            }
        }
        else if (ownedProcessExited)
        {
            DesktopLogger.Warn(
                $"Core lifecycle: owned Core exited but restart budget ({RelaunchBackoffSchedule.Length}) is exhausted — " +
                "leaving Core Unavailable rather than restarting indefinitely.");
        }
    }

    /// <summary>Resets the restart-attempt budget only once the connection
    /// has been healthy for a full <see cref="StableConnectionInterval"/> —
    /// a Core that crashes, recovers briefly, then crashes again is one
    /// ongoing failure, not a fresh problem entitled to a fresh backoff budget.</summary>
    private void MaybeForgiveRestartStreak()
    {
        if (RestartAttemptCount == 0)
        {
            return;
        }

        var now = _timeProvider.GetUtcNow();
        if (_recoveredAt is null)
        {
            _recoveredAt = now;
            return;
        }

        if (now - _recoveredAt.Value >= StableConnectionInterval)
        {
            RestartAttemptCount = 0;
            _recoveredAt = null;
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
