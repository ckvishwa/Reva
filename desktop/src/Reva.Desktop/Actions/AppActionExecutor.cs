using Reva.Desktop.Services;
using System.Text.Json;

namespace Reva.Desktop.Actions;

/// <summary>The Windows executor for <c>windows.app.open</c> and <c>windows.app.close</c>
/// (ARD-100 section 5, AR-WIN-005..009).
///
/// It acts on nothing until the grant verifies: signature, expiry, capability, canonical arguments,
/// device, owner and idempotency key. It then reports what it observed, never what it hoped:
///
///  * open is "verified" only when a visible top-level window of that app appeared (or the app's
///    window came to the front) after the launch; a process with no window in time is "unknown";
///  * close is "verified" only when every process of the app is gone; a window that is still there
///    (it may be asking to save) is "unknown".
///
/// The Core, not this class, decides what REVA says.</summary>
public sealed class AppActionExecutor
{
    public const string OpenCapability = "windows.app.open";
    public const string CloseCapability = "windows.app.close";
    private const int MaxEvidenceProcesses = 16;

    private readonly GrantVerifier _verifier;
    private readonly IAppTargets _targets;
    private readonly IWindowProbe _windows;
    private readonly IAppLauncher _launcher;
    private readonly TimeProvider _time;
    private readonly string _deviceId;
    private readonly string _actor;
    private readonly TimeSpan _windowTimeout;
    private readonly TimeSpan _exitTimeout;
    private readonly TimeSpan _poll;

    public AppActionExecutor(
        GrantVerifier verifier,
        IAppTargets targets,
        IWindowProbe windows,
        IAppLauncher launcher,
        TimeProvider? time = null,
        string deviceId = "local",
        string actor = "owner",
        TimeSpan? windowTimeout = null,
        TimeSpan? exitTimeout = null,
        TimeSpan? poll = null)
    {
        _verifier = verifier;
        _targets = targets;
        _windows = windows;
        _launcher = launcher;
        _time = time ?? TimeProvider.System;
        _deviceId = deviceId;
        _actor = actor;
        _windowTimeout = windowTimeout ?? TimeSpan.FromSeconds(8);
        _exitTimeout = exitTimeout ?? TimeSpan.FromSeconds(5);
        _poll = poll ?? TimeSpan.FromMilliseconds(150);
    }

    public async Task<ActionReport> ExecuteAsync(ActionOrder order, CancellationToken cancellationToken = default)
    {
        GrantCheck check;
        try
        {
            check = _verifier.Verify(
                order.Grant,
                order.Signature,
                _time.GetUtcNow(),
                order.Capability,
                GrantVerifier.ArgsHash(order.Args),
                _deviceId,
                _actor);
        }
        catch (FormatException)
        {
            check = GrantCheck.Fail("MALFORMED");
        }

        if (!check.Ok)
        {
            DesktopLogger.Info($"executor.refused reason={check.Reason} capability={order.Capability}");
            return new ActionReport(ActionReport.Failed, null, $"grant refused: {check.Reason}");
        }

        if (order.Args.ValueKind != JsonValueKind.Object
            || !order.Args.TryGetProperty("app_key", out var keyElement)
            || keyElement.ValueKind != JsonValueKind.String
            || _targets.Find(keyElement.GetString()!) is not { } target)
        {
            return new ActionReport(ActionReport.Failed, null, "unknown app");
        }

        return order.Capability switch
        {
            OpenCapability => await OpenAsync(target, cancellationToken).ConfigureAwait(false),
            CloseCapability => await CloseAsync(target, cancellationToken).ConfigureAwait(false),
            _ => new ActionReport(ActionReport.Failed, null, "unsupported capability"),
        };
    }

