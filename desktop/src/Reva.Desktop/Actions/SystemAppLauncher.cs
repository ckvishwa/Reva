using System.Diagnostics;
using System.Runtime.InteropServices;

namespace Reva.Desktop.Actions;

/// <summary>The real Windows seams under <see cref="AppActionExecutor"/>. Nothing here takes text from
/// a request: <see cref="LaunchTarget"/> comes from the fixed built-ins or the owner's approved apps.</summary>
public sealed class SystemAppLauncher : IAppLauncher
{
    public int? Start(LaunchTarget target)
    {
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = target.OpenTarget, // a fixed literal or a Start Menu shortcut the owner approved
            UseShellExecute = true,
        });
        return process?.Id;
    }

    public IReadOnlyList<int> RunningProcessIds(IReadOnlyList<string> processNames)
    {
        var ids = new List<int>();
        foreach (var name in processNames)
        {
            foreach (var process in Process.GetProcessesByName(name))
            {
                try
                {
                    if (!process.HasExited)
                    {
                        ids.Add(process.Id);
                    }
                }
                catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // Exited while we looked: not running.
                }
                finally
                {
                    process.Dispose();
                }
            }
        }

        return ids;
    }

    public bool RequestClose(IReadOnlyList<string> processNames)
    {
        var asked = false;
        foreach (var name in processNames)
        {
            foreach (var process in Process.GetProcessesByName(name))
            {
                try
                {
                    // A polite close: the app may ask to save. Never Kill().
                    asked |= process.CloseMainWindow();
                }
                catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // Gone already.
                }
                finally
                {
                    process.Dispose();
                }
            }
        }

        return asked;
    }
}

/// <summary>Visible, titled, non-tool top-level windows, with the process that owns each.</summary>
public sealed class SystemWindowProbe : IWindowProbe
{
    private const int GwlExStyle = -20;
    private const long WsExToolWindow = 0x80;
    private const long WsExNoActivate = 0x08000000;

    public IReadOnlyList<TopWindow> VisibleWindows()
    {
        var found = new List<TopWindow>();
        var names = new Dictionary<int, string>();
        Native.EnumWindows(
            (handle, _) =>
            {
                if (!Native.IsWindowVisible(handle) || Native.GetWindowTextLength(handle) == 0)
                {
                    return true;
                }

                var style = Native.GetWindowLongPtr(handle, GwlExStyle).ToInt64();
                if ((style & (WsExToolWindow | WsExNoActivate)) != 0 || Native.GetWindow(handle, 4 /* GW_OWNER */) != IntPtr.Zero)
                {
                    return true;
                }

                Native.GetWindowThreadProcessId(handle, out var pid);
                if (!names.TryGetValue((int)pid, out var name))
                {
                    name = ProcessName((int)pid);
                    names[(int)pid] = name;
                }

                if (name.Length > 0)
                {
                    found.Add(new TopWindow(handle, (int)pid, name, Title(handle)));
                }

                return true;
            },
            IntPtr.Zero);
        return found;
    }

    public IntPtr Foreground() => Native.GetForegroundWindow();

    private static string Title(IntPtr handle)
    {
        var length = Native.GetWindowTextLength(handle);
        if (length <= 0 || length > 512)
        {
            return string.Empty;
        }

        var buffer = new System.Text.StringBuilder(length + 1);
        return Native.GetWindowText(handle, buffer, buffer.Capacity) > 0 ? buffer.ToString() : string.Empty;
    }

    private static string ProcessName(int pid)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            return process.ProcessName;
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            return string.Empty;
        }
    }

    private static class Native
    {
        public delegate bool EnumWindowsProc(IntPtr handle, IntPtr lParam);

        [DllImport("user32.dll")]
        public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

        [DllImport("user32.dll")]
        public static extern bool IsWindowVisible(IntPtr handle);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int GetWindowTextLength(IntPtr handle);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int GetWindowText(IntPtr handle, System.Text.StringBuilder text, int maxCount);

        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
        public static extern IntPtr GetWindowLongPtr(IntPtr handle, int index);

        [DllImport("user32.dll")]
        public static extern IntPtr GetWindow(IntPtr handle, uint command);

        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);

        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();
    }
}
