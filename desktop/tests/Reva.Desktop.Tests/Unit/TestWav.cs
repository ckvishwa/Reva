namespace Reva.Desktop.Tests.Unit;

internal static class TestWav
{
    public static byte[] Mono16k(TimeSpan duration)
    {
        const int sampleRate = 16000;
        const short blockAlign = 2; // mono, 16-bit
        var dataBytes = (int)Math.Round(duration.TotalSeconds * sampleRate) * blockAlign;
        return Build(sampleRate, channels: 1, bitsPerSample: 16, dataBytes: dataBytes);
    }

    public static byte[] Build(int sampleRate, short channels, short bitsPerSample, int dataBytes)
    {
        short blockAlign = (short)(channels * bitsPerSample / 8);
        int byteRate = sampleRate * blockAlign;

        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write("RIFF"u8.ToArray());
        writer.Write(36 + dataBytes);
        writer.Write("WAVE"u8.ToArray());
        writer.Write("fmt "u8.ToArray());
        writer.Write(16); // fmt chunk size
        writer.Write((short)1); // PCM
        writer.Write(channels);
        writer.Write(sampleRate);
        writer.Write(byteRate);
        writer.Write(blockAlign);
        writer.Write(bitsPerSample);
        writer.Write("data"u8.ToArray());
        writer.Write(dataBytes);
        writer.Write(new byte[dataBytes]);
        return stream.ToArray();
    }
}
