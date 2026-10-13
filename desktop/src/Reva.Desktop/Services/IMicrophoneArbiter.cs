namespace Reva.Desktop.Services;

public enum MicrophoneOwner
{
    WakeWord,
    HoldToTalk,
}

public interface IMicrophoneArbiter
{
    MicrophoneOwner? CurrentOwner { get; }

    Task<IMicrophoneLease?> TryAcquireAsync(
        MicrophoneOwner owner,
        CancellationToken cancellationToken = default);
}

public interface IMicrophoneLease : IAsyncDisposable
{
    MicrophoneOwner Owner { get; }

    bool IsActive { get; }
}
