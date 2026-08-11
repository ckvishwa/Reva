namespace Reva.Desktop.Services;

/// <summary>A launched Core process. Never exposes the token or command
/// line — only exit-state, which the lifecycle needs for reconnect decisions.</summary>
public interface ICoreProcessHandle : IDisposable
{
    bool HasExited { get; }

    int? ExitCode { get; }
}
