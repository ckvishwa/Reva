namespace Reva.Desktop.Services;

public sealed class NullWakeWordDetector : IWakeWordDetector
{
    public bool IsRunning { get; private set; }

    public event EventHandler<WakeWordDetection>? Detected
    {
        add { }
        remove { }
    }

    public event EventHandler<WakeWordFailure>? Faulted
    {
        add { }
        remove { }
    }

    public Task StartAsync(
        WakeWordConfiguration configuration,
        IMicrophoneLease lease,
        CancellationToken cancellationToken = default)
    {
        IsRunning = true;
        return Task.CompletedTask;
    }

    public Task StopAsync(CancellationToken cancellationToken = default)
    {
        IsRunning = false;
        return Task.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        IsRunning = false;
        return ValueTask.CompletedTask;
    }
}
