using System.ComponentModel;
using System.Diagnostics;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WindowsAppExecutorTests
{
    private static readonly AppDescriptor TestApp = new(
        "testapp",
        "Test App",
        new[] { "test app" },
        "testapp.exe",
        new[] { "testapp" });

    [Fact]
    public async Task CloseAsync_CloseMainWindowReturnsFalse_ReturnsFailed()
    {
        var process = FakeProcess.Visible(closeResult: false);
        var executor = NewExecutor(process);

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.Failed, outcome);
        Assert.Equal(1, process.CloseCallCount);
        Assert.Equal(1, process.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_CloseMainWindowThrowsWin32Exception_ReturnsFailed()
    {
        var process = FakeProcess.Visible(closeException: new Win32Exception(5, "C:\\Sensitive\\close detail"));
        var executor = NewExecutor(process);

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.Failed, outcome);
        Assert.Equal(1, process.CloseCallCount);
        Assert.Equal(1, process.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_AllMatchingProcessesExited_ReturnsNotRunning()
    {
        var first = FakeProcess.WithRefreshException(new InvalidOperationException("already gone one"));
        var second = FakeProcess.Visible(closeException: new InvalidOperationException("already gone two"));
        var executor = NewExecutor(first, second);

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.NotRunning, outcome);
        Assert.Equal(0, first.CloseCallCount);
        Assert.Equal(1, second.CloseCallCount);
        Assert.Equal(1, first.DisposeCount);
        Assert.Equal(1, second.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_MinimizedEligibleWindow_ReceivesBoundedCloseRequest()
    {
        var process = FakeProcess.NoWindow(id: 101);
        var window = FakeWindow.Eligible(processId: 101);
        var executor = NewExecutor(new[] { process }, new[] { window });

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.CloseRequested, outcome);
        Assert.Equal(1, process.RefreshCallCount);
        Assert.Equal(0, process.CloseCallCount);
        Assert.Equal(1, window.SendCloseCallCount);
        Assert.Equal(1, process.DisposeCount);
        Assert.Equal(1, window.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_RestoredEligibleWindow_StillUsesPrimaryCloseMainWindow()
    {
        var process = FakeProcess.Visible(id: 101, closeResult: true);
        var window = FakeWindow.Eligible(processId: 101);
        var executor = NewExecutor(new[] { process }, new[] { window });

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.CloseRequested, outcome);
        Assert.Equal(1, process.RefreshCallCount);
        Assert.Equal(1, process.CloseCallCount);
        Assert.Equal(0, window.SendCloseCallCount);
    }

    [Fact]
    public async Task CloseAsync_ZeroMainWindowHandle_UsesSafeTopLevelWindowFallback()
    {
        var process = FakeProcess.NoWindow(id: 101);
        var window = FakeWindow.Eligible(processId: 101);
        var executor = NewExecutor(new[] { process }, new[] { window });

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.CloseRequested, outcome);
        Assert.Equal(1, window.SendCloseCallCount);
    }

    [Fact]
    public async Task CloseAsync_UnrelatedProcessWindows_AreNeverTargeted()
    {
        var process = FakeProcess.NoWindow(id: 101);
        var unrelated = FakeWindow.Eligible(processId: 202);
        var executor = NewExecutor(new[] { process }, new[] { unrelated });

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.Failed, outcome);
        Assert.Equal(0, unrelated.SendCloseCallCount);
        Assert.Equal(1, unrelated.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_HiddenOrOwnedHelperWindows_AreNeverTargeted()
    {
        var process = FakeProcess.NoWindow(id: 101);
        var hidden = FakeWindow.Hidden(processId: 101);
        var owned = FakeWindow.Owned(processId: 101);
        var executor = NewExecutor(new[] { process }, new[] { hidden, owned });

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.Failed, outcome);
        Assert.Equal(0, hidden.SendCloseCallCount);
        Assert.Equal(0, owned.SendCloseCallCount);
    }

    [Fact]
    public async Task CloseAsync_MatchingLiveProcessButNoWindowAvailable_ReturnsFailed()
    {
        var process = FakeProcess.NoWindow(id: 101);
        var executor = NewExecutor(process);

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.Failed, outcome);
    }

    [Fact]
    public async Task CloseAsync_FallbackPartialSuccess_ReturnsCloseRequested()
    {
        var first = FakeProcess.NoWindow(id: 101);
        var second = FakeProcess.NoWindow(id: 102);
        var success = FakeWindow.Eligible(processId: 101, closeResult: true);
        var failure = FakeWindow.Eligible(processId: 102, closeResult: false);
        var executor = NewExecutor(new[] { first, second }, new[] { success, failure });

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.CloseRequested, outcome);
        Assert.Equal(1, success.SendCloseCallCount);
        Assert.Equal(1, failure.SendCloseCallCount);
    }

    [Fact]
    public async Task CloseAsync_OneSuccessPlusOneFailure_ReturnsCloseRequested()
    {
        var success = FakeProcess.Visible(closeResult: true);
        var failure = FakeProcess.Visible(closeResult: false);
        var executor = NewExecutor(success, failure);

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.CloseRequested, outcome);
        Assert.Equal(1, success.DisposeCount);
        Assert.Equal(1, failure.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_MainWindowHandleThrowsWin32Exception_ReturnsFailed()
    {
        var process = FakeProcess.WithMainWindowException(new Win32Exception(5, "C:\\Sensitive\\handle detail"));
        var executor = NewExecutor(process);

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.Failed, outcome);
        Assert.Equal(0, process.CloseCallCount);
        Assert.Equal(1, process.DisposeCount);
    }

    [Fact]
    public async Task IsRunningAsync_MainWindowHandleThrowsWin32Exception_ReturnsTrue()
    {
        var process = FakeProcess.WithMainWindowException(new Win32Exception(5, "C:\\Sensitive\\handle detail"));
        var executor = NewExecutor(process);

        var running = await executor.IsRunningAsync(TestApp);

        Assert.True(running);
        Assert.Equal(1, process.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_EveryEnumeratedProcess_DisposedExactlyOnce()
    {
        var success = FakeProcess.Visible(closeResult: true);
        var noWindow = FakeProcess.NoWindow();
        var exitedDuringInspection = FakeProcess.WithRefreshException(new InvalidOperationException("exited"));
        var handleFailure = FakeProcess.WithMainWindowException(new Win32Exception(5, "access denied"));
        var closeFailure = FakeProcess.Visible(closeException: new Win32Exception(5, "close denied"));
        var executor = NewExecutor(success, noWindow, exitedDuringInspection, handleFailure, closeFailure);

        await executor.CloseAsync(TestApp);

        Assert.Equal(1, success.DisposeCount);
        Assert.Equal(1, noWindow.DisposeCount);
        Assert.Equal(1, exitedDuringInspection.DisposeCount);
        Assert.Equal(1, handleFailure.DisposeCount);
        Assert.Equal(1, closeFailure.DisposeCount);
    }

    [Fact]
    public async Task CloseAsync_EveryEnumeratedWindow_DisposedExactlyOnce()
    {
        var process = FakeProcess.NoWindow(id: 101);
        var eligible = FakeWindow.Eligible(processId: 101);
        var hidden = FakeWindow.Hidden(processId: 101);
        var unrelated = FakeWindow.Eligible(processId: 202);
        var executor = NewExecutor(new[] { process }, new[] { eligible, hidden, unrelated });

        await executor.CloseAsync(TestApp);

        Assert.Equal(1, eligible.DisposeCount);
        Assert.Equal(1, hidden.DisposeCount);
        Assert.Equal(1, unrelated.DisposeCount);
    }

    [Fact]
    public async Task OpenAsync_ReturnedProcessHandle_DisposedExactlyOnce()
    {
        var process = FakeProcess.Visible();
        var runtime = new FakeProcessRuntime { StartResult = process };
        var executor = new WindowsAppExecutor(runtime);

        var opened = await executor.OpenAsync(TestApp);

        Assert.True(opened);
        Assert.Equal(1, process.DisposeCount);
    }

    [Fact]
    public async Task OpenAsync_ExceptionDetails_AreAbsentFromLogs()
    {
        const string detail = "C:\\Sensitive\\not-for-ui.exe";
        var runtime = new FakeProcessRuntime
        {
            StartException = new Win32Exception(5, detail),
        };
        var executor = new WindowsAppExecutor(runtime);
        using var listener = new CapturingTraceListener();
        Trace.Listeners.Add(listener);

        try
        {
            var opened = await executor.OpenAsync(TestApp);
            var logText = string.Join(Environment.NewLine, listener.Messages);

            Assert.False(opened);
            Assert.Contains("reason=launch_failed", logText);
            Assert.DoesNotContain(detail, logText);
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    [Fact]
    public async Task CloseAsync_FallbackExceptionDetails_AreAbsentFromLogs()
    {
        const string detail = "Sensitive Window Title C:\\Secret\\close";
        var process = FakeProcess.NoWindow(id: 101);
        var window = FakeWindow.Eligible(
            processId: 101,
            closeException: new Win32Exception(5, detail));
        var executor = NewExecutor(new[] { process }, new[] { window });
        using var listener = new CapturingTraceListener();
        Trace.Listeners.Add(listener);

        try
        {
            var outcome = await executor.CloseAsync(TestApp);
            var logText = string.Join(Environment.NewLine, listener.Messages);

            Assert.Equal(AppCloseOutcome.Failed, outcome);
            Assert.DoesNotContain(detail, logText);
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    [Fact]
    public async Task CloseAsync_NoMatchingProcess_ReturnsNotRunning()
    {
        var executor = NewExecutor();

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.NotRunning, outcome);
    }

    private static WindowsAppExecutor NewExecutor(params FakeProcess[] processes)
    {
        return NewExecutor(processes, Array.Empty<FakeWindow>());
    }

    private static WindowsAppExecutor NewExecutor(FakeProcess[] processes, FakeWindow[] windows)
    {
        var runtime = new FakeProcessRuntime();
        runtime.ProcessesByName["testapp"] = processes;
        runtime.TopLevelWindows.AddRange(windows);
        return new WindowsAppExecutor(runtime);
    }

    private sealed class FakeProcessRuntime : IWindowsProcessRuntime
    {
        public Dictionary<string, IReadOnlyList<IWindowsAppProcess>> ProcessesByName { get; } =
            new(StringComparer.OrdinalIgnoreCase);

        public List<IWindowsAppWindow> TopLevelWindows { get; } = new();

        public IWindowsAppProcess? StartResult { get; init; }

        public Exception? StartException { get; init; }

        public IWindowsAppProcess? Start(ProcessStartInfo startInfo)
        {
            if (StartException is not null)
            {
                throw StartException;
            }

            return StartResult;
        }

        public IReadOnlyList<IWindowsAppProcess> GetProcessesByName(string processName) =>
            ProcessesByName.TryGetValue(processName, out var processes)
                ? processes
                : Array.Empty<IWindowsAppProcess>();

        public IReadOnlyList<IWindowsAppWindow> GetTopLevelWindows() => TopLevelWindows;
    }

    private sealed class FakeProcess : IWindowsAppProcess
    {
        private readonly int _id;
        private readonly Action _refresh;
        private readonly Func<IntPtr> _mainWindowHandle;
        private readonly Func<bool> _closeMainWindow;

        private FakeProcess(int id, Action refresh, Func<IntPtr> mainWindowHandle, Func<bool> closeMainWindow)
        {
            _id = id;
            _refresh = refresh;
            _mainWindowHandle = mainWindowHandle;
            _closeMainWindow = closeMainWindow;
        }

        public int Id => _id;

        public int RefreshCallCount { get; private set; }

        public int CloseCallCount { get; private set; }

        public int DisposeCount { get; private set; }

        public void Refresh()
        {
            RefreshCallCount++;
            _refresh();
        }

        public IntPtr MainWindowHandle => _mainWindowHandle();

        public bool CloseMainWindow()
        {
            CloseCallCount++;
            return _closeMainWindow();
        }

        public void Dispose() => DisposeCount++;

        public static FakeProcess Visible(int id = 100, bool closeResult = true, Exception? closeException = null) =>
            new(
                id,
                () => { },
                () => new IntPtr(42),
                () =>
                {
                    if (closeException is not null)
                    {
                        throw closeException;
                    }

                    return closeResult;
                });

        public static FakeProcess NoWindow(int id = 100) =>
            new(id, () => { }, () => IntPtr.Zero, () => true);

        public static FakeProcess WithMainWindowException(Exception exception, int id = 100) =>
            new(id, () => { }, () => throw exception, () => true);

        public static FakeProcess WithRefreshException(Exception exception, int id = 100) =>
            new(id, () => throw exception, () => new IntPtr(42), () => true);
    }

    private sealed class FakeWindow : IWindowsAppWindow
    {
        private readonly Func<bool> _sendClose;

        private FakeWindow(int processId, bool isVisible, bool isOwned, Func<bool> sendClose)
        {
            ProcessId = processId;
            IsVisible = isVisible;
            IsOwned = isOwned;
            _sendClose = sendClose;
        }

        public int ProcessId { get; }

        public bool IsVisible { get; }

        public bool IsOwned { get; }

        public int SendCloseCallCount { get; private set; }

        public int DisposeCount { get; private set; }

        public bool SendClose(TimeSpan timeout)
        {
            SendCloseCallCount++;
            Assert.True(timeout <= TimeSpan.FromSeconds(2));
            return _sendClose();
        }

        public void Dispose() => DisposeCount++;

        public static FakeWindow Eligible(
            int processId,
            bool closeResult = true,
            Exception? closeException = null) =>
            new(
                processId,
                isVisible: true,
                isOwned: false,
                () =>
                {
                    if (closeException is not null)
                    {
                        throw closeException;
                    }

                    return closeResult;
                });

        public static FakeWindow Hidden(int processId) =>
            new(processId, isVisible: false, isOwned: false, () => true);

        public static FakeWindow Owned(int processId) =>
            new(processId, isVisible: true, isOwned: true, () => true);
    }

    private sealed class CapturingTraceListener : TraceListener
    {
        public List<string> Messages { get; } = new();

        public override void Write(string? message)
        {
            if (message is not null)
            {
                Messages.Add(message);
            }
        }

        public override void WriteLine(string? message)
        {
            if (message is not null)
            {
                Messages.Add(message);
            }
        }
    }
}
