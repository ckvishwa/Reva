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
        var first = FakeProcess.WithMainWindowException(new InvalidOperationException("already gone one"));
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
        var exitedDuringInspection = FakeProcess.WithMainWindowException(new InvalidOperationException("exited"));
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
    public async Task CloseAsync_NoMatchingProcess_ReturnsNotRunning()
    {
        var executor = NewExecutor();

        var outcome = await executor.CloseAsync(TestApp);

        Assert.Equal(AppCloseOutcome.NotRunning, outcome);
    }

    private static WindowsAppExecutor NewExecutor(params FakeProcess[] processes)
    {
        var runtime = new FakeProcessRuntime();
        runtime.ProcessesByName["testapp"] = processes;
        return new WindowsAppExecutor(runtime);
    }

    private sealed class FakeProcessRuntime : IWindowsProcessRuntime
    {
        public Dictionary<string, IReadOnlyList<IWindowsAppProcess>> ProcessesByName { get; } =
            new(StringComparer.OrdinalIgnoreCase);

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
    }

    private sealed class FakeProcess : IWindowsAppProcess
    {
        private readonly Func<IntPtr> _mainWindowHandle;
        private readonly Func<bool> _closeMainWindow;

        private FakeProcess(Func<IntPtr> mainWindowHandle, Func<bool> closeMainWindow)
        {
            _mainWindowHandle = mainWindowHandle;
            _closeMainWindow = closeMainWindow;
        }

        public int CloseCallCount { get; private set; }

        public int DisposeCount { get; private set; }

        public IntPtr MainWindowHandle => _mainWindowHandle();

        public bool CloseMainWindow()
        {
            CloseCallCount++;
            return _closeMainWindow();
        }

        public void Dispose() => DisposeCount++;

        public static FakeProcess Visible(bool closeResult = true, Exception? closeException = null) =>
            new(
                () => new IntPtr(42),
                () =>
                {
                    if (closeException is not null)
                    {
                        throw closeException;
                    }

                    return closeResult;
                });

        public static FakeProcess NoWindow() => new(() => IntPtr.Zero, () => true);

        public static FakeProcess WithMainWindowException(Exception exception) =>
            new(() => throw exception, () => true);
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
