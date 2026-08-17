namespace Reva.Desktop.Services;

public interface IWakeSpeechCapture
{
    Task<byte[]> CaptureAsync(CancellationToken cancellationToken = default);
}
