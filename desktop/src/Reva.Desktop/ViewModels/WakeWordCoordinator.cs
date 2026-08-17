using Microsoft.UI.Dispatching;
using Reva.Desktop.Services;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

public sealed class WakeWordCoordinator : ObservableObject, IAsyncDisposable
{
    private static readonly TimeSpan InitialRecoveryDelay = TimeSpan.FromSeconds(1);
    private static readonly TimeSpan MaxRecoveryDelay = TimeSpan.FromSeconds(30);

    private readonly IWakeWordDetector _detector;
    private readonly IMicrophoneArbiter _arbiter;
    private readonly IWakeSpeechCapture _speechCapture;
    private readonly IRevaCoreClient _coreClient;
    private readonly IComposerSink _composerSink;
    private readonly IChimePlayer _chimePlayer;
    private readonly IRevaCoreLifecycle? _coreLifecycle;
    private readonly IWakeWordRecoveryEvents? _recoveryEvents;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly DispatcherQueue? _dispatcherQueue = TryGetDispatcherQueue();
    private readonly object _gate = new();
    private WakeWordConfiguration? _configuration;
    private IMicrophoneLease? _lease;
    private CancellationTokenSource? _recoveryCancellation;
    private Task _turnTask = Task.CompletedTask;
    private Task _recoveryTask = Task.CompletedTask;
    private WakeWordUiState _state = WakeWordUiState.Disabled;
    private string _statusText = WakeWordUiStateText.For(WakeWordUiState.Disabled);
    private string? _errorMessage;
    private bool _isEnabled;
    private bool _turnInProgress;
    private int _recoveryAttempts;

    public WakeWordCoordinator(
        IWakeWordDetector detector,
        IMicrophoneArbiter arbiter,
        IWakeSpeechCapture speechCapture,
        IRevaCoreClient coreClient,
        IComposerSink composerSink,
        IChimePlayer chimePlayer,
        IRevaCoreLifecycle? coreLifecycle = null,
        IWakeWordRecoveryEvents? recoveryEvents = null,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _detector = detector;
        _arbiter = arbiter;
        _speechCapture = speechCapture;
        _coreClient = coreClient;
        _composerSink = composerSink;
        _chimePlayer = chimePlayer;
        _coreLifecycle = coreLifecycle;
        _recoveryEvents = recoveryEvents;
        _delay = delay ?? ((span, token) => Task.Delay(span, token));
        _detector.Detected += OnDetected;
        _detector.Faulted += OnDetectorFaulted;
        if (_coreLifecycle is not null)
        {
            _coreLifecycle.StateChanged += OnCoreLifecycleStateChanged;
        }

        if (_recoveryEvents is not null)
        {
            _recoveryEvents.RecoveryRequested += OnRecoveryRequested;
        }
    }

    public WakeWordUiState State
    {
        get => _state;
        private set
        {
            if (SetProperty(ref _state, value))
            {
                StatusText = WakeWordUiStateText.For(value);
            }
        }
    }

    public string StatusText
    {
        get => _statusText;
        private set => SetProperty(ref _statusText, value);
    }

    public string? ErrorMessage
    {
        get => _errorMessage;
        private set => SetProperty(ref _errorMessage, value);
    }

    public bool IsEnabled
    {
        get => _isEnabled;
        private set => SetProperty(ref _isEnabled, value);
    }

    public async Task EnableAsync(
        WakeWordConfiguration configuration,
        CancellationToken cancellationToken = default)
    {
        _configuration = configuration;
        IsEnabled = true;
        _recoveryEvents?.Start();
        CancelRecovery();
        SetState(WakeWordUiState.Initializing);
        await StartDetectorAsync(scheduleRecovery: true, cancellationToken).ConfigureAwait(false);
    }

    public async Task DisableAsync(CancellationToken cancellationToken = default)
    {
        IsEnabled = false;
        CancelRecovery();
        _recoveryEvents?.Stop();
        await StopAndReleaseAsync(cancellationToken).ConfigureAwait(false);
        SetState(WakeWordUiState.Disabled);
    }

    public async Task SuspendForHoldToTalkAsync(CancellationToken cancellationToken = default)
    {
        CancelRecovery();
        await StopAndReleaseAsync(cancellationToken).ConfigureAwait(false);
        SetState(WakeWordUiState.Disabled);
    }

