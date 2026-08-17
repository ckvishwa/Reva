using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WavAudioTests
{
    [Fact]
    public void TryGetDurationMs_OneSecond16kHzMono_Returns1000()
    {
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.FromSeconds(1)), out var durationMs);

        Assert.True(ok);
        Assert.Equal(1000, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_100Milliseconds_Returns100()
    {
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.FromMilliseconds(100)), out var durationMs);

        Assert.True(ok);
        Assert.Equal(100, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_Exactly250Milliseconds_Returns250()
    {
        // Boundary that Task 7's acceptance rule depends on.
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.FromMilliseconds(250)), out var durationMs);

        Assert.True(ok);
        Assert.Equal(250, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_Null_ReturnsFalse()
    {
        var ok = WavAudio.TryGetDurationMs(null, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_EmptyArray_ReturnsFalse()
    {
        var ok = WavAudio.TryGetDurationMs(Array.Empty<byte>(), out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_NotRiffWave_ReturnsFalse()
    {
        var ok = WavAudio.TryGetDurationMs(new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 }, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_ZeroDataBytes_ReturnsZeroDuration()
    {
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.Zero), out var durationMs);

        Assert.True(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_DeclaredDataSizeExceedsBuffer_ReturnsFalse()
    {
        var wav = TestWav.Mono16k(TimeSpan.FromSeconds(1));
        // Corrupt the data chunk size to claim far more bytes than are present.
        BitConverter.GetBytes(int.MaxValue).CopyTo(wav, 40);

        var ok = WavAudio.TryGetDurationMs(wav, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_ChunkSizeAboveIntMaxValue_ReturnsFalseNotNegative()
    {
        // Guards the unchecked (int) cast: 0xFFFFFFFF must not become -1 and
        // slip past the bounds check as a "smaller" value.
        var wav = TestWav.Mono16k(TimeSpan.FromSeconds(1));
        BitConverter.GetBytes(uint.MaxValue).CopyTo(wav, 40);

        var ok = WavAudio.TryGetDurationMs(wav, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }
}
