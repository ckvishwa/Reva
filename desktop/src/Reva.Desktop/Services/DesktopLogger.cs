using System.Diagnostics;

namespace Reva.Desktop.Services;

/// <summary>
/// Minimal structured-ish debug logger. Defense in depth against a token
/// or Authorization header ending up in a log line: any message whose
/// text contains a sensitive keyword is withheld entirely rather than
/// partially redacted. Callers must still never pass a token/header value
/// into a log message in the first place — this is a safety net, not a
/// license to be careless.
///
/// Every line carries a thread id and, when the caller supplies one, an
/// operation id — added for Slice 8A so overlapping Core-lifecycle
/// operations (a startup and a recovery racing, two recoveries racing)
/// are visible as overlap in the log instead of an unexplained flap.
/// </summary>
public static class DesktopLogger
{
    private static readonly string[] SensitiveKeywords =
    {
        "token", "authorization", "bearer", "password", "secret",
    };

    private static readonly object InitLock = new();
    private static bool _fileLoggingInitialized;

    public static void Info(string message, string? operationId = null) => Log("INFO", message, operationId);

    public static void Warn(string message, string? operationId = null) => Log("WARN", message, operationId);

    public static void Error(string message, string? operationId = null) => Log("ERROR", message, operationId);

    /// <summary>
    /// Attaches a file-backed <see cref="TraceListener"/> under
    /// <see cref="RuntimePaths.GetDefaultLogDirectory"/> so lifecycle log
    /// lines survive past process exit for post-hoc reading during the
    /// physical acceptance test — without this, Release-mode Trace.WriteLine
    /// has no durable sink (only OutputDebugString, visible solely to an
    /// attached debugger). Idempotent: safe to call more than once, from
    /// more than one place, without attaching duplicate listeners.
    /// </summary>
    public static void EnsureFileLoggingInitialized()
    {
        if (_fileLoggingInitialized)
        {
            return;
        }

        lock (InitLock)
        {
            if (_fileLoggingInitialized)
            {
                return;
            }

            var logDirectory = RuntimePaths.GetDefaultLogDirectory();
            Directory.CreateDirectory(logDirectory);
            var logFile = Path.Combine(logDirectory, "lifecycle.log");
            Trace.Listeners.Add(new TextWriterTraceListener(logFile));
            // Immediate flush: the physical test reads this file while the
            // process it's diagnosing may crash or be force-killed, and a
            // buffered write lost with the process would defeat the point.
            Trace.AutoFlush = true;
            _fileLoggingInitialized = true;
        }
    }

    private static void Log(string level, string message, string? operationId)
    {
        // Trace, not Debug: Debug.WriteLine is [Conditional("DEBUG")] and is
        // compiled out entirely in Release builds — Trace.WriteLine always
        // runs, which is what a real desktop app (shipped as Release) needs.
        Trace.WriteLine(FormatLine(level, message, operationId));
    }

    internal static string FormatLine(string level, string message, string? operationId) =>
        $"[{DateTimeOffset.UtcNow:O}] [tid={Environment.CurrentManagedThreadId}] " +
        $"[op={operationId ?? "-"}] {level} {Redact(message)}";

    private static string Redact(string message)
    {
        foreach (var keyword in SensitiveKeywords)
        {
            if (message.Contains(keyword, StringComparison.OrdinalIgnoreCase))
            {
                return "[message withheld: potentially contains sensitive data]";
            }
        }

        return message;
    }
}
