using Pv;

namespace Reva.Desktop.Services;

public sealed class PvRecorderWakeSpeechCapture : IWakeSpeechCapture
{
    private const int SampleRate = 16000;
    private const int FrameLength = 512;

    public Task<byte[]> CaptureAsync(CancellationToken cancellationToken = default) =>
        Task.Run(() => CaptureCore(cancellationToken), cancellationToken);

    private static byte[] CaptureCore(CancellationToken cancellationToken)
    {
        using var recorder = PvRecorder.Create(frameLength: FrameLength);
        var endpointer = new Endpointer(SampleRate);
        var samples = new List<short>(SampleRate * 8);
        var started = false;

        try
        {
            recorder.Start();
            started = true;
            while (!cancellationToken.IsCancellationRequested)
            {
                var frame = recorder.Read();
                samples.AddRange(frame);
                if (endpointer.ShouldStop(frame))
                {
                    break;
                }
            }
        }
        finally
        {
            if (started && recorder.IsRecording)
            {
                recorder.Stop();
            }
        }

        cancellationToken.ThrowIfCancellationRequested();
        return WavAudio.FromPcm16Mono(samples, SampleRate);
    }
}
