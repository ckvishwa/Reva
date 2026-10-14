using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class EndpointerTests
{
    [Fact]
    public void ShouldStop_WaitsForSpeechThenTrailingSilence()
    {
        var endpointer = new Endpointer(sampleRate: 16000);

        Assert.False(endpointer.ShouldStop(Silence()));
        Assert.False(endpointer.ShouldStop(Speech()));

        var stopped = false;
        for (var i = 0; i < 24; i++)
        {
            stopped = endpointer.ShouldStop(Silence());
        }

        Assert.True(stopped);
    }

    [Fact]
    public void ShouldStop_StopsAtHardCap()
    {
        var endpointer = new Endpointer(sampleRate: 16000, maxCapture: TimeSpan.FromSeconds(1));

        var stopped = false;
        for (var i = 0; i < 32; i++)
        {
            stopped = endpointer.ShouldStop(Speech());
        }

        Assert.True(stopped);
    }

    private static short[] Silence() => new short[512];

    private static short[] Speech() => Enumerable.Repeat((short)4000, 512).ToArray();
}