    public async Task ResumeAfterHoldToTalkAsync(CancellationToken cancellationToken = default)
    {
        if (!IsEnabled || _configuration is null)
        {
            return;
        }

        SetState(WakeWordUiState.Recovering);
        await StartDetectorAsync(scheduleRecovery: true, cancellationToken).ConfigureAwait(false);
    }

    public Task RecoverAsync(WakeWordRecoveryReason reason, CancellationToken cancellationToken = default)
    {
        if (!IsEnabled || _configuration is null)
        {
            return Task.CompletedTask;
        }

        return ScheduleRecoveryAsync(cancellationToken);
    }

    internal Task WaitForTurnAsync() => _turnTask;

    internal Task WaitForRecoveryAsync()
    {
        lock (_gate)
        {
            return _recoveryTask;
        }
    }

    private async Task StartDetectorAsync(bool scheduleRecovery, CancellationToken cancellationToken)
    {
        if (_configuration is null)
        {
            SetUnavailable("Wake word is not configured.");
            return;
        }

        _lease ??= await _arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord, cancellationToken)
            .ConfigureAwait(false);
        if (_lease is null)
        {
            SetUnavailable("Microphone is unavailable.");
            if (scheduleRecovery)
            {
                _ = ScheduleRecoveryAsync(CancellationToken.None);
            }

            return;
        }

