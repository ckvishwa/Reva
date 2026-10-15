using NAudio.Wave;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Tests.Voice;

public class PcmConverterTests
{
    private static byte[] FloatSine(int rate, int channels, double hz, double seconds, double amplitude = 0.5)
    {
        var frames = (int)(rate * seconds);
        var bytes = new byte[frames * channels * 4];
        for (var i = 0; i < frames; i++)
        {
            var value = (float)(amplitude * Math.Sin(2 * Math.PI * hz * i / rate));
            for (var c = 0; c < channels; c++)
            {
                BitConverter.TryWriteBytes(bytes.AsSpan((i * channels + c) * 4), value);
            }
        }

        return bytes;
    }

    private static short[] Samples(byte[] pcm)
    {
        var samples = new short[pcm.Length / 2];
        Buffer.BlockCopy(pcm, 0, samples, 0, samples.Length * 2);
        return samples;
    }

    private static int ZeroCrossings(short[] samples)
    {
        var count = 0;
        for (var i = 1; i < samples.Length; i++)
        {
            if (samples[i - 1] < 0 && samples[i] >= 0)
            {
                count++;
            }
        }

        return count;
    }

    private static byte[] ConvertAll(PcmConverter converter, byte[] input, int chunk)
    {
        using var output = new MemoryStream();
        for (var offset = 0; offset < input.Length; offset += chunk)
        {
            var count = Math.Min(chunk, input.Length - offset);
            var part = new byte[count];
            Array.Copy(input, offset, part, 0, count);
            output.Write(converter.Convert(part, count));
        }

        return output.ToArray();
    }

    [Fact]
    public void Stereo_48k_float_becomes_16k_mono_pcm16_with_the_same_pitch()
    {
        var converter = new PcmConverter(WaveFormat.CreateIeeeFloatWaveFormat(48_000, 2));

        var pcm = ConvertAll(converter, FloatSine(48_000, 2, 440, 1.0), chunk: 4800);
        var samples = Samples(pcm);

        Assert.InRange(samples.Length, 15_000, 16_100); // about one second at 16 kHz, a little held back by the filter
        Assert.InRange(ZeroCrossings(samples), 425, 450); // 440 Hz survives
        Assert.InRange(samples.Max(), 14_000, 17_500); // 0.5 full scale, not clipped or flattened
    }

    [Fact]
    public void Chunk_size_does_not_change_the_result_length_materially()
    {
        var input = FloatSine(48_000, 2, 300, 1.0);
        var a = ConvertAll(new PcmConverter(WaveFormat.CreateIeeeFloatWaveFormat(48_000, 2)), input, 960);
        var b = ConvertAll(new PcmConverter(WaveFormat.CreateIeeeFloatWaveFormat(48_000, 2)), input, 9600);

        Assert.InRange(Math.Abs(a.Length - b.Length), 0, 400);
    }

    [Fact]
    public void Pcm16_44k_mono_is_resampled()
    {
        var frames = 44_100;
        var input = new byte[frames * 2];
        for (var i = 0; i < frames; i++)
        {
            var value = (short)(12_000 * Math.Sin(2 * Math.PI * 500 * i / 44_100.0));
            BitConverter.TryWriteBytes(input.AsSpan(i * 2), value);
        }

        var pcm = ConvertAll(new PcmConverter(new WaveFormat(44_100, 16, 1)), input, 4410);
        var samples = Samples(pcm);

        Assert.InRange(samples.Length, 15_000, 16_100);
        Assert.InRange(ZeroCrossings(samples), 480, 520);
    }

    [Fact]
    public void Silence_stays_silent()
    {
        var pcm = ConvertAll(new PcmConverter(WaveFormat.CreateIeeeFloatWaveFormat(48_000, 2)), new byte[48_000 * 2 * 4], 9600);

        Assert.True(Samples(pcm).All(s => s == 0));
    }

    [Fact]
    public void A_six_channel_device_is_averaged_not_rejected()
    {
        var converter = new PcmConverter(WaveFormat.CreateIeeeFloatWaveFormat(48_000, 6));

        var pcm = ConvertAll(converter, FloatSine(48_000, 6, 440, 0.5), chunk: 5760);

        Assert.InRange(Samples(pcm).Max(), 14_000, 17_500);
    }

    [Fact]
    public void Already_16k_float_mono_is_only_converted_to_pcm16()
    {
        var input = FloatSine(16_000, 1, 200, 0.5, amplitude: 1.5); // beyond full scale on purpose

        var pcm = ConvertAll(new PcmConverter(WaveFormat.CreateIeeeFloatWaveFormat(16_000, 1)), input, 3200);

        var samples = Samples(pcm);
        Assert.Equal(8_000, samples.Length);
        Assert.Equal(short.MaxValue, samples.Max()); // clamped, not wrapped around
        Assert.True(samples.Min() >= -short.MaxValue);
    }
}
