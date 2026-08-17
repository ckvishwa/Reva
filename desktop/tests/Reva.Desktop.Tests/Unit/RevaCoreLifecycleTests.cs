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
        public void Dispose() { }
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
}
