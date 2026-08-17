using Microsoft.UI.Dispatching;
using Reva.Desktop.Services;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

public sealed class WakeWordCoordinator : ObservableObject, IAsyncDisposable
{
    private readonly IWakeWordDetector _detector;
    private readonly IMicrophoneArbiter _arbiter;
    private readonly IVoiceDevice _voiceDevice;
    private readonly IRevaCoreClient _coreClient;
    private readonly IComposerSink _composerSink;
    private readonly IChimePlayer _chimePlayer;
    private readonly DispatcherQueue? _dispatcherQueue = TryGetDispatcherQueue();
    private readonly object _gate = new();
    private WakeWordConfiguration? _configuration;
    private IMicrophoneLease? _lease;
    private Task _turnTask = Task.CompletedTask;
    private WakeWordUiState _state = WakeWordUiState.Off;
    private string _statusText = WakeWordUiStateText.For(WakeWordUiState.Off);
    private string? _errorMessage;
    private bool _isEnabled;

    public WakeWordCoordinator(
        IWakeWordDetector detector,
        IMicrophoneArbiter arbiter,
        IVoiceDevice voiceDevice,
        IRevaCoreClient coreClient,
        IComposerSink composerSink,
        IChimePlayer chimePlayer)
    {
        _detector = detector;
        _arbiter = arbiter;
        _voiceDevice = voiceDevice;
        _coreClient = coreClient;
        _composerSink = composerSink;
        _chimePlayer = chimePlayer;
        _detector.Detected += OnDetected;
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
        SetState(WakeWordUiState.Starting);
        await StartDetectorAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task DisableAsync(CancellationToken cancellationToken = default)
    {
        IsEnabled = false;
        await StopAndReleaseAsync(cancellationToken).ConfigureAwait(false);
        SetState(WakeWordUiState.Off);
    }

    public async Task SuspendForHoldToTalkAsync(CancellationToken cancellationToken = default)
    {
        await StopAndReleaseAsync(cancellationToken).ConfigureAwait(false);
        SetState(WakeWordUiState.Off);
    }

    public async Task ResumeAfterHoldToTalkAsync(CancellationToken cancellationToken = default)
    {
        if (!IsEnabled || _configuration is null)
        {
            return;
        }

        await StartDetectorAsync(cancellationToken).ConfigureAwait(false);
    }

    internal Task WaitForTurnAsync() => _turnTask;

    private async Task StartDetectorAsync(CancellationToken cancellationToken)
    {
        if (_configuration is null)
        {
            SetState(WakeWordUiState.WakeWordError);
            return;
        }

        _lease ??= await _arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord, cancellationToken)
            .ConfigureAwait(false);
        if (_lease is null)
        {
            SetState(WakeWordUiState.MicrophoneUnavailable);
            return;
        }

        try
        {
            await _detector.StartAsync(_configuration, _lease, cancellationToken).ConfigureAwait(false);
            ErrorMessage = null;
            SetState(WakeWordUiState.Armed);
        }
        catch (Exception) when (!cancellationToken.IsCancellationRequested)
        {
            await ReleaseLeaseAsync().ConfigureAwait(false);
            ErrorMessage = "Wake word could not start.";
            SetState(WakeWordUiState.WakeWordError);
        }
    }

    private void OnDetected(object? sender, WakeWordDetection detection)
    {
        lock (_gate)
        {
            if (State != WakeWordUiState.Armed)
            {
                return;
            }

            SetState(WakeWordUiState.Detected);
            _turnTask = RunTurnAsync(detection, CancellationToken.None);
        }
    }

    private async Task RunTurnAsync(WakeWordDetection detection, CancellationToken cancellationToken)
    {
        DesktopLogger.Info($"wakeword.detected phrase={detection.Phrase}");
        var recordingStarted = false;
        try
        {
            await _detector.StopAsync(cancellationToken).ConfigureAwait(false);
            await _chimePlayer.PlayAsync(cancellationToken).ConfigureAwait(false);
            SetState(WakeWordUiState.Listening);
            await _voiceDevice.StartRecordingAsync(cancellationToken).ConfigureAwait(false);
            recordingStarted = true;

            SetState(WakeWordUiState.Transcribing);
            var audio = await _voiceDevice.StopRecordingAsync(cancellationToken).ConfigureAwait(false);
            recordingStarted = false;

            if (audio.Length == 0 || !WavAudio.TryGetDurationMs(audio, out var durationMs) || durationMs < 250)
            {
                ErrorMessage = "No speech was recognized. Try again.";
                SetState(WakeWordUiState.WakeWordError);
                return;
            }

            var transcription = await _coreClient.TranscribeSpeechAsync(audio, cancellationToken).ConfigureAwait(false);
            if (!transcription.IsSuccess)
            {
                ErrorMessage = transcription.Error!.SafeMessage;
                SetState(WakeWordUiState.SttUnavailable);
                return;
            }

            var text = StripWakePhrase(transcription.Value!.Text?.Trim() ?? string.Empty, detection.Phrase);
            if (text.Length == 0)
            {
                ErrorMessage = "No speech was recognized. Try again.";
                SetState(WakeWordUiState.WakeWordError);
                return;
            }

            await _composerSink.SubmitTranscriptionAsync(text, cancellationToken).ConfigureAwait(false);
            ErrorMessage = null;
            SetState(WakeWordUiState.Cooldown);
        }
        catch (OperationCanceledException)
        {
            SetState(WakeWordUiState.Cooldown);
        }
        catch (Exception)
        {
            ErrorMessage = "Wake word capture failed. Try again.";
            SetState(WakeWordUiState.WakeWordError);
        }
        finally
        {
            if (recordingStarted)
            {
                try
                {
                    _voiceDevice.CancelRecording();
                }
                catch
                {
                }
            }

            if (IsEnabled && _configuration is not null)
            {
                await StartDetectorAsync(CancellationToken.None).ConfigureAwait(false);
            }
        }
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
        await _detector.StopAsync(cancellationToken).ConfigureAwait(false);
        await ReleaseLeaseAsync().ConfigureAwait(false);
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
        await StopAndReleaseAsync(CancellationToken.None).ConfigureAwait(false);
        await _detector.DisposeAsync().ConfigureAwait(false);
    }
}
