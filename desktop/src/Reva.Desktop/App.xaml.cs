using Microsoft.UI.Xaml;
using Reva.Desktop.Services;

namespace Reva.Desktop;

/// <summary>
/// Composition root. Wires the (small, explicit) service layer together and
/// hands the real <see cref="IRevaCoreClient"/> to the main window. No DI
/// container — a handful of services do not need one.
/// </summary>
public partial class App : Application
{
    private Window? _window;

    public App()
    {
        InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        var configuration = DesktopConfiguration.CreateDefault();
        var tokenProvider = new LocalTokenProvider(configuration);
        var httpClient = new System.Net.Http.HttpClient
        {
            BaseAddress = configuration.CoreBaseUrl,
            Timeout = configuration.RequestTimeout,
        };
        var coreClient = new RevaCoreClient(httpClient, tokenProvider);

        _window = new MainWindow(coreClient);
        _window.Activate();
    }
}
