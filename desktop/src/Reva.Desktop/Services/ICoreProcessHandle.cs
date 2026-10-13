namespace Reva.Desktop.Services;

/// <summary>A launched Core process. Never exposes the token or command
/// line — only exit-state, which the lifecycle needs for reconnect decisions.</summary>
public interface ICoreProcessHandle : IDisposable
{
    bool HasExited { get; }

    int? ExitCode { get; }

    /// <summary>Process id, for diagnostics only — never logged alongside
    /// any sensitive data.</summary>
    int? Pid { get; }

    /// <summary>Terminates this process. Callers must only invoke this on a
    /// handle they own (one this instance itself launched) — never on a
    /// handle representing an externally-started Core.</summary>
    void Stop();
}
