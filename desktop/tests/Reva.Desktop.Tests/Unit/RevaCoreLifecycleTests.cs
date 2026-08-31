using System.Diagnostics;
using Reva.Desktop.Contracts;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class RevaCoreLifecycleTests
{
    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private Queue<CoreResult<HealthStatus>> _healthResults;

        public FakeCoreClient(params CoreResult<HealthStatus>[] healthResults) =>
            _healthResults = new Queue<CoreResult<HealthStatus>>(healthResults);

        public int HealthCallCount { get; private set; }

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default)
        {
            HealthCallCount++;
            var result = _healthResults.Count > 1 ? _healthResults.Dequeue() : _healthResults.Peek();
            return Task.FromResult(result);
        }

        public void QueueHealthFailureThenSuccess()
        {
            _healthResults.Clear();
            _healthResults.Enqueue(CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"));
            _healthResults.Enqueue(CoreResult<HealthStatus>.Success(Healthy()));
        }

        public void QueuePersistentFailure()
        {
            _healthResults.Clear();
            _healthResults.Enqueue(CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"));
        }

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query, int limit, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
            byte[] wavAudio, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(
            string text, string language, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }

    private sealed class FakeTokenProvider : ILocalTokenProvider
    {
        private readonly Queue<TokenLoadResult> _results;

        public FakeTokenProvider(params TokenLoadResult[] results) => _results = new Queue<TokenLoadResult>(results);

        public Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default)
        {
            var result = _results.Count > 1 ? _results.Dequeue() : _results.Peek();
            return Task.FromResult(result);
        }
    }

    private sealed class FakeExecutableLocator : ICoreExecutableLocator
    {
        private readonly CoreExecutableResolution _result;

        public FakeExecutableLocator(CoreExecutableResolution result) => _result = result;

        public int ResolveCallCount { get; private set; }

        public CoreExecutableResolution Resolve()
        {
            ResolveCallCount++;
            return _result;
        }
    }

    private sealed class FakeProcessHandle : ICoreProcessHandle
    {
        public bool HasExited { get; set; }
        public int? ExitCode { get; set; }
        public int? Pid { get; set; } = 1234;
        public int DisposeCallCount { get; private set; }
        public int StopCallCount { get; private set; }
        public void Dispose() => DisposeCallCount++;
        public void Stop() => StopCallCount++;
    }

    private sealed class FakeProcessLauncher : ICoreProcessLauncher
    {
        public int LaunchCallCount { get; private set; }
        public FakeProcessHandle LastHandle { get; } = new();

        public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
        {
            LaunchCallCount++;
            return LastHandle;
        }
    }

    private static DesktopConfiguration Configuration() =>
        new(new Uri("http://127.0.0.1:18756/"), Path.Combine(Path.GetTempPath(), "reva-lifecycle-test"), TimeSpan.FromSeconds(5), DesktopConfiguration.DefaultSttRequestTimeout);

    private static HealthStatus Healthy() => new(1, "healthy", 1, DateTimeOffset.UtcNow);

    private static CoreExecutableResolution AvailableResolution() =>
        CoreExecutableResolution.Available("python.exe", "-m reva_core --serve", Path.GetTempPath());

    [Fact]
    public async Task StartAsync_AttachesWithoutLaunching_WhenCoreAlreadyHealthy()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        using var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration());

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);
        Assert.Equal(0, launcher.LaunchCallCount);
    }

    [Fact]
    public async Task StartAsync_LaunchesCore_WhenNoneReachable_ThenReachesConnected()
    {
        // 3 results, not 2: the mutex-guarded launch path in StartAsync
        // re-probes health once more right after acquiring the start lock
        // (before deciding to launch), so the call sequence is initial
        // probe -> mutex reprobe -> WaitForHealthAsync poll(s).
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        using var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);
        Assert.Equal(1, launcher.LaunchCallCount);
    }

    [Fact]
    public async Task StartAsync_BecomesUnavailable_WhenExecutableCannotBeResolved()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"));
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Unavailable()),
            new FakeExecutableLocator(CoreExecutableResolution.Unavailable("no repo found")),
            new FakeProcessLauncher(), Configuration(), delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Unavailable, lifecycle.State);
    }

    [Fact]
    public async Task StartAsync_BecomesUnavailable_WithoutLaunching_WhenPortHeldByNonReva()
    {
        // CoreInvalidResponse is what RevaCoreClient normalizes a 200
        // response with unparseable JSON to (see RevaCoreClient.InterpretResponseAsync)
        // — a responding-but-not-REVA listener on the configured port.
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreInvalidResponse, "unexpected response"));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Unavailable()),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Unavailable, lifecycle.State);
        Assert.Equal(0, launcher.LaunchCallCount);
    }

    [Fact]
    public async Task StartAsync_BecomesAuthorizationUnavailable_WhenHealthyButTokenNeverAppears()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Unavailable()),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.AuthorizationUnavailable, lifecycle.State);
    }

    [Fact]
    public async Task StartAsync_RaisesStateChanged_OnEveryTransition()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        using var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration());
        var raisedCount = 0;
        lifecycle.StateChanged += (_, _) => raisedCount++;

        await lifecycle.StartAsync();

        Assert.True(raisedCount > 0);
    }

    // Task 3 (Slice 8A): ownership is now an explicit, tested state — not an
    // inferred boolean scattered across call sites — so every stop/kill path
    // can gate on it directly.
    [Fact]
    public async Task StartAsync_WhenAttachingToAlreadyHealthyCore_SetsOwnershipToExternal()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        using var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration());

        await lifecycle.StartAsync();

        Assert.Equal(CoreOwnership.External, lifecycle.Ownership);
    }

    [Fact]
    public async Task StartAsync_WhenLaunchingCore_SetsOwnershipToOwned()
    {
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        using var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();

        Assert.Equal(CoreOwnership.Owned, lifecycle.Ownership);
    }

    [Fact]
    public async Task Dispose_WhenOwned_DisposesTheOwnedProcessHandle()
    {
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);
        await lifecycle.StartAsync();

        lifecycle.Dispose();

        Assert.Equal(1, launcher.LastHandle.DisposeCallCount);
    }

    [Fact]
    public async Task Dispose_WhenExternal_NeverTouchesTheAttachedProcess()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration());
        await lifecycle.StartAsync();

        lifecycle.Dispose();

        // Nothing was ever launched (attach path), so nothing to dispose —
        // asserting the fake's handle was never touched proves the gate,
        // not just that the launcher was never called.
        Assert.Equal(0, launcher.LastHandle.DisposeCallCount);
    }

    [Fact]
    public async Task Monitor_WhenExternalCoreDiesRepeatedly_NeverAdoptsItOrAttemptsRelaunch()
    {
        // Explicit decision (Task 3): an External Core that stops responding
        // is not silently adopted as Owned. REVA never launched it, so REVA
        // never relaunches it — the lifecycle simply reports Unavailable and
        // waits, exactly as if a human needs to restart it themselves.
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration());
        await lifecycle.StartAsync();
        Assert.Equal(CoreOwnership.External, lifecycle.Ownership);
        lifecycle.StopMonitoring();

        client.QueuePersistentFailure();
        await lifecycle.RunMonitorIterationAsync();
        await lifecycle.RunMonitorIterationAsync();
        await lifecycle.RunMonitorIterationAsync();

        Assert.Equal(0, launcher.LaunchCallCount);
        Assert.Equal(CoreOwnership.External, lifecycle.Ownership);
    }

    [Fact]
    public async Task StartAsync_SecondConcurrentLifecycle_DoesNotLaunchASecondProcess()
    {
        // Simulates two Desktop instances starting at once: both see
        // CoreUnavailable on their first probe. The first to acquire the
        // start-lock launches; the second must re-probe after releasing
        // the lock and attach to what the first one started, never launch
        // its own second process.
        //
        // Health is backed by shared state (not a fixed per-client result
        // queue): which instance wins the real OS-level named Mutex is not
        // deterministic, so whichever one is the "loser" must observe the
        // "winner" already launched when it re-probes — a fixed queue on
        // an independent per-client fake can't express that.
        var sharedState = new SharedCoreState();
        var sharedLaunchCount = 0;
        var launcher1 = new CountingLauncher(() => { Interlocked.Increment(ref sharedLaunchCount); sharedState.MarkLaunched(); });
        var launcher2 = new CountingLauncher(() => { Interlocked.Increment(ref sharedLaunchCount); sharedState.MarkLaunched(); });
        using var lifecycle1 = new RevaCoreLifecycle(
            new SharedHealthCoreClient(sharedState), new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher1, Configuration(),
            delay: (_, _) => Task.CompletedTask);
        using var lifecycle2 = new RevaCoreLifecycle(
            new SharedHealthCoreClient(sharedState), new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher2, Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await Task.WhenAll(lifecycle1.StartAsync(), lifecycle2.StartAsync());

        Assert.Equal(1, sharedLaunchCount);
        Assert.Equal(CoreLifecycleState.Connected, lifecycle1.State);
        Assert.Equal(CoreLifecycleState.Connected, lifecycle2.State);
    }

    private sealed class SharedCoreState
    {
        private int _launched;
        public bool IsLaunched => Volatile.Read(ref _launched) != 0;
        public void MarkLaunched() => Interlocked.Exchange(ref _launched, 1);
    }

    private sealed class SharedHealthCoreClient : IRevaCoreClient
    {
        private readonly SharedCoreState _state;
        public SharedHealthCoreClient(SharedCoreState state) => _state = state;

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(_state.IsLaunched
                ? CoreResult<HealthStatus>.Success(Healthy())
                : CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"));

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query, int limit, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
            byte[] wavAudio, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(
            string text, string language, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }

    private sealed class CountingLauncher : ICoreProcessLauncher
    {
        private readonly Action _onLaunch;
        public CountingLauncher(Action onLaunch) => _onLaunch = onLaunch;
        public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
        {
            _onLaunch();
            return new FakeProcessHandle();
        }
    }

    [Fact]
    public async Task Monitor_RelaunchesOwnedProcess_AfterItExitsUnexpectedly()
    {
        // 3 results for the same reason as StartAsync_LaunchesCore_...:
        // initial probe -> mutex reprobe -> WaitForHealthAsync poll.
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var firstHandle = new FakeProcessHandle();
        var launcher = new SequencedLauncher(firstHandle, new FakeProcessHandle());
        using var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);
        await lifecycle.StartAsync();
        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);

        // Stop the auto-started background monitor before driving an
        // iteration manually — with the instant-resolving delay stub it
        // spins in a tight loop and otherwise races this test's own call
        // to RunMonitorIterationAsync over the same mutable fake queue.
        lifecycle.StopMonitoring();

        firstHandle.HasExited = true;
        firstHandle.ExitCode = 1;
        client.QueueHealthFailureThenSuccess();
        await lifecycle.RunMonitorIterationAsync();

        Assert.Equal(2, launcher.LaunchCallCount);
    }

    private sealed class SequencedLauncher : ICoreProcessLauncher
    {
        private readonly Queue<ICoreProcessHandle> _handles;
        public int LaunchCallCount { get; private set; }
        public SequencedLauncher(params ICoreProcessHandle[] handles) => _handles = new Queue<ICoreProcessHandle>(handles);
        public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
        {
            LaunchCallCount++;
            return _handles.Count > 1 ? _handles.Dequeue() : _handles.Peek();
        }
    }

    // Root-cause regression (Slice 8A, Task 1/2): confirmed by a real physical
    // repro (Release build, real REVA Core, real graceful window close via
    // CloseMainWindow, real tasklist check) that the owned Core process
    // survives Desktop exiting. Real cmd.exe process here (not python), same
    // precedent as CoreProcessLauncherTests: this proves RevaCoreLifecycle's
    // process-ownership contract, not Core's own behavior. No mock stands in
    // for the OS process — Dispose()/Kill() cannot be faked into proving this.
    private sealed class PidCapturingLauncher : ICoreProcessLauncher
    {
        private readonly ICoreProcessLauncher _inner = new CoreProcessLauncher();
        public int? LastPid { get; private set; }

        public ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port)
        {
            var handle = _inner.Launch(resolution, dataDirectory, port);
            LastPid = handle.Pid;
            return handle;
        }
    }

    [Fact]
    public async Task Dispose_StopsTheRealOwnedProcess_NotJustTheDotNetHandle()
    {
        var realCoreStandIn = CoreExecutableResolution.Available(
            Environment.ExpandEnvironmentVariables(@"%WINDIR%\System32\cmd.exe"),
            "/c ping -n 60 127.0.0.1 >nul", // long-running: 60s, far past this test's assertion window
            Path.GetTempPath());
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new PidCapturingLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(realCoreStandIn), launcher, Configuration(),
            delay: (_, _) => Task.CompletedTask);

        await lifecycle.StartAsync();
        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);
        var pid = launcher.LastPid;
        Assert.NotNull(pid);
        Assert.False(Process.GetProcessById(pid!.Value).HasExited);

        try
        {
            lifecycle.Dispose();

            var deadline = DateTime.UtcNow.AddSeconds(3);
            var stillRunning = true;
            while (DateTime.UtcNow < deadline)
            {
                try
                {
                    stillRunning = !Process.GetProcessById(pid.Value).HasExited;
                }
                catch (ArgumentException)
                {
                    stillRunning = false; // process no longer exists at all
                }

                if (!stillRunning)
                {
                    break;
                }

                await Task.Delay(50);
            }

            Assert.False(stillRunning, "REVA must stop a Core process it launched when the lifecycle is disposed.");
        }
        finally
        {
            // Cleanup regardless of outcome — never leak a real process out of the test run.
            try
            {
                using var leftover = Process.GetProcessById(pid.Value);
                if (!leftover.HasExited)
                {
                    leftover.Kill(entireProcessTree: true);
                }
            }
            catch (ArgumentException)
            {
                // Already gone — nothing to clean up.
            }
        }
    }

    // Task 6 (Slice 8A): shutdown cancels the monitor loop first, so a
    // recovery decision that would otherwise fire on the next iteration
    // never gets the chance. Real async scheduling: the injected `_delay`
    // seam is a genuinely awaited Task, and shutdown races in during that
    // real await — not a mocked stand-in for the race.
    [Fact]
    public async Task Shutdown_DuringMonitorLoopWait_PreventsAnyFurtherRecoveryAttempt()
    {
        RevaCoreLifecycle? lifecycle = null;
        var shutdownTriggered = false;
        Func<TimeSpan, CancellationToken, Task> delay = (span, token) =>
        {
            if (!shutdownTriggered)
            {
                shutdownTriggered = true;
                // Shutdown races in during the monitor loop's real await —
                // the same yield point a real Task.Delay would occupy.
                lifecycle!.Dispose();
            }

            return Task.CompletedTask;
        };
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var firstHandle = new FakeProcessHandle();
        var launcher = new SequencedLauncher(firstHandle, new FakeProcessHandle());
        lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration(),
            delay: delay);

        await lifecycle.StartAsync();
        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);
        Assert.Equal(1, launcher.LaunchCallCount);

        // The owned process "crashes" right as shutdown is racing in via
        // the delay hook above — if the monitor loop's cancellation check
        // did not win, this is exactly the condition that would trigger a
        // relaunch.
        firstHandle.HasExited = true;
        firstHandle.ExitCode = 1;

        // Real wait, not the synchronization mechanism: gives the monitor
        // loop's already-scheduled continuation a chance to actually run
        // and observe cancellation, so a bug (a relaunch slipping through)
        // has a real opportunity to manifest before we assert its absence.
        await Task.Delay(200);

        Assert.Equal(1, launcher.LaunchCallCount);
        Assert.True(shutdownTriggered);
    }

    // Task 6 (Slice 8A): ShutdownAsync must not return until the monitor
    // loop has actually exited — a fire-and-forget cancel could still let a
    // relaunch decision already past its cancellation check run concurrently
    // with Stop(). Proven with a real TaskCompletionSource gate, not a mock.
    [Fact]
    public async Task ShutdownAsync_WaitsForTheMonitorLoopToActuallyExit()
    {
        var loopGate = new TaskCompletionSource();
        var events = new List<string>();
        Func<TimeSpan, CancellationToken, Task> delay = async (span, token) =>
        {
            events.Add("loop-waiting");
            await loopGate.Task.ConfigureAwait(true);
        };
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration(),
            delay: delay);

        await lifecycle.StartAsync();
        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);

        var deadline = DateTime.UtcNow.AddSeconds(2);
        while (events.Count == 0 && DateTime.UtcNow < deadline)
        {
            await Task.Yield();
        }

        Assert.Contains("loop-waiting", events);

        var shutdownTask = lifecycle.ShutdownAsync();

        var notYetDeadline = DateTime.UtcNow.AddMilliseconds(300);
        while (!shutdownTask.IsCompleted && DateTime.UtcNow < notYetDeadline)
        {
            await Task.Delay(10);
        }

        Assert.False(shutdownTask.IsCompleted, "ShutdownAsync must wait for the monitor loop to actually exit.");

        loopGate.SetResult();
        await shutdownTask;
        events.Add("shutdown-completed");

        Assert.Equal(new[] { "loop-waiting", "shutdown-completed" }, events);
    }

    // Task 6 (Slice 8A) — found via a real physical repro, not a unit test:
    // with the REAL `Task.Delay` (no injected stub), cancelling the monitor
    // loop's CancellationTokenSource makes its pending `_delay(MonitorInterval,
    // cancellationToken)` throw TaskCanceledException. RunMonitorLoopAsync did
    // not catch it, so the loop's Task faulted; ShutdownAsync's `await
    // loopTask` rethrew it into MainWindow_Closed's `async void` continuation,
    // which silently died before ever reaching Close() — the window never
    // actually closed. Real CancellationTokenSource, real Task.Delay: this is
    // the exact "real async scheduling and real cancellation" rule 3 requires.
    [Fact]
    public async Task ShutdownAsync_WithRealDelay_CompletesWithoutThrowing_WhenMonitorLoopIsCancelledMidWait()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration());
            // No delay: parameter — uses the real Task.Delay-backed default.

        await lifecycle.StartAsync();
        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);

        // Give the real monitor loop a moment to actually reach its real
        // 5-second Task.Delay before we cancel it out from under it.
        await Task.Delay(100);

        var exception = await Record.ExceptionAsync(() => lifecycle.ShutdownAsync());

        Assert.Null(exception);
    }
}
