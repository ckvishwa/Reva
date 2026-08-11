using Reva.Desktop.Services;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Backs the main window's honest Core-connection status. Sourced from
/// <see cref="IRevaCoreLifecycle"/>'s state machine (probe/launch/health/
/// token/reconnect) — this class does no Core I/O of its own.
///
/// Deliberately has no WinUI/XAML type dependency (no Brush, no Color) so
/// it can be unit-tested from a plain class library test project without
/// pulling in the WinUI XAML build pipeline. Color/visual mapping lives
/// in the View (MainWindow.xaml.cs).
/// </summary>
public sealed class ShellViewModel : ObservableObject
{
    private readonly IRevaCoreLifecycle _lifecycle;

    public ShellViewModel(IRevaCoreLifecycle lifecycle)
    {
        _lifecycle = lifecycle;
        _lifecycle.StateChanged += OnLifecycleStateChanged;
    }

    public CoreLifecycleState LifecycleState => _lifecycle.State;

    public bool IsCoreConnected => _lifecycle.State == CoreLifecycleState.Connected;

    public string CoreStatusText => _lifecycle.StatusText;

    private void OnLifecycleStateChanged(object? sender, EventArgs e)
    {
        RaisePropertyChanged(nameof(LifecycleState));
        RaisePropertyChanged(nameof(IsCoreConnected));
        RaisePropertyChanged(nameof(CoreStatusText));
    }
}
