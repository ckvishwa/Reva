using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

// Environment variables are process-global and xUnit parallelizes across
// classes; without this, CreateDefault() called concurrently from another
// class sees a mutated environment and fails intermittently.
[CollectionDefinition("EnvironmentVariables", DisableParallelization = true)]
public class EnvironmentVariablesCollection;

[Collection("EnvironmentVariables")]
public class DesktopConfigurationTests
{
    private const string SttEnvVar = "REVA_DESKTOP_STT_TIMEOUT_SECONDS";

    [Theory]
    [InlineData("http://localhost:8756/")]
    [InlineData("http://127.0.0.1:8756/")]
    [InlineData("http://[::1]:8756/")]
    public void Constructor_AcceptsLoopbackUrl(string url)
    {
        var configuration = new DesktopConfiguration(new Uri(url), "data", TimeSpan.FromSeconds(5), DesktopConfiguration.DefaultSttRequestTimeout);

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
            () => new DesktopConfiguration(new Uri(url), "data", TimeSpan.FromSeconds(5), DesktopConfiguration.DefaultSttRequestTimeout));
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
    public void CreateDefault_UsesStableLocalAppDataDirectory_WhenNoEnvironmentOverride()
    {
        var configuration = DesktopConfiguration.CreateDefault();

        Assert.Equal(RuntimePaths.GetDefaultDataDirectory(), configuration.CoreDataDirectory);
    }

    [Fact]
    public void CreateDefault_RespectsDataDirectoryEnvironmentOverride()
    {
        var overridePath = Path.Combine(Path.GetTempPath(), "reva-desktop-config-test-" + Guid.NewGuid());
        Environment.SetEnvironmentVariable("REVA_DATA_DIR", overridePath);
        try
        {
            var configuration = DesktopConfiguration.CreateDefault();

            Assert.Equal(overridePath, configuration.CoreDataDirectory);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_DATA_DIR", null);
        }
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

    [Fact]
    public void CreateDefault_NoOverride_UsesThirtySecondSttTimeout()
    {
        var previous = Environment.GetEnvironmentVariable(SttEnvVar);
        Environment.SetEnvironmentVariable(SttEnvVar, null);
        try
        {
            Assert.Equal(TimeSpan.FromSeconds(30), DesktopConfiguration.CreateDefault().SttRequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable(SttEnvVar, previous);
        }
    }

    [Fact]
    public void CreateDefault_SttTimeoutEnvVarOverride_IsRespected()
    {
        var previous = Environment.GetEnvironmentVariable(SttEnvVar);
        Environment.SetEnvironmentVariable(SttEnvVar, "45");
        try
        {
            Assert.Equal(TimeSpan.FromSeconds(45), DesktopConfiguration.CreateDefault().SttRequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable(SttEnvVar, previous);
        }
    }

    [Theory]
    [InlineData("0")]
    [InlineData("-5")]
    [InlineData("banana")]
    [InlineData("")]
    public void CreateDefault_InvalidSttTimeoutOverride_FallsBackToDefault(string value)
    {
        var previous = Environment.GetEnvironmentVariable(SttEnvVar);
        Environment.SetEnvironmentVariable(SttEnvVar, value);
        try
        {
            Assert.Equal(TimeSpan.FromSeconds(30), DesktopConfiguration.CreateDefault().SttRequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable(SttEnvVar, previous);
        }
    }
}
