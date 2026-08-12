namespace Reva.Desktop.Services;

public interface IVoiceDevice
{
    bool IsAvailable { get; }

    Task StartRecordingAsync(CancellationToken cancellationToken = default);

    Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default);

    Task PlayAsync(byte[] wavAudio, CancellationToken cancellationToken = default);

    void StopPlayback();

    void CancelRecording();
}
