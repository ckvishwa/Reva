using System.ComponentModel;
using System.Diagnostics;

namespace Reva.Desktop.Services;

/// <summary>The only file in the app that touches System.Diagnostics.Process.
/// Every operation runs on the thread pool: Process.Start with
/// UseShellExecute=true blocks while the shell resolves and launches the
/// target, and process enumeration is not instant either — neither belongs on
/// the UI thread.</summary>
public sealed class WindowsAppExecutor : IAppExecutor
{
    private readonly IWindowsProcessRuntime _processRuntime;

    public WindowsAppExecutor()
        : this(new SystemWindowsProcessRuntime())
    {
    }

    internal WindowsAppExecutor(IWindowsProcessRuntime processRuntime) =>
        _processRuntime = processRuntime;

    public Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                try
                {
                    var startInfo = new ProcessStartInfo
                    {
                        FileName = descriptor.OpenTarget,   // fixed literal, never user input
                        UseShellExecute = true,
                    };
                    using var process = _processRuntime.Start(startInfo);

                    // ms-settings: and other shell protocol handlers legitimately
                    // return null from Process.Start even on success, so a null
                    // process is only a failure for entries that launch an exe.
                    return process is not null || IsShellProtocol(descriptor.OpenTarget);
                }
                catch (Exception ex) when (
                    ex is Win32Exception or InvalidOperationException or System.IO.FileNotFoundException)
                {
                    DesktopLogger.Info($"command.state=Rejected action=Open app={descriptor.Key} reason=launch_failed");
                    return false;
                }
            },
            cancellationToken);

    public Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                var running = false;
                foreach (var process in GetProcesses(descriptor))
                {
                    try
                    {
                        try
                        {
                            running |= process.MainWindowHandle != IntPtr.Zero;
                        }
                        catch (Win32Exception)
                        {
                            // If Windows says the process exists but refuses
                            // to expose its window handle, treat it
                            // conservatively as running.
                            running = true;
                        }
                        catch (InvalidOperationException)
                        {
                            // Exited while we were enumerating.
                        }
                    }
                    finally
                    {
                        process.Dispose();
                    }
                }

                return running;
            },
            cancellationToken);

    public Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                var requested = 0;
                var failed = 0;
                foreach (var process in GetProcesses(descriptor))
                {
                    try
                    {
                        try
                        {
                            if (process.MainWindowHandle == IntPtr.Zero)
                            {
                                continue;
                            }
                        }
                        catch (InvalidOperationException)
                        {
                            // Exited before we could inspect it.
                            continue;
                        }
                        catch (Win32Exception)
                        {
                            // Existing process, but Windows would not expose
                            // the window handle. Count it as a close failure
                            // rather than pretending nothing is running.
                            failed++;
                            continue;
                        }

                        try
                        {
                            // Polite request only — the target may ignore it or
                            // raise its own "save changes?" prompt. Never Kill().
                            if (process.CloseMainWindow())
                            {
                                requested++;
                            }
                            else
                            {
                                failed++;
                            }
                        }
                        catch (InvalidOperationException)
                        {
                            // The process exited between enumeration and this
                            // call — up to 30 seconds can pass while the user
                            // decides. Not an error; just nothing left to close.
                        }
                        catch (Win32Exception)
                        {
                            // Access denied or the window is unresponsive.
                            // This is a genuine close failure, not a not-running condition.
                            failed++;
                        }
                    }
                    finally
                    {
                        process.Dispose();
                    }
                }

                if (requested > 0)
                {
                    return AppCloseOutcome.CloseRequested;
                }

                return failed > 0 ? AppCloseOutcome.Failed : AppCloseOutcome.NotRunning;
            },
            cancellationToken);

    private static bool IsShellProtocol(string target) => target.EndsWith(':');

    private IReadOnlyList<IWindowsAppProcess> GetProcesses(AppDescriptor descriptor)
    {
        var processes = new List<IWindowsAppProcess>();
        foreach (var name in descriptor.CloseProcessNames ?? Array.Empty<string>())
        {
            processes.AddRange(_processRuntime.GetProcessesByName(name));
        }

        return processes;
    }
}

internal interface IWindowsProcessRuntime
{
    IWindowsAppProcess? Start(ProcessStartInfo startInfo);

    IReadOnlyList<IWindowsAppProcess> GetProcessesByName(string processName);
}

internal interface IWindowsAppProcess : IDisposable
{
    IntPtr MainWindowHandle { get; }

    bool CloseMainWindow();
}

internal sealed class SystemWindowsProcessRuntime : IWindowsProcessRuntime
{
    public IWindowsAppProcess? Start(ProcessStartInfo startInfo)
    {
        var process = Process.Start(startInfo);
        return process is null ? null : new SystemWindowsAppProcess(process);
    }

    public IReadOnlyList<IWindowsAppProcess> GetProcessesByName(string processName)
    {
        var processes = Process.GetProcessesByName(processName);
        var wrapped = new IWindowsAppProcess[processes.Length];
        for (var i = 0; i < processes.Length; i++)
        {
            wrapped[i] = new SystemWindowsAppProcess(processes[i]);
        }

        return wrapped;
    }
}

internal sealed class SystemWindowsAppProcess : IWindowsAppProcess
{
    private readonly Process _process;

    public SystemWindowsAppProcess(Process process) => _process = process;

    public IntPtr MainWindowHandle => _process.MainWindowHandle;

    public bool CloseMainWindow() => _process.CloseMainWindow();

    public void Dispose()
    {
        _process.Dispose();
    }
}
