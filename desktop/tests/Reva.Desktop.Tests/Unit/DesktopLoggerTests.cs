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

    [Fact]
    public void Info_IncludesManagedThreadId()
    {
        var listener = new CapturingListener();
        Trace.Listeners.Add(listener);
        try
        {
            DesktopLogger.Info("thread id check");

            Assert.Contains(listener.Lines, l => l.Contains($"tid={Environment.CurrentManagedThreadId}"));
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    [Fact]
    public void Info_IncludesOperationId_WhenProvided()
    {
        var listener = new CapturingListener();
        Trace.Listeners.Add(listener);
        try
        {
            DesktopLogger.Info("op id check", operationId: "op-42");

            Assert.Contains(listener.Lines, l => l.Contains("op=op-42"));
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    [Fact]
    public void Info_UsesPlaceholderOperationId_WhenNotProvided()
    {
        var listener = new CapturingListener();
        Trace.Listeners.Add(listener);
        try
        {
            DesktopLogger.Info("no op id");

            Assert.Contains(listener.Lines, l => l.Contains("[op=-]"));
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    [Fact]
    public void FormatLine_RedactsSensitiveMessage_BeforeInsertingIntoTemplate()
    {
        var line = DesktopLogger.FormatLine("WARN", "Authorization: Bearer secretvalue", operationId: "op-1");

        Assert.Contains("withheld", line);
        Assert.DoesNotContain("secretvalue", line);
        Assert.Contains("op=op-1", line);
    }

    [Fact]
    public void EnsureFileLoggingInitialized_CreatesLogDirectory_AndIsIdempotent()
    {
        DesktopLogger.EnsureFileLoggingInitialized();
        DesktopLogger.EnsureFileLoggingInitialized();

        Assert.True(Directory.Exists(RuntimePaths.GetDefaultLogDirectory()));
    }
}
