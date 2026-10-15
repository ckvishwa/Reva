using NAudio.Wave;
using NAudio.Wave.SampleProviders;

namespace Reva.Desktop.Voice;

/// <summary>
/// Turns whatever the capture device delivers (usually 48 kHz stereo float) into the 16 kHz mono
/// 16-bit little-endian PCM that Core's endpointing and speech-to-text expect. Stateful across
/// calls (the resampler keeps its filter history), so one instance serves one capture run.
/// </summary>
public sealed class PcmConverter
{
    public const int TargetSampleRate = 16_000;

    private readonly BufferedWaveProvider _buffer;
    private readonly ISampleProvider _chain;
    private readonly float[] _scratch = new float[4096];

    public PcmConverter(WaveFormat input)
    {
        _buffer = new BufferedWaveProvider(input)
        {
            ReadFully = false,
            DiscardOnBufferOverflow = true,
            BufferDuration = TimeSpan.FromSeconds(2),
        };
        ISampleProvider samples = _buffer.ToSampleProvider();
        if (samples.WaveFormat.Channels > 1)
        {
            samples = new MonoMixer(samples);
        }

        _chain = samples.WaveFormat.SampleRate == TargetSampleRate
            ? samples
            : new WdlResamplingSampleProvider(samples, TargetSampleRate);
    }

    public byte[] Convert(byte[] data, int count)
    {
        _buffer.AddSamples(data, 0, count);
        using var output = new MemoryStream();
        int read;
        while ((read = _chain.Read(_scratch, 0, _scratch.Length)) > 0)
        {
            for (var i = 0; i < read; i++)
            {
                var clipped = Math.Clamp(_scratch[i], -1f, 1f);
                var sample = (short)Math.Round(clipped * short.MaxValue);
                output.WriteByte((byte)(sample & 0xFF));
                output.WriteByte((byte)((sample >> 8) & 0xFF));
            }
        }

        return output.ToArray();
    }

    /// <summary>Average of all channels.</summary>
    private sealed class MonoMixer : ISampleProvider
    {
        private readonly ISampleProvider _source;
        private readonly int _channels;
        private float[] _frame = Array.Empty<float>();

        public MonoMixer(ISampleProvider source)
        {
            _source = source;
            _channels = source.WaveFormat.Channels;
            WaveFormat = WaveFormat.CreateIeeeFloatWaveFormat(source.WaveFormat.SampleRate, 1);
        }

        public WaveFormat WaveFormat { get; }

        public int Read(float[] buffer, int offset, int count)
        {
            var needed = count * _channels;
            if (_frame.Length < needed)
            {
                _frame = new float[needed];
            }

            var read = _source.Read(_frame, 0, needed);
            var frames = read / _channels;
            for (var i = 0; i < frames; i++)
            {
                var sum = 0f;
                for (var c = 0; c < _channels; c++)
                {
                    sum += _frame[i * _channels + c];
                }

                buffer[offset + i] = sum / _channels;
            }

            return frames;
        }
    }
}
