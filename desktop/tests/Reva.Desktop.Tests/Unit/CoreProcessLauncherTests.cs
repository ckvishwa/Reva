using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class CoreProcessLauncherTests
{
    // Uses cmd.exe, never python.exe: this test verifies CoreProcessLauncher's
    // *mechanics* (start, environment, no-window, exit tracking), not Core
    // resolution — that is DeveloperModeCoreExecutableLocatorTests's job.
    private static CoreExecutableResolution CmdResolution(string arguments) =>
        CoreExecutableResolution.Available(
            Environment.ExpandEnvironmentVariables(@"%WINDIR%\System32\cmd.exe"),
            arguments,
            Path.GetTempPath());

    [Fact]
    public void Launch_StartsProcess_AndHasExitedIsFalseImmediately()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c ping -n 3 127.0.0.1 >nul"), Path.GetTempPath(), 18756);

        Assert.False(handle.HasExited);
    }

    [Fact]
    public async Task Launch_HasExitedBecomesTrue_AfterProcessExits()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c exit 0"), Path.GetTempPath(), 18756);

        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!handle.HasExited && DateTime.UtcNow < deadline)
        {
            await Task.Delay(50);
        }

        Assert.True(handle.HasExited);
        Assert.Equal(0, handle.ExitCode);
    }

    [Fact]
    public async Task Launch_ExitCodeReflectsNonZeroExit()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c exit 7"), Path.GetTempPath(), 18756);

        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!handle.HasExited && DateTime.UtcNow < deadline)
        {
            await Task.Delay(50);
        }

        Assert.Equal(7, handle.ExitCode);
    }

    [Fact]
    public void Launch_Throws_WhenResolutionUnavailable()
    {
        var launcher = new CoreProcessLauncher();
        var unavailable = CoreExecutableResolution.Unavailable("no repo found");

        Assert.Throws<InvalidOperationException>(() => launcher.Launch(unavailable, Path.GetTempPath(), 18756));
    }
}
