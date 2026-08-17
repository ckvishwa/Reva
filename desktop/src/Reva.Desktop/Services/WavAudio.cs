using System.Buffers.Binary;
using System.Text;

namespace Reva.Desktop.Services;

public static class WavAudio
{
    public static bool TryGetDurationMs(byte[]? wav, out int durationMs)
    {
        durationMs = 0;
        if (wav is null || wav.Length < 12 || !Tag(wav, 0, "RIFF") || !Tag(wav, 8, "WAVE"))
        {
            return false;
        }

        var offset = 12;
        var sampleRate = 0;
        var blockAlign = 0;
        long dataBytes = -1;

        while (offset + 8 <= wav.Length)
        {
            var chunkId = Encoding.ASCII.GetString(wav, offset, 4);
            var chunkSize = BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(offset + 4, 4));
            if (chunkSize > int.MaxValue)
            {
                return false;
            }

            long chunkStart = offset + 8;
            long chunkEnd = chunkStart + chunkSize;
            if (chunkEnd > wav.Length)
            {
                return false;
            }

            if (chunkId == "fmt " && chunkSize >= 16)
            {
                sampleRate = (int)BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan((int)chunkStart + 4, 4));
                blockAlign = BinaryPrimitives.ReadUInt16LittleEndian(wav.AsSpan((int)chunkStart + 12, 2));
            }
            else if (chunkId == "data")
            {
                dataBytes = chunkSize;
            }

            offset = (int)(chunkEnd + (chunkSize % 2));
        }

        if (sampleRate <= 0 || blockAlign <= 0 || dataBytes < 0)
        {
            return false;
        }

        var frames = dataBytes / (double)blockAlign;
        durationMs = (int)Math.Round(frames / sampleRate * 1000);
        return true;
    }

    private static bool Tag(byte[] data, int offset, string tag) =>
        Encoding.ASCII.GetString(data, offset, 4) == tag;
}
