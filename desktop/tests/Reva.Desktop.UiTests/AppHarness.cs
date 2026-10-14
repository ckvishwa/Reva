using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using FlaUI.Core;
using FlaUI.Core.AutomationElements;
using FlaUI.Core.Tools;
using FlaUI.UIA3;

namespace Reva.Desktop.UiTests;

/// <summary>Marks a test that needs an interactive desktop. Skipped (not passed) unless REVA_RUN_UI_TESTS=1.</summary>
public sealed class UiFactAttribute : FactAttribute
{
    public UiFactAttribute()
    {
        if (Environment.GetEnvironmentVariable("REVA_RUN_UI_TESTS") != "1")
        {
            Skip = "UI smoke tests are opt-in: set REVA_RUN_UI_TESTS=1 (needs an interactive Windows desktop).";
        }
    }
}

/// <summary>
/// Starts the real desktop app against a throw-away data directory, an in-memory Finance key and a
/// free loopback port, so it can never touch real data or a Core the person is running.
/// </summary>
public sealed class AppHarness : IDisposable
{
    private readonly string _dataDirectory;
    private readonly UIA3Automation? _automation;
    private readonly Application? _app;

    public AppHarness()
    {
        if (Environment.GetEnvironmentVariable("REVA_RUN_UI_TESTS") != "1")
        {
            _dataDirectory = string.Empty;
            return;
        }

        var repoRoot = FindRepoRoot();
        _dataDirectory = Path.Combine(Path.GetTempPath(), "reva-ui-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dataDirectory);

        var start = new ProcessStartInfo(FindAppExecutable(repoRoot)) { UseShellExecute = false };
        start.Environment["REVA_DATA_DIR"] = _dataDirectory;
        start.Environment["REVA_DOMAIN_KEYSTORE"] = "memory";
        CoreUrl = $"http://127.0.0.1:{FreePort()}/";
        start.Environment["REVA_DESKTOP_CORE_URL"] = CoreUrl;
        // The pairing gateway, if a test switches it on, binds loopback on a free port (never a LAN address).
        start.Environment["REVA_GATEWAY_HOST"] = "127.0.0.1";
        start.Environment["REVA_GATEWAY_PORT"] = FreePort().ToString();
        start.Environment["REVA_CORE_PYTHON_EXE"] = FindPython(repoRoot);
        // This checkout's reva_core must win over any editable install of another checkout.
        start.Environment["PYTHONPATH"] = repoRoot;

        _automation = new UIA3Automation();
        _app = Application.Launch(start);
        Window = _app.GetMainWindow(_automation, TimeSpan.FromSeconds(45))
            ?? throw new InvalidOperationException("The REVA window did not appear.");
        // A known, large size so layout (and what is on screen) does not depend on the default window size.
        Window.Patterns.Window.Pattern.SetWindowVisualState(FlaUI.Core.Definitions.WindowVisualState.Maximized);
        Thread.Sleep(800);
    }

    public Window Window { get; } = null!;

    public string CoreUrl { get; } = string.Empty;

    public string DataDirectory => _dataDirectory;

    public AutomationElement? Find(string automationId, TimeSpan? timeout = null) =>
        Retry.WhileNull(
            () => Window.FindFirstDescendant(cf => cf.ByAutomationId(automationId)) ?? FindOnDesktop(automationId),
            timeout ?? TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(200)).Result;

    public AutomationElement Require(string automationId, TimeSpan? timeout = null) =>
        Find(automationId, timeout) ?? throw new InvalidOperationException($"No element with AutomationId '{automationId}'.");

    /// <summary>Saves a screenshot of the window for a failure message and returns its path.</summary>
    public string Screenshot(string name)
    {
        var path = Path.Combine(Path.GetTempPath(), "reva-ui-" + name + ".png");
        Window.Capture().Save(path);
        return path;
    }

    /// <summary>
    /// Saves what the window itself renders (Win32 PrintWindow of its handle), which is correct at any display scale.
    /// Screen-rectangle captures through UI Automation are cropped on scaled displays, so design reviews use this.
    /// </summary>
    public string ScreenshotWindowContent(string name)
    {
        var handle = Window.Properties.NativeWindowHandle.ValueOrDefault;
        GetWindowRect(handle, out var rect);
        var width = rect.Right - rect.Left;
        var height = rect.Bottom - rect.Top;
        var path = Path.Combine(Path.GetTempPath(), "reva-ui-" + name + ".png");
        using var bitmap = new System.Drawing.Bitmap(width, height);
        using (var graphics = System.Drawing.Graphics.FromImage(bitmap))
        {
            var hdc = graphics.GetHdc();
            try
            {
                PrintWindow(handle, hdc, 2); // PW_RENDERFULLCONTENT
            }
            finally
            {
                graphics.ReleaseHdc(hdc);
            }
        }

        bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png);
        return path;
    }

