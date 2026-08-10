using System.Diagnostics;

namespace Reva.Desktop.Services;

/// <summary>
/// Minimal structured-ish debug logger. Defense in depth against a token
/// or Authorization header ending up in a log line: any message whose
/// text contains a sensitive keyword is withheld entirely rather than
/// partially redacted. Callers must still never pass a token/header value
/// into a log message in the first place — this is a safety net, not a
/// license to be careless.
/// </summary>
public static class DesktopLogger
{
    private static readonly string[] SensitiveKeywords =
    {
        "token", "authorization", "bearer", "password", "secret",
    };

    public static void Info(string message) => Log("INFO", message);

    public static void Warn(string message) => Log("WARN", message);

    public static void Error(string message) => Log("ERROR", message);

    private static void Log(string level, string message)
    {
        // Trace, not Debug: Debug.WriteLine is [Conditional("DEBUG")] and is
        // compiled out entirely in Release builds — Trace.WriteLine always
        // runs, which is what a real desktop app (shipped as Release) needs.
        Trace.WriteLine($"[{DateTimeOffset.UtcNow:O}] {level} {Redact(message)}");
    }

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
