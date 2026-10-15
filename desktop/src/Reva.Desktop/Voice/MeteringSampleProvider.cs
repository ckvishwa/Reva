using NAudio.Wave;

namespace Reva.Desktop.Voice;

/// <summary>
/// Passes audio through unchanged and reports its loudness in ~60 Hz windows as the audio device
/// pulls it. The mouth is driven from this, so it follows what is actually being played and stops
/// the moment playback stops (the device stops pulling): FR-AV-003 and FR-AV-004.
/// </summary>
public sealed class MeteringSampleProvider : ISampleProvider
{
    public const int WindowsPerSecond = 60;

    private readonly ISampleProvider _source;
    private readonly int _channels;
    private readonly int _windowFrames;
    private readonly Action<int, double> _onLevel;
    private double _sumSquares;
    private int _framesInWindow;
    private long _framesTotal;

    public MeteringSampleProvider(ISampleProvider source, Action<int, double> onLevel)
    {
        _source = source;
        _channels = Math.Max(1, source.WaveFormat.Channels);
        _windowFrames = Math.Max(1, source.WaveFormat.SampleRate / WindowsPerSecond);
        _onLevel = onLevel;
    }

    public WaveFormat WaveFormat => _source.WaveFormat;

    public int Read(float[] buffer, int offset, int count)
    {
        var read = _source.Read(buffer, offset, count);
        var frames = read / _channels;
        for (var i = 0; i < frames; i++)
        {
            var sum = 0f;
            for (var c = 0; c < _channels; c++)
            {
                sum += buffer[offset + i * _channels + c];
            }

            var mono = sum / _channels;
            _sumSquares += mono * mono;
            _framesInWindow++;
            _framesTotal++;
            if (_framesInWindow == _windowFrames)
            {
                var rms = Math.Sqrt(_sumSquares / _windowFrames);
                var positionMs = (int)(_framesTotal * 1000L / WaveFormat.SampleRate);
                _sumSquares = 0;
                _framesInWindow = 0;
                _onLevel(positionMs, rms);
            }
        }

        return read;
    }
}
