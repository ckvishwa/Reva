using Reva.Desktop.Contracts;
using Reva.Desktop.Services;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class ShellViewModelTests
{
    /// <summary>Records whether continuations were marshaled through this
    /// context (Post/Send) rather than resuming directly on whatever
    /// thread-pool thread completed the awaited task. A ViewModel method
    /// that mutates UI-bound state after an `await` must resume via the
    /// calling SynchronizationContext — that's what makes it safe to touch
    /// bound properties afterward on a real UI thread. `ConfigureAwait(false)`
    /// bypasses this.</summary>
    private sealed class RecordingSynchronizationContext : SynchronizationContext
    {
        public int PostCount { get; private set; }

        public override void Post(SendOrPostCallback d, object? state)
        {
            PostCount++;
            d(state);
        }

        public override void Send(SendOrPostCallback d, object? state)
        {
            PostCount++;
            d(state);
        }
    }

    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly CoreResult<HealthStatus> _result;

        public FakeCoreClient(CoreResult<HealthStatus> result) => _result = result;

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
            // Task.Run (not Task.Yield/Task.Delay): completes on a raw
            // ThreadPool thread with NO SynchronizationContext involvement
            // of its own. Task.Yield's awaiter would itself consult
            // SynchronizationContext.Current to schedule its continuation,
            // which would tick the test's recording context independently
            // of whether ShellViewModel's own await captures it — that
            // would make the test pass regardless of the bug. Task.Run
            // sidesteps that confound entirely.
            Task.Run(() => _result);

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("ShellViewModel never calls GetVersionAsync.");

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("ShellViewModel never calls SendMessageAsync.");
    }

    private static HealthStatus HealthyStatus() =>
        new(SchemaVersion: 1, Status: "healthy", DbSchemaVersion: 1, StartedAt: DateTimeOffset.UtcNow);

    [Fact]
    public void InitialState_IsCheckingAndNotConnected()
    {
        var viewModel = new ShellViewModel(new FakeCoreClient(CoreResult<HealthStatus>.Success(HealthyStatus())));

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("Checking REVA Core...", viewModel.CoreStatusText);
    }

    [Fact]
    public async Task RefreshCoreStatusAsync_Success_SetsConnected()
    {
        var viewModel = new ShellViewModel(new FakeCoreClient(CoreResult<HealthStatus>.Success(HealthyStatus())));

        await viewModel.RefreshCoreStatusAsync();

        Assert.True(viewModel.IsCoreConnected);
        Assert.Equal("Core Connected", viewModel.CoreStatusText);
    }

    [Fact]
    public async Task RefreshCoreStatusAsync_Failure_SetsUnavailable()
    {
        var client = new FakeCoreClient(
            CoreResult<HealthStatus>.Failure(CoreErrorKind.CoreUnavailable, "REVA Core is not reachable."));
        var viewModel = new ShellViewModel(client);

        await viewModel.RefreshCoreStatusAsync();

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("Core Unavailable", viewModel.CoreStatusText);
    }

    /// <summary>
    /// Regression test for the real bug found during Slice 3's manual
    /// smoke test: RefreshCoreStatusAsync awaited GetHealthAsync with
    /// ConfigureAwait(false), so its continuation (setting
    /// IsCoreConnected/CoreStatusText) ran on a thread-pool thread instead
    /// of resuming via the UI's SynchronizationContext. No exception, no
    /// crash — the status update just silently never reached a real WinUI
    /// binding, stuck on "Checking REVA Core..." even against a healthy,
    /// reachable Core. This test installs a recording SynchronizationContext
    /// (standing in for WinUI's DispatcherQueueSynchronizationContext) and
    /// fails if the continuation bypasses it.
    /// </summary>
    // Deliberately NOT `async Task`: if the test method itself were async
    // and awaited RefreshCoreStatusAsync() directly, the TEST'S OWN await
    // would also capture and Post through recordingContext for its own
    // continuation — incrementing PostCount regardless of whether
    // ShellViewModel's internal await does. That confound would make the
    // assertion pass even with the bug reintroduced (verified empirically
    // while writing this test). Blocking synchronously via Task.Wait()
    // instead means the only way PostCount can be nonzero is if
    // RefreshCoreStatusAsync's own continuation used the context.
    [Fact]
    public void RefreshCoreStatusAsync_ResumesOnCallingSynchronizationContext()
    {
        var previousContext = SynchronizationContext.Current;
        var recordingContext = new RecordingSynchronizationContext();
        SynchronizationContext.SetSynchronizationContext(recordingContext);
        try
        {
            var viewModel = new ShellViewModel(
                new FakeCoreClient(CoreResult<HealthStatus>.Success(HealthyStatus())));

            var task = viewModel.RefreshCoreStatusAsync();
#pragma warning disable xUnit1031 // blocking wait is the point of this test — see comment above
            var completed = task.Wait(TimeSpan.FromSeconds(5));
#pragma warning restore xUnit1031

            Assert.True(completed, "RefreshCoreStatusAsync did not complete within 5 seconds.");
            Assert.True(
                recordingContext.PostCount > 0,
                "RefreshCoreStatusAsync's continuation must resume via the calling " +
                "SynchronizationContext (e.g. WinUI's dispatcher) so UI-bound property " +
                "updates are safe. A ConfigureAwait(false) anywhere in this call chain " +
                "would make this 0 and silently break the real app's status display.");
            Assert.True(viewModel.IsCoreConnected);
            Assert.Equal("Core Connected", viewModel.CoreStatusText);
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(previousContext);
        }
    }
}