        try
        {
            await _detector.StartAsync(_configuration, _lease, cancellationToken).ConfigureAwait(false);
            _recoveryAttempts = 0;
            ErrorMessage = null;
            SetState(WakeWordUiState.Listening);
        }
        catch (WakeWordConfigurationException ex) when (!cancellationToken.IsCancellationRequested)
        {
            await ReleaseLeaseAsync().ConfigureAwait(false);
            SetUnavailable(ex.Message);
        }
        catch (Exception) when (!cancellationToken.IsCancellationRequested)
        {
            await ReleaseLeaseAsync().ConfigureAwait(false);
            SetUnavailable("Wake word is unavailable.");
            if (scheduleRecovery)
            {
                _ = ScheduleRecoveryAsync(CancellationToken.None);
            }
        }
    }

    private void OnDetected(object? sender, WakeWordDetection detection)
    {
        lock (_gate)
        {
            if (_turnInProgress || State != WakeWordUiState.Listening)
            {
                return;
            }

            _turnInProgress = true;
            SetState(WakeWordUiState.Detected);
            _turnTask = RunTurnAsync(detection, CancellationToken.None);
        }
    }

    private async Task RunTurnAsync(WakeWordDetection detection, CancellationToken cancellationToken)
    {
        DesktopLogger.Info($"wakeword.detected phrase={detection.Phrase}");
        try
        {
            await _detector.StopAsync(cancellationToken).ConfigureAwait(false);
            await _chimePlayer.PlayAsync(cancellationToken).ConfigureAwait(false);
            SetState(WakeWordUiState.Capturing);
            var audio = await _speechCapture.CaptureAsync(cancellationToken).ConfigureAwait(false);

            if (audio.Length == 0 || !WavAudio.TryGetDurationMs(audio, out var durationMs) || durationMs < 250)
            {
                ErrorMessage = "No speech was recognized. Try again.";
                SetState(WakeWordUiState.Recovering);
                return;
            }

            var transcription = await _coreClient.TranscribeSpeechAsync(audio, cancellationToken).ConfigureAwait(false);
            if (!transcription.IsSuccess)
            {
                ErrorMessage = transcription.Error!.SafeMessage;
                SetState(WakeWordUiState.Recovering);
                return;
            }

            var text = StripWakePhrase(transcription.Value!.Text?.Trim() ?? string.Empty, detection.Phrase);
            if (text.Length == 0)
            {
                ErrorMessage = "No speech was recognized. Try again.";
                SetState(WakeWordUiState.Recovering);
                return;
            }

            await _composerSink.SubmitTranscriptionAsync(text, cancellationToken).ConfigureAwait(false);
            ErrorMessage = null;
            SetState(WakeWordUiState.Recovering);
        }
        catch (OperationCanceledException)
        {
            SetState(WakeWordUiState.Recovering);
        }
        catch (Exception)
        {
            ErrorMessage = "Wake word capture failed. Try again.";
            SetState(WakeWordUiState.Recovering);
        }
        finally
        {
            lock (_gate)
            {
                _turnInProgress = false;
            }

            if (IsEnabled && _configuration is not null)
            {
                await StartDetectorAsync(scheduleRecovery: true, CancellationToken.None).ConfigureAwait(false);
            }
        }
    }

    private void OnDetectorFaulted(object? sender, WakeWordFailure failure)
    {
        if (failure.Kind == WakeWordFailureKind.DetectorException)
        {
            _ = RecoverAsync(WakeWordRecoveryReason.DetectorException);
        }
    }

    private void OnRecoveryRequested(object? sender, WakeWordRecoveryReason reason) =>
        _ = RecoverAsync(reason);

    private void OnCoreLifecycleStateChanged(object? sender, EventArgs e)
    {
        if (_coreLifecycle?.State == CoreLifecycleState.Connected
            && IsEnabled
            && _configuration is not null
            && State == WakeWordUiState.Unavailable)
        {
            _ = ScheduleRecoveryAsync(CancellationToken.None);
        }
    }

    private Task ScheduleRecoveryAsync(CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            if (!_recoveryTask.IsCompleted)
            {
                return _recoveryTask;
            }

            _recoveryCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            _recoveryTask = RecoverAfterBackoffAsync(_recoveryCancellation.Token);
            return _recoveryTask;
        }
    }

    private async Task RecoverAfterBackoffAsync(CancellationToken cancellationToken)
    {
        SetState(WakeWordUiState.Recovering);
        var delay = NextRecoveryDelay();
        try
        {
            await StopAndReleaseAsync(cancellationToken).ConfigureAwait(false);
            await _delay(delay, cancellationToken).ConfigureAwait(false);
            if (!IsEnabled || _configuration is null || cancellationToken.IsCancellationRequested)
            {
                return;
            }

            await StartDetectorAsync(scheduleRecovery: true, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private TimeSpan NextRecoveryDelay()
    {
        var seconds = Math.Min(
            MaxRecoveryDelay.TotalSeconds,
            InitialRecoveryDelay.TotalSeconds * Math.Pow(2, _recoveryAttempts));
        _recoveryAttempts++;
        return TimeSpan.FromSeconds(seconds);
    }

    private void CancelRecovery()
    {
        _recoveryCancellation?.Cancel();
        _recoveryCancellation?.Dispose();
        _recoveryCancellation = null;
    }

    private void SetUnavailable(string safeMessage)
    {
        ErrorMessage = safeMessage;
        SetState(WakeWordUiState.Unavailable);
    }

    private static string StripWakePhrase(string text, WakePhrase phrase)
    {
        var phraseText = WakePhraseDefaults.DisplayName(phrase);
        return text.StartsWith(phraseText, StringComparison.OrdinalIgnoreCase)
            ? text[phraseText.Length..].TrimStart(' ', ',', '.', ':', ';', '-', '\u2014')
            : text;
    }

    private async Task StopAndReleaseAsync(CancellationToken cancellationToken)
    {
        try
        {
            await _detector.StopAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            await ReleaseLeaseAsync().ConfigureAwait(false);
        }
    }

    private async Task ReleaseLeaseAsync()
    {
        if (_lease is not null)
        {
            await _lease.DisposeAsync().ConfigureAwait(false);
            _lease = null;
        }
    }

    private void SetState(WakeWordUiState state)
    {
        DesktopLogger.Info($"wakeword.state={state}");
        if (_dispatcherQueue is not null && !_dispatcherQueue.HasThreadAccess)
        {
            _dispatcherQueue.TryEnqueue(() => State = state);
            return;
        }

        State = state;
    }

    private static DispatcherQueue? TryGetDispatcherQueue()
    {
        try
        {
            return DispatcherQueue.GetForCurrentThread();
        }
        catch
        {
            return null;
        }
    }

    public async ValueTask DisposeAsync()
    {
        _detector.Detected -= OnDetected;
        _detector.Faulted -= OnDetectorFaulted;
        if (_coreLifecycle is not null)
        {
            _coreLifecycle.StateChanged -= OnCoreLifecycleStateChanged;
        }

        if (_recoveryEvents is not null)
        {
            _recoveryEvents.RecoveryRequested -= OnRecoveryRequested;
            _recoveryEvents.Dispose();
        }

        CancelRecovery();
        await StopAndReleaseAsync(CancellationToken.None).ConfigureAwait(false);
        await _detector.DisposeAsync().ConfigureAwait(false);
    }
}
