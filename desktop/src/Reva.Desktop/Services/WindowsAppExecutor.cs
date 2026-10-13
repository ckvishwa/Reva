using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace Reva.Desktop.Services;

/// <summary>The only file in the app that touches System.Diagnostics.Process.
/// Every operation runs on the thread pool: Process.Start with
/// UseShellExecute=true blocks while the shell resolves and launches the
/// target, and process enumeration is not instant either — neither belongs on
/// the UI thread.</summary>
public sealed class WindowsAppExecutor : IAppExecutor
{
    private static readonly TimeSpan WindowCloseTimeout = TimeSpan.FromSeconds(2);

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
                var liveProcessIds = new HashSet<int>();
                foreach (var process in GetProcesses(descriptor))
                {
                    int? processId = null;
                    try
                    {
                        process.Refresh();
                        processId = process.Id;
                        liveProcessIds.Add(processId.Value);

                        try
                        {
                            if (process.MainWindowHandle != IntPtr.Zero)
                            {
                                running = true;
                            }
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
                            if (processId is not null)
                            {
                                liveProcessIds.Remove(processId.Value);
                            }
                        }
                    }
                    catch (Win32Exception)
                    {
                        running = true;
                    }
                    catch (InvalidOperationException)
                    {
                        // Exited while we were enumerating.
                    }
                    finally
                    {
                        process.Dispose();
                    }
                }

                return running || liveProcessIds.Count > 0;
            },
            cancellationToken);

    public Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
        Task.Run(
            () =>
            {
                var requested = 0;
                var failed = 0;
                var liveProcessIds = new HashSet<int>();
                var fallbackCandidateIds = new HashSet<int>();
                foreach (var process in GetProcesses(descriptor))
                {
                    int processId;
                    try
                    {
                        try
                        {
                            process.Refresh();
                            processId = process.Id;
                            liveProcessIds.Add(processId);
                        }
                        catch (InvalidOperationException)
                        {
                            // Exited before we could inspect it.
                            continue;
                        }
                        catch (Win32Exception)
                        {
                            failed++;
                            continue;
                        }

                        try
                        {
                            if (process.MainWindowHandle == IntPtr.Zero)
                            {
                                fallbackCandidateIds.Add(processId);
                                continue;
                            }
                        }
                        catch (InvalidOperationException)
                        {
                            // Exited before we could inspect it.
                            liveProcessIds.Remove(processId);
                            continue;
                        }
                        catch (Win32Exception)
                        {
                            // Existing process, but Windows would not expose
                            // the window handle. Try the bounded top-level
                            // window fallback before declaring failure.
                            fallbackCandidateIds.Add(processId);
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
                                fallbackCandidateIds.Add(processId);
                            }
                        }
                        catch (InvalidOperationException)
                        {
                            // The process exited between enumeration and this
                            // call — up to 30 seconds can pass while the user
                            // decides. Not an error; just nothing left to close.
                            liveProcessIds.Remove(processId);
                        }
                        catch (Win32Exception)
                        {
                            // Access denied or the window is unresponsive. Try
                            // the bounded top-level window fallback before
                            // declaring failure.
                            fallbackCandidateIds.Add(processId);
                        }
                    }
                    finally
                    {
                        process.Dispose();
                    }
                }

                if (fallbackCandidateIds.Count > 0)
                {
                    var fallback = CloseTopLevelWindows(fallbackCandidateIds);
                    requested += fallback.Requested;
                    failed += fallback.Failed;
                }

                if (requested > 0)
                {
                    return AppCloseOutcome.CloseRequested;
                }

                return failed > 0 || liveProcessIds.Count > 0
                    ? AppCloseOutcome.Failed
                    : AppCloseOutcome.NotRunning;
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

    private CloseCounts CloseTopLevelWindows(IReadOnlySet<int> processIds)
    {
        var requested = 0;
        var failed = 0;
        foreach (var window in _processRuntime.GetTopLevelWindows())
        {
            try
            {
                if (!processIds.Contains(window.ProcessId)
                    || !window.IsVisible
                    || window.IsOwned)
                {
                    continue;
                }

                try
                {
                    if (window.SendClose(WindowCloseTimeout))
                    {
                        requested++;
                    }
                    else
                    {
                        failed++;
                    }
                }
                catch (Win32Exception)
                {
                    failed++;
                }
            }
            finally
            {
                window.Dispose();
            }
        }

        return new CloseCounts(requested, failed);
    }

    private readonly record struct CloseCounts(int Requested, int Failed);
}

internal interface IWindowsProcessRuntime
{
    IWindowsAppProcess? Start(ProcessStartInfo startInfo);

    IReadOnlyList<IWindowsAppProcess> GetProcessesByName(string processName);

    IReadOnlyList<IWindowsAppWindow> GetTopLevelWindows();
}

internal interface IWindowsAppProcess : IDisposable
{
    int Id { get; }

    void Refresh();

    IntPtr MainWindowHandle { get; }

    bool CloseMainWindow();
}

internal interface IWindowsAppWindow : IDisposable
{
    int ProcessId { get; }

    bool IsVisible { get; }

    bool IsOwned { get; }

    bool SendClose(TimeSpan timeout);
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

    public IReadOnlyList<IWindowsAppWindow> GetTopLevelWindows()
    {
        var windows = new List<IWindowsAppWindow>();
        NativeMethods.EnumWindows(
            (handle, _) =>
            {
                windows.Add(new SystemWindowsAppWindow(handle));
                return true;
            },
            IntPtr.Zero);

        return windows;
    }
}

internal sealed class SystemWindowsAppProcess : IWindowsAppProcess
{
    private readonly Process _process;

    public SystemWindowsAppProcess(Process process) => _process = process;

    public int Id => _process.Id;

    public void Refresh() => _process.Refresh();

    public IntPtr MainWindowHandle => _process.MainWindowHandle;

    public bool CloseMainWindow() => _process.CloseMainWindow();

    public void Dispose()
    {
        _process.Dispose();
    }
}

internal sealed class SystemWindowsAppWindow : IWindowsAppWindow
{
    private const uint GwOwner = 4;
    private const uint WmClose = 0x0010;
    private const uint SmtoBlock = 0x0001;
    private const uint SmtoAbortIfHung = 0x0002;

    private readonly IntPtr _handle;

    public SystemWindowsAppWindow(IntPtr handle) => _handle = handle;

    public int ProcessId
    {
        get
        {
            _ = NativeMethods.GetWindowThreadProcessId(_handle, out var processId);
            return unchecked((int)processId);
        }
    }

    public bool IsVisible => NativeMethods.IsWindowVisible(_handle);

    public bool IsOwned => NativeMethods.GetWindow(_handle, GwOwner) != IntPtr.Zero;

    public bool SendClose(TimeSpan timeout)
    {
        var timeoutMilliseconds = checked((uint)Math.Max(1, timeout.TotalMilliseconds));
        var result = NativeMethods.SendMessageTimeout(
            _handle,
            WmClose,
            IntPtr.Zero,
            IntPtr.Zero,
            SmtoBlock | SmtoAbortIfHung,
            timeoutMilliseconds,
            out _);

        return result != IntPtr.Zero;
    }

    public void Dispose()
    {
        // HWNDs are borrowed from EnumWindows; this wrapper owns no handle.
    }
}

internal static partial class NativeMethods
{
    public delegate bool EnumWindowsProc(IntPtr handle, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc enumProc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr handle);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetWindow(IntPtr handle, uint command);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr handle,
        uint message,
        IntPtr wParam,
        IntPtr lParam,
        uint flags,
        uint timeoutMilliseconds,
        out IntPtr result);
}
