using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class DesktopConfigurationTests
{
    [Theory]
    [InlineData("http://localhost:8756/")]
    [InlineData("http://127.0.0.1:8756/")]
    [InlineData("http://[::1]:8756/")]
    public void Constructor_AcceptsLoopbackUrl(string url)
    {
        var configuration = new DesktopConfiguration(new Uri(url), "data", TimeSpan.FromSeconds(5));

        Assert.Equal(new Uri(url), configuration.CoreBaseUrl);
    }

    [Theory]
    [InlineData("http://192.168.1.10:8756/")]
    [InlineData("http://example.com:8756/")]
    [InlineData("http://0.0.0.0:8756/")]
    [InlineData("https://reva-core.internal/")]
    public void Constructor_RejectsRemoteUrl(string url)
    {
        Assert.Throws<DesktopConfigurationException>(
            () => new DesktopConfiguration(new Uri(url), "data", TimeSpan.FromSeconds(5)));
    }

    [Theory]
    [InlineData("localhost", true)]
    [InlineData("127.0.0.1", true)]
    [InlineData("::1", true)]
    [InlineData("LOCALHOST", true)]
    [InlineData("192.168.1.10", false)]
    [InlineData("example.com", false)]
    public void IsLoopback_ClassifiesHostsCorrectly(string host, bool expected)
    {
        var uri = new Uri($"http://{(host.Contains(':') ? $"[{host}]" : host)}:8756/");

        Assert.Equal(expected, DesktopConfiguration.IsLoopback(uri));
    }

    [Fact]
    public void CreateDefault_UsesLoopbackUrlAndDoesNotThrow()
    {
        var configuration = DesktopConfiguration.CreateDefault();

        Assert.True(DesktopConfiguration.IsLoopback(configuration.CoreBaseUrl));
    }

    [Fact]
    public void CreateDefault_RespectsCoreUrlEnvironmentOverride()
    {
        Environment.SetEnvironmentVariable("REVA_DESKTOP_CORE_URL", "http://127.0.0.1:9999/");
        try
        {
            var configuration = DesktopConfiguration.CreateDefault();

            Assert.Equal(9999, configuration.CoreBaseUrl.Port);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_DESKTOP_CORE_URL", null);
        }
    }

    [Fact]
    public void CreateDefault_RejectsRemoteUrlFromEnvironmentOverride()
    {
        Environment.SetEnvironmentVariable("REVA_DESKTOP_CORE_URL", "http://example.com/");
        try
        {
            Assert.Throws<DesktopConfigurationException>(() => DesktopConfiguration.CreateDefault());
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_DESKTOP_CORE_URL", null);
        }
    }

    [Fact]
    public void CreateDefault_UsesTenSecondTimeout_WhenNoEnvironmentOverride()
    {
        var configuration = DesktopConfiguration.CreateDefault();

        Assert.Equal(TimeSpan.FromSeconds(10), configuration.RequestTimeout);
    }

    [Fact]
    public void CreateDefault_RespectsRequestTimeoutEnvironmentOverride()
    {
        Environment.SetEnvironmentVariable("REVA_DESKTOP_REQUEST_TIMEOUT_SECONDS", "120");
        try
        {
            var configuration = DesktopConfiguration.CreateDefault();

            Assert.Equal(TimeSpan.FromSeconds(120), configuration.RequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_DESKTOP_REQUEST_TIMEOUT_SECONDS", null);
        }
    }

    [Theory]
    [InlineData("not-a-number")]
    [InlineData("-5")]
    [InlineData("0")]
    [InlineData("")]
    public void CreateDefault_FallsBackToTenSecondTimeout_OnInvalidEnvironmentOverride(string badValue)
    {
        Environment.SetEnvironmentVariable("REVA_DESKTOP_REQUEST_TIMEOUT_SECONDS", badValue);
        try
        {
            var configuration = DesktopConfiguration.CreateDefault();

            Assert.Equal(TimeSpan.FromSeconds(10), configuration.RequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_DESKTOP_REQUEST_TIMEOUT_SECONDS", null);
        }
    }
}
