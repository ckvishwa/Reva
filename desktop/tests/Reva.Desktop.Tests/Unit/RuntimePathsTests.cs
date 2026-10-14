using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class RuntimePathsTests
{
    [Fact]
    public void GetDefaultDataDirectory_ReturnsRevaFolderUnderLocalAppData()
    {
        var expected = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Reva");

        var actual = RuntimePaths.GetDefaultDataDirectory();

        Assert.Equal(expected, actual);
    }

    [Fact]
    public void GetDefaultDataDirectory_IsStableAcrossCalls()
    {
        Assert.Equal(RuntimePaths.GetDefaultDataDirectory(), RuntimePaths.GetDefaultDataDirectory());
    }

    [Fact]
    public void GetDefaultLogDirectory_ReturnsLogsFolderUnderDataDirectory()
    {
        var expected = Path.Combine(RuntimePaths.GetDefaultDataDirectory(), "logs");

        var actual = RuntimePaths.GetDefaultLogDirectory();

        Assert.Equal(expected, actual);
    }
}
