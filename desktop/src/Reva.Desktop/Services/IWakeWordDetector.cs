namespace Reva.Desktop.Services;

public sealed record WakeWordDetection(WakePhrase Phrase, DateTimeOffset DetectedAtUtc);

public interface IWakeWordDetector : IAsyncDisposable
{
    bool IsRunning { get; }

    event EventHandler<WakeWordDetection>? Detected;

    Task StartAsync(
        WakeWordConfiguration configuration,
        IMicrophoneLease lease,
        CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);
}
