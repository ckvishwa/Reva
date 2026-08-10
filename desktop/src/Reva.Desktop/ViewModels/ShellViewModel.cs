using Reva.Desktop.Services;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Backs the main window's honest Core-connection status. Sourced only
/// from a real GET /health call — never fake/simulated state.
///
/// Deliberately has no WinUI/XAML type dependency (no Brush, no Color) so
/// it can be unit-tested from a plain class library test project without
/// pulling in the WinUI XAML build pipeline. Color/visual mapping from
/// <see cref="IsCoreConnected"/> lives in the View (Views/StatusBrushConverter.cs).
/// </summary>
public sealed class ShellViewModel : ObservableObject
{
    private readonly IRevaCoreClient _coreClient;
    private bool _isCoreConnected;
    private string _coreStatusText = "Checking REVA Core...";

    public ShellViewModel(IRevaCoreClient coreClient)
    {
        _coreClient = coreClient;
    }

    public bool IsCoreConnected
    {
        get => _isCoreConnected;
        private set => SetProperty(ref _isCoreConnected, value);
    }

    public string CoreStatusText
    {
        get => _coreStatusText;
        private set => SetProperty(ref _coreStatusText, value);
    }

    public async Task RefreshCoreStatusAsync(CancellationToken cancellationToken = default)
    {
        // No ConfigureAwait(false): this method mutates UI-bound state
        // afterward (IsCoreConnected/CoreStatusText), so it must resume on
        // the calling (UI) SynchronizationContext. ConfigureAwait(false)
        // here was a real bug found via manual smoke testing — the status
        // update silently never reached the UI because it landed on a
        // thread-pool thread instead of the UI thread; no exception, no
        // crash, just a status stuck on its initial value forever.
        var result = await _coreClient.GetHealthAsync(cancellationToken);
        if (result.IsSuccess)
        {
            IsCoreConnected = true;
            CoreStatusText = "Core Connected";
        }
        else
        {
            IsCoreConnected = false;
            CoreStatusText = "Core Unavailable";
        }
    }
}
