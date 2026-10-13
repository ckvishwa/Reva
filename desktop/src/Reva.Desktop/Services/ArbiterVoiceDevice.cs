namespace Reva.Desktop.Services;

public sealed class ArbiterVoiceDevice : IVoiceDevice
{
    private readonly IVoiceDevice _inner;
    private readonly IMicrophoneArbiter _arbiter;
    private IMicrophoneLease? _lease;

    public ArbiterVoiceDevice(IVoiceDevice inner, IMicrophoneArbiter arbiter)
    {
        _inner = inner;
        _arbiter = arbiter;
    }

    public bool IsAvailable => _inner.IsAvailable;

    public Task<VoiceDeviceAvailability> VerifyAvailabilityAsync(CancellationToken cancellationToken = default) =>
        _inner.VerifyAvailabilityAsync(cancellationToken);

    public async Task StartRecordingAsync(CancellationToken cancellationToken = default)
    {
        if (_lease is not null)
        {
            return;
        }

        _lease = await _arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk, cancellationToken)
            .ConfigureAwait(false);
        if (_lease is null)
        {
            throw new VoiceCaptureException(VoiceDeviceAvailability.RecordingFailed());
        }

        try
        {
            await _inner.StartRecordingAsync(cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            await ReleaseLeaseAsync().ConfigureAwait(false);
            throw;
        }
    }

    public async Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            return await _inner.StopRecordingAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            await ReleaseLeaseAsync().ConfigureAwait(false);
        }
    }

    public Task PlayAsync(byte[] wavAudio, CancellationToken cancellationToken = default) =>
        _inner.PlayAsync(wavAudio, cancellationToken);

    public void StopPlayback() => _inner.StopPlayback();

    public void CancelRecording()
    {
        _inner.CancelRecording();
        _ = ReleaseLeaseAsync();
    }

    private async Task ReleaseLeaseAsync()
    {
        if (_lease is not null)
        {
            await _lease.DisposeAsync().ConfigureAwait(false);
            _lease = null;
        }
    }
}
