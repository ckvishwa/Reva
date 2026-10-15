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
        DesktopLogger.EnsureFileLoggingInitialized();
        var configuration = DesktopConfiguration.CreateDefault();
        var tokenProvider = new LocalTokenProvider(configuration);
        var httpClient = new System.Net.Http.HttpClient
        {
            BaseAddress = configuration.CoreBaseUrl,
            // Backstop only. Every call path enforces its own shorter, per-call
            // timeout; this exists so a future method added without a CTS
            // cannot hang forever. Must stay comfortably above the STT timeout
            // (30s default, env-overridable) so it never pre-empts it. If
            // REVA_DESKTOP_STT_TIMEOUT_SECONDS is ever set above 300, this
            // backstop wins.
            Timeout = TimeSpan.FromSeconds(300),
        };
        var coreClient = new RevaCoreClient(
            httpClient, tokenProvider, configuration.RequestTimeout, configuration.SttRequestTimeout);
        var lifecycle = new RevaCoreLifecycle(
            coreClient, tokenProvider, new DeveloperModeCoreExecutableLocator(), new CoreProcessLauncher(), configuration);
        _lifecycle = lifecycle;

        var commandRouter = new CommandRouter(new WindowsAppExecutor());
        var microphoneArbiter = new MicrophoneArbiter();
        var wakeWordOptions = WakeWordRuntimeOptions.FromEnvironment();
        WakeWordProviderDiagnostics.Create(wakeWordOptions).Log();
        var assistant = new ViewModels.AssistantViewModel(
            coreClient,
            new ArbiterVoiceDevice(new WindowsVoiceDevice(), microphoneArbiter),
            lifecycle,
            commandRouter);
        IWakeWordDetector detector = wakeWordOptions.IsEnabled
            ? new PorcupineWakeWordDetector(
                wakeWordOptions.AccessKey,
                wakeWordOptions.KeywordDirectory,
                new RealFileSystemProbe(),
                wakeWordOptions.ModelManifest)
            : new NullWakeWordDetector();
        var wakeWord = new ViewModels.WakeWordCoordinator(
            detector,
            microphoneArbiter,
            new PvRecorderWakeSpeechCapture(),
            coreClient,
            assistant,
            new SystemChimePlayer(),
            lifecycle,
            new WindowsWakeWordRecoveryEvents());

        var financeApi = new Finance.FinanceApiClient(
            httpClient, tokenProvider, configuration.RequestTimeout);
        var today = new ViewModels.TodayViewModel(financeApi);
        var uiQueue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
        var voiceLoop = new Voice.VoiceLoopController(
            new Voice.VoiceSessionClient(httpClient, tokenProvider, configuration.CoreBaseUrl),
            new Voice.ArbitratedAudioCapture(
                new Voice.NAudioCapture(),
                microphoneArbiter,
                () => wakeWord.SuspendForHoldToTalkAsync(),
                () => wakeWord.ResumeAfterHoldToTalkAsync()),
            new Voice.NAudioPlayback(),
            new Voice.GlobalPushToTalkHotkey());
        var liveVoice = new ViewModels.LiveVoiceViewModel(voiceLoop, action => uiQueue.TryEnqueue(() => action()));
        var devicesApi = new Devices.DevicesApiClient(httpClient, tokenProvider, configuration.RequestTimeout);
        var actionsApi = new Actions.ActionsApi(httpClient, tokenProvider, configuration.RequestTimeout);
        var appTargets = new Actions.AppTargetStore(
            System.IO.Path.Combine(configuration.CoreDataDirectory, "app-targets.json"));
        var actionCoordinator = new Actions.ActionCoordinator(actionsApi, () => CreateExecutor(configuration, appTargets));
        voiceLoop.CoreEvent += actionCoordinator.OnCoreEvent;
        _window = new MainWindow(
            new ViewModels.ShellViewModel(lifecycle),
            assistant,
            new ViewModels.MemoryViewModel(coreClient),
            new ViewModels.NavigationViewModel(),
            new ViewModels.FinanceViewModel(financeApi),
            today,
            new ViewModels.DevicesViewModel(devicesApi, new Devices.QrCoderEncoder()),
            liveVoice,
            new ViewModels.CloudSettingsViewModel(new Settings.CloudSettingsApi(httpClient, tokenProvider, configuration.RequestTimeout)),
            new ViewModels.AvatarSettingsViewModel(new Avatar.AvatarSettingsStore(configuration.CoreDataDirectory)),
            new ViewModels.AppsViewModel(actionsApi, appTargets),
            new ViewModels.ActivityViewModel(actionsApi),
            new ViewModels.ApprovalCardViewModel(actionCoordinator, action => uiQueue.TryEnqueue(() => action())),
            wakeWord);
        _window.Activate();
        if (wakeWordOptions.IsEnabled)
        {
            await wakeWord.EnableAsync(wakeWordOptions.Configuration);
        }

        // Deliberately started after Activate(), not awaited before it: the
        // window (and its "Starting Core…" initial state) must appear
        // immediately rather than leaving Windows showing nothing while
        // Core boots — confirmed necessary during manual smoke testing of
        // the equivalent one-shot health check in Slice 3.
        await lifecycle.StartAsync();
        await today.RefreshAsync();
        ((MainWindow)_window).StartRefreshOnChanges(financeApi);
    }

    /// <summary>The executor needs the public half of the Core's grant key (written next to the
    /// database when Core starts). Without it nothing can be verified, so there is no executor and
    /// every order is reported as failed; REVA never acts on a grant it cannot check.</summary>
    private static Actions.AppActionExecutor? CreateExecutor(DesktopConfiguration configuration, Actions.AppTargetStore targets)
    {
        var keyPath = System.IO.Path.Combine(configuration.CoreDataDirectory, "grant_public_key.pem");
        try
        {
            var verifier = new Actions.GrantVerifier(System.IO.File.ReadAllText(keyPath));
            return new Actions.AppActionExecutor(verifier, targets, new Actions.SystemWindowProbe(), new Actions.SystemAppLauncher());
        }
        catch (Exception ex) when (ex is System.IO.IOException or UnauthorizedAccessException
                                       or System.Security.Cryptography.CryptographicException or ArgumentException)
        {
            DesktopLogger.Info("executor.unavailable reason=grant_key");
            return null;
        }
    }
}