    public bool GoneWithin(string automationId, TimeSpan timeout) =>
        Retry.WhileTrue(
            () => Window.FindFirstDescendant(cf => cf.ByAutomationId(automationId)) is not null,
            timeout,
            TimeSpan.FromMilliseconds(200)).Success;

    public void WaitForCore()
    {
        var connected = Retry.WhileFalse(
            () => Window.FindFirstDescendant(cf => cf.ByAutomationId("CoreStatusText"))?.Name?.Contains("Connected", StringComparison.OrdinalIgnoreCase) == true,
            TimeSpan.FromSeconds(90),
            TimeSpan.FromMilliseconds(500));
        if (!connected.Success)
        {
            throw new InvalidOperationException("REVA Core did not become connected.");
        }
    }

    /// <summary>Keyboard input goes to the foreground window; Windows only lets us take it after a key event.</summary>
    public void BringToFront()
    {
        var handle = Window.Properties.NativeWindowHandle.ValueOrDefault;
        keybd_event(0x12, 0, 0, UIntPtr.Zero); // ALT down/up lifts the foreground lock
        keybd_event(0x12, 0, 2, UIntPtr.Zero);
        ShowWindow(handle, 9);
        SetForegroundWindow(handle);
        Window.Focus();
        Thread.Sleep(400);
    }

    /// <summary>
    /// Scrolls the Finance page (through its UI Automation scroll pattern, so it does not depend on where the mouse
    /// is) until the element is on screen. Off-screen elements report no size, and a control clipped by the window
    /// edge reports only the visible part, so ask for its full height. The element is looked up again on every step:
    /// the accounts strip is virtualised, so a card scrolled out of view is recycled and an old handle goes stale.
    /// </summary>
    public AutomationElement ScrollIntoView(string automationId, int fullHeight = 1)
    {
        // Recycled ItemsRepeater elements can linger in the tree with an empty rectangle: prefer a visible match.
        AutomationElement? Current()
        {
            var matches = Window.FindAllDescendants(cf => cf.ByAutomationId(automationId));
            return matches.FirstOrDefault(m => m.BoundingRectangle.Height >= fullHeight) ?? matches.FirstOrDefault();
        }

        bool Visible(AutomationElement? e) => e is not null && e.BoundingRectangle.Height >= fullHeight;

        if (!Visible(Current()))
        {
            var scroller = PageScroller();
            for (var percent = 0; percent <= 100 && !Visible(Current()); percent += 8)
            {
                scroller.SetScrollPercent(FlaUI.Core.Patterns.ScrollPatternConstants.NoScroll, percent);
                Thread.Sleep(200);
            }
        }

        var element = Current();
        if (Visible(element))
        {
            return element!;
        }

        throw new InvalidOperationException(
            $"'{automationId}' never scrolled into view (found={element is not null}, fullHeight={fullHeight}). Screenshot: {Screenshot(automationId)}");
    }