    private async Task<ActionReport> OpenAsync(LaunchTarget target, CancellationToken cancellationToken)
    {
        var before = _windows.VisibleWindows().Select(w => w.Handle).ToHashSet();
        int? startedPid;
        try
        {
            startedPid = _launcher.Start(target);
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidOperationException or FileNotFoundException)
        {
            DesktopLogger.Info($"executor.launch_failed app={target.Key}");
            return new ActionReport(ActionReport.Failed, null, "launch failed");
        }

        var deadline = _time.GetUtcNow() + _windowTimeout;
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var found = FindWindow(target, before);
            if (found is { } window)
            {
                if (target.ProcessNames.Count == 0)
                {
                    _targets.Learn(target.Key, window.ProcessName);
                }

                return new ActionReport(
                    ActionReport.Verified,
                    new ActionEvidence("process_started", $"pid:{window.ProcessId} window:0x{window.Handle.ToInt64():X}"),
                    "window seen");
            }

            if (_time.GetUtcNow() >= deadline)
            {
                break;
            }

            await Task.Delay(_poll, _time, cancellationToken).ConfigureAwait(false);
        }

        // No window in time. If something of the app is running it started but we cannot confirm it;
        // if nothing is running at all, the launch did not work.
        var running = _launcher.RunningProcessIds(target.ProcessNames);
        var pid = running.Count > 0 ? running[0] : startedPid;
        return pid is null
            ? new ActionReport(ActionReport.Failed, null, "nothing started")
            : new ActionReport(ActionReport.Unknown, new ActionEvidence("process_started", $"pid:{pid} no_window"), "no window");
    }

    private static string Squash(string text) =>
        new(text.Where(char.IsLetterOrDigit).Select(char.ToLowerInvariant).ToArray());

    private TopWindow? FindWindow(LaunchTarget target, HashSet<IntPtr> before)
    {
        var names = target.ProcessNames;
        var squashedKey = Squash(target.Key);
        var squashedName = Squash(target.DisplayName);

        // A known process name must match. An approved app we have not opened before has none yet, so
        // the new window must look like it: its process or its title carries the app's name or key.
        bool Matches(TopWindow w) =>
            names.Count > 0
                ? names.Contains(w.ProcessName, StringComparer.OrdinalIgnoreCase)
                : Squash(w.ProcessName).Contains(squashedKey, StringComparison.Ordinal)
                  || Squash(w.Title).Contains(squashedName, StringComparison.Ordinal)
                  || Squash(w.Title).Contains(squashedKey, StringComparison.Ordinal);

        var windows = _windows.VisibleWindows();
        foreach (var window in windows)
        {
            if (!before.Contains(window.Handle) && Matches(window))
            {
                return window;
            }
        }

        // The app was already open and launching it brought its window to the front.
        var foreground = _windows.Foreground();
        foreach (var window in windows)
        {
            if (window.Handle == foreground && names.Count > 0 && Matches(window))
            {
                return window;
            }
        }

        return null;
    }

    private async Task<ActionReport> CloseAsync(LaunchTarget target, CancellationToken cancellationToken)
    {
        if (target.ProcessNames.Count == 0)
        {
            return new ActionReport(ActionReport.Failed, null, "close needs the app to have been opened by REVA first");
        }

        var before = _launcher.RunningProcessIds(target.ProcessNames);
        if (before.Count == 0)
        {
            return new ActionReport(ActionReport.Failed, null, "not running");
        }

        _launcher.RequestClose(target.ProcessNames);
        var deadline = _time.GetUtcNow() + _exitTimeout;
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (_launcher.RunningProcessIds(target.ProcessNames).Count == 0)
            {
                var ids = string.Join(',', before.Take(MaxEvidenceProcesses));
                var noun = before.Count == 1 ? "pid" : "pids";
                return new ActionReport(
                    ActionReport.Verified,
                    new ActionEvidence("process_exited", $"{noun}:{ids} exited"),
                    "process gone");
            }

            if (_time.GetUtcNow() >= deadline)
            {
                break;
            }

            await Task.Delay(_poll, _time, cancellationToken).ConfigureAwait(false);
        }

        return new ActionReport(ActionReport.Unknown, null, "still running");
    }
}
