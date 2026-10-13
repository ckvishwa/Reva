using System.Diagnostics;
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
    public void Launch_ExposesRealProcessId_ForDiagnosticsOnly()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c ping -n 3 127.0.0.1 >nul"), Path.GetTempPath(), 18756);

        Assert.NotNull(handle.Pid);
        using var osProcess = Process.GetProcessById(handle.Pid!.Value);
        Assert.False(osProcess.HasExited);
    }

    [Fact]
    public void Stop_TerminatesTheRealProcess()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c ping -n 60 127.0.0.1 >nul"), Path.GetTempPath(), 18756);
        var pid = handle.Pid!.Value;

        handle.Stop();

        var deadline = DateTime.UtcNow.AddSeconds(3);
        var stillRunning = true;
        while (stillRunning && DateTime.UtcNow < deadline)
        {
            try
            {
                stillRunning = !Process.GetProcessById(pid).HasExited;
            }
            catch (ArgumentException)
            {
                stillRunning = false; // process fully gone
            }

            if (stillRunning)
            {
                Thread.Sleep(50);
            }
        }

        Assert.False(stillRunning);
    }

    [Fact]
    public void Stop_OnAlreadyExitedProcess_DoesNotThrow()
    {
        var launcher = new CoreProcessLauncher();
        using var handle = launcher.Launch(CmdResolution("/c exit 0"), Path.GetTempPath(), 18756);
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!handle.HasExited && DateTime.UtcNow < deadline)
        {
            Thread.Sleep(50);
        }

        var exception = Record.Exception(() => handle.Stop());

        Assert.Null(exception);
    }

    [Fact]
    public void Launch_Throws_WhenResolutionUnavailable()
    {
        var launcher = new CoreProcessLauncher();
        var unavailable = CoreExecutableResolution.Unavailable("no repo found");

        Assert.Throws<InvalidOperationException>(() => launcher.Launch(unavailable, Path.GetTempPath(), 18756));
    }
}
