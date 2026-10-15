using System.Text.Json;

namespace Reva.Desktop.Actions;

/// <summary>What the Core hands the app to carry out: the signed grant and exactly what to do.</summary>
public sealed record ActionOrder(
    Grant Grant,
    string Signature,
    string Capability,
    JsonElement Args,
    string TargetDeviceId);

/// <summary>Proof of what happened, in the shape the Core's registry expects for the capability:
/// "process_started" (<c>pid:N window:0xH</c>) or "process_exited" (<c>pids:N,M exited</c>).</summary>
public sealed record ActionEvidence(string Kind, string Reference);

/// <summary>What an executor tells the Core. Only the Core turns this into words.</summary>
public sealed record ActionReport(string Status, ActionEvidence? Evidence, string Note)
{
    public const string Verified = "verified";
    public const string Unknown = "unknown";
    public const string Failed = "failed";
}

/// <summary>A visible, titled top-level window.</summary>
public readonly record struct TopWindow(IntPtr Handle, int ProcessId, string ProcessName);

public interface IWindowProbe
{
    IReadOnlyList<TopWindow> VisibleWindows();

    IntPtr Foreground();
}

/// <summary>What starting and stopping a program needs. <see cref="Start"/> only ever receives a
/// <see cref="LaunchTarget"/> built from the fixed built-ins or from the owner's own approved
/// apps; it never receives text from a request.</summary>
public interface IAppLauncher
{
    /// <summary>Starts the target; the process id when the shell reports one, otherwise null.</summary>
    int? Start(LaunchTarget target);

    IReadOnlyList<int> RunningProcessIds(IReadOnlyList<string> processNames);

    /// <summary>Asks each window to close (never kills). True if anything was asked.</summary>
    bool RequestClose(IReadOnlyList<string> processNames);
}

public sealed record LaunchTarget(
    string Key,
    string DisplayName,
    string OpenTarget,
    IReadOnlyList<string> ProcessNames);

public interface IAppTargets
{
    LaunchTarget? Find(string key);

    /// <summary>Remembers the process name seen for an approved app, so it can be closed later.</summary>
    void Learn(string key, string processName);
}
