using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class LocalTokenProviderTests
{
    private static DesktopConfiguration ConfigurationFor(string dataDirectory) =>
        new(new Uri("http://127.0.0.1:8756/"), dataDirectory, TimeSpan.FromSeconds(5));

    [Fact]
    public async Task GetTokenAsync_ReturnsUnavailable_WhenFileDoesNotExist()
    {
        var dataDir = Directory.CreateTempSubdirectory().FullName;
        var provider = new LocalTokenProvider(ConfigurationFor(dataDir));

        var result = await provider.GetTokenAsync();

        Assert.False(result.IsAvailable);
    }

    [Fact]
    public async Task GetTokenAsync_ReturnsAvailable_WithTrimmedTokenValue()
    {
        var dataDir = Directory.CreateTempSubdirectory().FullName;
        await File.WriteAllTextAsync(Path.Combine(dataDir, "local_auth_token"), "  test-token-value  \n");
        var provider = new LocalTokenProvider(ConfigurationFor(dataDir));

        var result = await provider.GetTokenAsync();

        Assert.True(result.IsAvailable);
        Assert.Equal("test-token-value", result.Token);
    }

    [Fact]
    public async Task GetTokenAsync_ReturnsUnavailable_WhenFileIsEmpty()
    {
        var dataDir = Directory.CreateTempSubdirectory().FullName;
        await File.WriteAllTextAsync(Path.Combine(dataDir, "local_auth_token"), "   ");
        var provider = new LocalTokenProvider(ConfigurationFor(dataDir));

        var result = await provider.GetTokenAsync();

        Assert.False(result.IsAvailable);
    }

    [Fact]
    public async Task GetTokenAsync_ReturnsUnavailable_WhenDataDirectoryDoesNotExist()
    {
        var dataDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
        var provider = new LocalTokenProvider(ConfigurationFor(dataDir));

        var result = await provider.GetTokenAsync();

        Assert.False(result.IsAvailable);
    }

    [Fact]
    public void Token_Throws_WhenNotAvailable()
    {
        var result = TokenLoadResult.Unavailable();

        Assert.Throws<InvalidOperationException>(() => result.Token);
    }

    [Fact]
    public void ToString_NeverExposesTokenValue()
    {
        var result = TokenLoadResult.Available("super-secret-token-value");

        var text = result.ToString();

        Assert.DoesNotContain("super-secret-token-value", text);
    }
}
