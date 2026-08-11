using Reva.Desktop.Contracts;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class RevaCoreLifecycleTests
{
    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly Queue<CoreResult<HealthStatus>> _healthResults;

        public FakeCoreClient(params CoreResult<HealthStatus>[] healthResults) =>
            _healthResults = new Queue<CoreResult<HealthStatus>>(healthResults);

        public int HealthCallCount { get; private set; }

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default)
        {
            HealthCallCount++;
            var result = _healthResults.Count > 1 ? _healthResults.Dequeue() : _healthResults.Peek();
            return Task.FromResult(result);
        }

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query, int limit, CancellationToken cancellationToken = default) => throw new NotSupportedException();
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
        new(new Uri("http://127.0.0.1:18756/"), Path.Combine(Path.GetTempPath(), "reva-lifecycle-test"), TimeSpan.FromSeconds(5));

    private static HealthStatus Healthy() => new(1, "healthy", 1, DateTimeOffset.UtcNow);

    private static CoreExecutableResolution AvailableResolution() =>
        CoreExecutableResolution.Available("python.exe", "-m reva_core --serve", Path.GetTempPath());

    [Fact]
    public async Task StartAsync_AttachesWithoutLaunching_WhenCoreAlreadyHealthy()
    {
        var client = new FakeCoreClient(CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), launcher, Configuration());

        await lifecycle.StartAsync();

        Assert.Equal(CoreLifecycleState.Connected, lifecycle.State);
        Assert.Equal(0, launcher.LaunchCallCount);
    }

    [Fact]
    public async Task StartAsync_LaunchesCore_WhenNoneReachable_ThenReachesConnected()
    {
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "not reachable"),
            CoreResult<HealthStatus>.Success(Healthy()));
        var launcher = new FakeProcessLauncher();
        var lifecycle = new RevaCoreLifecycle(
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
        var lifecycle = new RevaCoreLifecycle(
            client, new FakeTokenProvider(TokenLoadResult.Available("tok")),
            new FakeExecutableLocator(AvailableResolution()), new FakeProcessLauncher(), Configuration());
        var raisedCount = 0;
        lifecycle.StateChanged += (_, _) => raisedCount++;

        await lifecycle.StartAsync();

        Assert.True(raisedCount > 0);
    }
}
