using Reva.Desktop.Services;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class ShellViewModelTests
{
    private sealed class FakeLifecycle : IRevaCoreLifecycle
    {
        public CoreLifecycleState State { get; set; } = CoreLifecycleState.Starting;
        public CoreOwnership Ownership { get; set; } = CoreOwnership.Owned;
        public string StatusText { get; set; } = "Starting Core…";
        public event EventHandler? StateChanged;
        public Task StartAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public void StopMonitoring() { }
        public int ShutdownCallCount { get; private set; }
        public Task ShutdownAsync()
        {
            ShutdownCallCount++;
            return Task.CompletedTask;
        }

        public void Raise(CoreLifecycleState state, string statusText)
        {
            State = state;
            StatusText = statusText;
            StateChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    [Fact]
    public void InitialState_IsStartingAndNotConnected()
    {
        var viewModel = new ShellViewModel(new FakeLifecycle());

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("Starting Core…", viewModel.CoreStatusText);
    }

    [Fact]
    public void ReflectsLifecycle_Connected()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);

        lifecycle.Raise(CoreLifecycleState.Connected, "Core Connected");

        Assert.True(viewModel.IsCoreConnected);
        Assert.Equal("Core Connected", viewModel.CoreStatusText);
    }

    [Fact]
    public void ReflectsLifecycle_Unavailable()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);

        lifecycle.Raise(CoreLifecycleState.Unavailable, "Core Unavailable");

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("Core Unavailable", viewModel.CoreStatusText);
    }

    [Fact]
    public void ReflectsLifecycle_AuthorizationUnavailable()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);

        lifecycle.Raise(CoreLifecycleState.AuthorizationUnavailable, "REVA authorization unavailable");

        Assert.False(viewModel.IsCoreConnected);
        Assert.Equal("REVA authorization unavailable", viewModel.CoreStatusText);
        Assert.Equal(CoreLifecycleState.AuthorizationUnavailable, viewModel.LifecycleState);
    }

    [Fact]
    public void RaisesPropertyChanged_OnLifecycleTransition()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);
        var raised = new List<string?>();
        viewModel.PropertyChanged += (_, e) => raised.Add(e.PropertyName);

        lifecycle.Raise(CoreLifecycleState.Connected, "Core Connected");

        Assert.Contains(nameof(ShellViewModel.IsCoreConnected), raised);
        Assert.Contains(nameof(ShellViewModel.CoreStatusText), raised);
        Assert.Contains(nameof(ShellViewModel.LifecycleState), raised);
    }

    [Fact]
    public async Task ShutdownAsync_ForwardsToLifecycle()
    {
        var lifecycle = new FakeLifecycle();
        var viewModel = new ShellViewModel(lifecycle);

        await viewModel.ShutdownAsync();

        Assert.Equal(1, lifecycle.ShutdownCallCount);
    }
}
