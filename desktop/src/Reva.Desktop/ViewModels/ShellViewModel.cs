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
        var result = await _coreClient.GetHealthAsync(cancellationToken).ConfigureAwait(false);
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
