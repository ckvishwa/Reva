namespace Reva.Desktop.Tests.Unit;

// Slice 8A follow-up: Core stop must happen before wake-word disposal, not
// after. Reported gap — MainWindow_Closed previously awaited wake-word
// disposal first, leaving the owned Core process alive with no visible UI
// for however long that takes, exposing exactly the orphan window the
// shutdown fix was meant to close. Ordered event log, not timing — the
// two operations here are instant no-ops; only their relative order matters.
public class MainWindowShutdownOrderTests
{
    [Fact]
    public async Task RunShutdownSequenceAsync_StopsCoreBeforeDisposingWakeWord()
    {
        var events = new List<string>();
        Func<Task> stopCoreAsync = () =>
        {
            events.Add("core-stop");
            return Task.CompletedTask;
        };
        Func<Task> disposeWakeWordAsync = () =>
        {
            events.Add("wakeword-dispose");
            return Task.CompletedTask;
        };

        await Reva.Desktop.MainWindow.RunShutdownSequenceAsync(stopCoreAsync, disposeWakeWordAsync);

        Assert.Equal(new[] { "core-stop", "wakeword-dispose" }, events);
    }

    [Fact]
    public async Task RunShutdownSequenceAsync_AwaitsCoreStop_BeforeStartingWakeWordDispose()
    {
        // Real async scheduling: proves stopCoreAsync is actually awaited to
        // completion (not just invoked) before disposeWakeWordAsync starts —
        // a fire-and-forget stopCoreAsync().  wouldn't be caught by the
        // simple ordering test above if disposeWakeWordAsync happened to run
        // synchronously first.
        var coreStopGate = new TaskCompletionSource();
        var events = new List<string>();
        Func<Task> stopCoreAsync = async () =>
        {
            events.Add("core-stop-begin");
            await coreStopGate.Task;
            events.Add("core-stop-end");
        };
        Func<Task> disposeWakeWordAsync = () =>
        {
            events.Add("wakeword-dispose");
            return Task.CompletedTask;
        };

        var sequenceTask = Reva.Desktop.MainWindow.RunShutdownSequenceAsync(stopCoreAsync, disposeWakeWordAsync);

        var deadline = DateTime.UtcNow.AddMilliseconds(300);
        while (events.Count == 0 && DateTime.UtcNow < deadline)
        {
            await Task.Yield();
        }

        Assert.Equal(new[] { "core-stop-begin" }, events);

        coreStopGate.SetResult();
        await sequenceTask;

        Assert.Equal(new[] { "core-stop-begin", "core-stop-end", "wakeword-dispose" }, events);
    }

    [Fact]
    public async Task CompleteShutdownAsync_ExitsOnlyAfterCleanupFinishes()
    {
        var events = new List<string>();
        var coreStopGate = new TaskCompletionSource();
        Func<Task> stopCoreAsync = async () =>
        {
            events.Add("core-stop-begin");
            await coreStopGate.Task;
            events.Add("core-stop-end");
        };
        Func<Task> disposeWakeWordAsync = () =>
        {
            events.Add("wakeword-dispose");
            return Task.CompletedTask;
        };

        var sequenceTask = Reva.Desktop.MainWindow.CompleteShutdownAsync(
            stopCoreAsync,
            disposeWakeWordAsync,
            () => events.Add("process-exit"));

        coreStopGate.SetResult();
        await sequenceTask;

        Assert.Equal(
            new[] { "core-stop-begin", "core-stop-end", "wakeword-dispose", "process-exit" },
            events);
    }

    [Fact]
    public async Task CompleteShutdownAsync_DoesNotExitWhenCoreStopThrows()
    {
        var exited = false;

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            Reva.Desktop.MainWindow.CompleteShutdownAsync(
                () => throw new InvalidOperationException("stop failed"),
                () => Task.CompletedTask,
                () => exited = true));

        Assert.False(exited);
    }
}
