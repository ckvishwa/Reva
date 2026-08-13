namespace Reva.Desktop.Services;

public sealed class UnavailableVoiceDevice : IVoiceDevice
{
    public bool IsAvailable => false;

    public Task<VoiceDeviceAvailability> VerifyAvailabilityAsync(
        CancellationToken cancellationToken = default) =>
        Task.FromResult(VoiceDeviceAvailability.RecordingFailed());

    public Task StartRecordingAsync(CancellationToken cancellationToken = default) =>
        throw new InvalidOperationException("Voice capture is unavailable.");

    public Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default) =>
        throw new InvalidOperationException("Voice capture is unavailable.");

    public Task PlayAsync(byte[] wavAudio, CancellationToken cancellationToken = default) =>
        throw new InvalidOperationException("Voice playback is unavailable.");

    public void StopPlayback()
    {
    }

    public void CancelRecording()
    {
    }
}
