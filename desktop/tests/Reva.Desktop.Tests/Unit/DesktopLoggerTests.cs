using System.Collections.Concurrent;
using System.Diagnostics;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class DesktopLoggerTests
{
    private sealed class CapturingListener : TraceListener
    {
        public readonly ConcurrentQueue<string> Lines = new();
        public override void Write(string? message) { }
        public override void WriteLine(string? message)
        {
            if (message is not null) Lines.Enqueue(message);
        }
    }

    [Fact]
    public void Info_WithdrawsMessage_WhenItMentionsToken()
    {
        var listener = new CapturingListener();
        Trace.Listeners.Add(listener);
        try
        {
            DesktopLogger.Info("Authorization: Bearer abc123-real-token-value");

            Assert.Contains(listener.Lines, l => l.Contains("withheld"));
            Assert.DoesNotContain(listener.Lines, l => l.Contains("abc123-real-token-value"));
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    [Fact]
    public void Info_LogsSafeMessage_Normally()
    {
        var listener = new CapturingListener();
        Trace.Listeners.Add(listener);
        try
        {
            DesktopLogger.Info("Core status refreshed");

            Assert.Contains(listener.Lines, l => l.Contains("Core status refreshed"));
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }
}
