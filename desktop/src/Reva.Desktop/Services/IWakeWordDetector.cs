namespace Reva.Desktop.Services;

public sealed record WakeWordDetection(WakePhrase Phrase, DateTimeOffset DetectedAtUtc);

public sealed record WakeWordFailure(WakeWordFailureKind Kind);

public enum WakeWordFailureKind
{
    DetectorException,
}

public interface IWakeWordDetector : IAsyncDisposable
{
    bool IsRunning { get; }

    event EventHandler<WakeWordDetection>? Detected;

    event EventHandler<WakeWordFailure>? Faulted;

    Task StartAsync(
        WakeWordConfiguration configuration,
        IMicrophoneLease lease,
        CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);
}
