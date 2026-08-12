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
    private RevaCoreLifecycle? _lifecycle;

    public App()
    {
        InitializeComponent();
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        var configuration = DesktopConfiguration.CreateDefault();
        var tokenProvider = new LocalTokenProvider(configuration);
        var httpClient = new System.Net.Http.HttpClient
        {
            BaseAddress = configuration.CoreBaseUrl,
            Timeout = configuration.RequestTimeout,
        };
        var coreClient = new RevaCoreClient(httpClient, tokenProvider);
        var lifecycle = new RevaCoreLifecycle(
            coreClient, tokenProvider, new DeveloperModeCoreExecutableLocator(), new CoreProcessLauncher(), configuration);
        _lifecycle = lifecycle;

        _window = new MainWindow(coreClient, lifecycle, new WindowsVoiceDevice());
        _window.Activate();

        // Deliberately started after Activate(), not awaited before it: the
        // window (and its "Starting Core…" initial state) must appear
        // immediately rather than leaving Windows showing nothing while
        // Core boots — confirmed necessary during manual smoke testing of
        // the equivalent one-shot health check in Slice 3.
        await lifecycle.StartAsync();
    }
}
