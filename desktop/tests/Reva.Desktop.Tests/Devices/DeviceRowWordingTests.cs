using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Devices;

public class DeviceRowWordingTests
{
    [Theory]
    [InlineData(0, "just now")]
    [InlineData(30, "just now")]
    [InlineData(300, "5 min ago")]
    [InlineData(7200, "2 h ago")]
    public void Relative_times_read_naturally_after_Synced(int secondsAgo, string expected)
    {
        var now = new DateTimeOffset(2026, 10, 14, 12, 0, 0, TimeSpan.Zero);
        var iso = now.AddSeconds(-secondsAgo).ToString("o");

        Assert.Equal($"Synced {expected}", $"Synced {DeviceRowViewModel.RelativeTime(iso, now)}");
    }
}