    private FlaUI.Core.Patterns.IScrollPattern PageScroller()
    {
        // The Finance page's own ScrollViewer: the largest vertically scrollable element in the window.
        var candidates = Window.FindAllDescendants()
            .Select(e => (Element: e, Pattern: e.Patterns.Scroll.PatternOrDefault))
            .Where(c => c.Pattern is not null && c.Pattern.VerticallyScrollable.ValueOrDefault)
            .OrderByDescending(c => c.Element.BoundingRectangle.Width * c.Element.BoundingRectangle.Height)
            .ToList();
        return candidates.FirstOrDefault().Pattern ?? throw new InvalidOperationException("No scrollable page found.");
    }

    public string FocusedDescription()
    {
        var focused = _automation?.FocusedElement();
        var foreground = GetForegroundWindow() == Window.Properties.NativeWindowHandle.ValueOrDefault;
        return (focused is null ? "(nothing focused)" : $"{focused.ControlType} '{focused.Name}' id='{focused.AutomationId}'")
            + $", app is foreground: {foreground}";
    }

    /// <summary>
    /// UI Automation rectangles are in the caller's DPI-awareness space, which is not reliably the app's. Calibrate
    /// against a control whose design height is exactly 44 DIP (the primary button, MinHeight 44).
    /// </summary>
    public double DpiScale(string calibrationAutomationId)
    {
        var reference = ScrollIntoView(calibrationAutomationId);
        return reference.BoundingRectangle.Height / 44.0;
    }

    public void Dispose()
    {
        if (_app is not null)
        {
            try
            {
                _app.Close(); // graceful: the app stops the Core it owns
                if (!_app.HasExited)
                {
                    Retry.WhileFalse(() => _app.HasExited, TimeSpan.FromSeconds(30), TimeSpan.FromMilliseconds(250));
                }
            }
            catch (Exception)
            {
                // fall through to the kill below
            }

            if (!_app.HasExited)
            {
                _app.Kill();
            }

            _app.Dispose();
        }

        _automation?.Dispose();
        if (_dataDirectory.Length > 0)
        {
            try
            {
                Directory.Delete(_dataDirectory, recursive: true);
            }
            catch (IOException)
            {
                // Core may still be releasing files; the directory is in the temp folder.
            }
        }
    }

    private AutomationElement? FindOnDesktop(string automationId)
    {
        // A ContentDialog is hosted in a popup that UI Automation can surface under the desktop root.
        var processId = Window.Properties.ProcessId.ValueOrDefault;
        return _automation!.GetDesktop().FindFirstDescendant(
            cf => cf.ByAutomationId(automationId).And(cf.ByProcessId(processId)));
    }

    private static int FreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "pyproject.toml")) && Directory.Exists(Path.Combine(directory.FullName, "reva_core")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new InvalidOperationException("Could not find the REVA repository root above the test output.");
    }

    private static string FindAppExecutable(string repoRoot)
    {
        var configuration = AppContext.BaseDirectory.Contains($"{Path.DirectorySeparatorChar}Release{Path.DirectorySeparatorChar}", StringComparison.Ordinal)
            ? "Release"
            : "Debug";
        var exe = Path.Combine(
            repoRoot, "desktop", "src", "Reva.Desktop", "bin", configuration, "net10.0-windows10.0.19041.0", "Reva.Desktop.exe");
        return File.Exists(exe) ? exe : throw new FileNotFoundException("Build the desktop app first.", exe);
    }

    private static string FindPython(string repoRoot)
    {
        var configured = Environment.GetEnvironmentVariable("REVA_CORE_PYTHON_EXE");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return configured;
        }

        var local = Path.Combine(repoRoot, ".venv", "Scripts", "python.exe");
        return File.Exists(local)
            ? local
            : throw new FileNotFoundException(
                "Set REVA_CORE_PYTHON_EXE to a Python with REVA's requirements installed (for example the main checkout's .venv).");
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);

    [DllImport("user32.dll")]
    private static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hwnd, int command);

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
}
