using Pv;

namespace Reva.Desktop.Services;

internal interface IWakeWordEngine : IDisposable
{
    int SampleRate { get; }

    int FrameLength { get; }

    int Process(short[] frame);
}

internal interface IWakeWordEngineFactory
{
    IWakeWordEngine Create(
        string accessKey,
        IReadOnlyList<string> keywordPaths,
        IReadOnlyList<float> sensitivities);
}

internal interface IWakeFrameRecorder : IDisposable
{
    bool IsRecording { get; }

    void Start();

    short[] Read();

    void Stop();
}

internal interface IWakeFrameRecorderFactory
{
    IWakeFrameRecorder Create(int frameLength);
}

internal sealed class PorcupineEngineFactory : IWakeWordEngineFactory
{
    public IWakeWordEngine Create(
        string accessKey,
        IReadOnlyList<string> keywordPaths,
        IReadOnlyList<float> sensitivities) =>
        new PorcupineEngine(Porcupine.FromKeywordPaths(accessKey, keywordPaths, sensitivities: sensitivities));
}

internal sealed class PorcupineEngine : IWakeWordEngine
{
    private readonly Porcupine _inner;

    public PorcupineEngine(Porcupine inner) => _inner = inner;

    public int SampleRate => _inner.SampleRate;

    public int FrameLength => _inner.FrameLength;

    public int Process(short[] frame) => _inner.Process(frame);

    public void Dispose() => _inner.Dispose();
}

internal sealed class PvRecorderFrameRecorderFactory : IWakeFrameRecorderFactory
{
    public IWakeFrameRecorder Create(int frameLength) =>
        new PvRecorderFrameRecorder(PvRecorder.Create(frameLength: frameLength));
}

internal sealed class PvRecorderFrameRecorder : IWakeFrameRecorder
{
    private readonly PvRecorder _inner;

    public PvRecorderFrameRecorder(PvRecorder inner) => _inner = inner;

    public bool IsRecording => _inner.IsRecording;

    public void Start() => _inner.Start();

    public short[] Read() => _inner.Read();

    public void Stop() => _inner.Stop();

    public void Dispose() => _inner.Dispose();
}
