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
                    using var process = Process.Start(startInfo);

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
                var matches = FindRunningProcesses(descriptor);
                try
                {
                    return matches.Count > 0;
                }
                finally
                {
                    DisposeAll(matches);
                }
            },
            cancellationToken);

    public Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                var matches = FindRunningProcesses(descriptor);
                if (matches.Count == 0)
                {
                    return AppCloseOutcome.NotRunning;
                }

                try
                {
                    var requested = 0;
                    var failed = 0;
                    foreach (var process in matches)
                    {
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

                    if (requested > 0)
                    {
                        return AppCloseOutcome.CloseRequested;
                    }

                    return failed > 0 ? AppCloseOutcome.Failed : AppCloseOutcome.NotRunning;
                }
                finally
                {
                    DisposeAll(matches);
                }
            },
            cancellationToken);

    private static bool IsShellProtocol(string target) => target.EndsWith(':');

    private static List<Process> FindRunningProcesses(AppDescriptor descriptor)
    {
        var matches = new List<Process>();
        foreach (var name in descriptor.CloseProcessNames ?? Array.Empty<string>())
        {
            foreach (var process in Process.GetProcessesByName(name))
            {
                try
                {
                    if (process.MainWindowHandle != IntPtr.Zero)
                    {
                        matches.Add(process);
                        continue;
                    }
                }
                catch (InvalidOperationException)
                {
                    // Exited while we were enumerating.
                }

                process.Dispose();
            }
        }

        return matches;
    }

    private static void DisposeAll(List<Process> processes)
    {
        foreach (var process in processes)
        {
            process.Dispose();
        }
    }
}
