using System.Collections.ObjectModel;
using Microsoft.UI.Dispatching;
using Reva.Desktop.Services;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Typed assistant conversation for the current app session. No WinUI
/// types — testable without the XAML build pipeline. No persistence, no
/// history reload, no memory creation (that's Slice 4's "Remember this"
/// action, a deliberately separate, explicit code path — ADR-006).
/// </summary>
public sealed class AssistantViewModel : ObservableObject
{
    private readonly IRevaCoreClient _coreClient;
    private readonly IVoiceDevice _voiceDevice;
    private readonly IRevaCoreLifecycle? _lifecycle;
    private readonly DispatcherQueue? _dispatcherQueue = TryGetDispatcherQueue();
    private string _composerText = string.Empty;
    private bool _isPending;
    private bool _isVoiceAvailable;
    private bool _isVoiceBusy;
    private bool _isListening;
    private bool _isSpeaking;
    private VoiceUiState _voiceState;
    private string _voiceStatusText = "Voice Unavailable";
    private string? _errorMessage;
    private string? _voiceErrorMessage;
    private CancellationTokenSource? _voiceTurnCancellation;
    private Task? _recordingStartTask;

    public AssistantViewModel(
        IRevaCoreClient coreClient,
        IVoiceDevice? voiceDevice = null,
        IRevaCoreLifecycle? lifecycle = null)
    {
        _coreClient = coreClient;
        _voiceDevice = voiceDevice ?? new UnavailableVoiceDevice();
        _lifecycle = lifecycle;
        _isVoiceAvailable = _voiceDevice.IsAvailable;
        _voiceState = _isVoiceAvailable
            ? (IsCoreConnected ? VoiceUiState.ReadyToTalk : VoiceUiState.SttUnavailable)
            : VoiceUiState.CheckingMicrophone;
        _voiceStatusText = VoiceUiStateText.For(_voiceState);

        if (_lifecycle is not null)
        {
            _lifecycle.StateChanged += OnLifecycleStateChanged;
        }
    }

    // Captured on the constructing thread: the UI thread in MainWindow, null
    // under xUnit. Never throws — a null queue simply means "already on the
    // right thread, invoke directly."
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

    private bool IsCoreConnected => _lifecycle is null || _lifecycle.State == CoreLifecycleState.Connected;

    private void OnLifecycleStateChanged(object? sender, EventArgs e)
    {
        // Even though today's RevaCoreLifecycle implementation deliberately
        // preserves the UI-thread SynchronizationContext via
        // ConfigureAwait(true) (so StateChanged doesn't actually fire off the
        // UI thread in production today), nothing at the IRevaCoreLifecycle
        // interface level guarantees that invariant. Marshal defensively
        // rather than depending on an implementation detail this class
        // doesn't own — a stray off-thread PropertyChanged push here would
        // throw RPC_E_WRONG_THREAD at runtime.
        if (_dispatcherQueue is not null && !_dispatcherQueue.HasThreadAccess)
        {
            _dispatcherQueue.TryEnqueue(ApplyLifecycleChange);
            return;
        }

        ApplyLifecycleChange();
    }

    private void ApplyLifecycleChange()
    {
        RefreshIdleVoiceState();
        RaiseVoiceAvailabilityProperties();
    }

    // Recomputes the idle status from mic + Core so status and enablement can
    // never disagree. Deliberately does nothing mid-turn, and never overwrites
    // a mic-specific failure (which is more informative than "STT Unavailable").
    private void RefreshIdleVoiceState()
    {
        if (IsMicrophoneActive || IsVoiceBusy)
        {
            return;
        }

        if (VoiceState is VoiceUiState.PermissionDenied
            or VoiceUiState.NoMicrophone
            or VoiceUiState.CheckingMicrophone)
        {
            return;
        }

        if (!_isVoiceAvailable)
        {
            return;
        }

        VoiceState = IdleState();
        VoiceErrorMessage = IsCoreConnected ? null : "REVA Core is not connected.";
    }

    // Shared idle computation: what VoiceState should read when nothing is
    // in flight. Used both by RefreshIdleVoiceState (Core-lifecycle-driven,
    // with its own no-op guards above) and by RestoreIdleVoiceState (used at
    // the end of a canceled/interrupted voice turn).
    private VoiceUiState IdleState() =>
        !_isVoiceAvailable ? VoiceUiState.NoMicrophone
        : IsCoreConnected ? VoiceUiState.ReadyToTalk
        : VoiceUiState.SttUnavailable;

    private void RestoreIdleVoiceState() => VoiceState = IdleState();

    /// <summary>Unsubscribes from lifecycle StateChanged. Call from the
    /// window's Closed handler — an AssistantViewModel outliving its window
    /// would otherwise keep this instance alive via the event subscription.</summary>
    public void DetachLifecycle()
    {
        if (_lifecycle is not null)
        {
            _lifecycle.StateChanged -= OnLifecycleStateChanged;
        }
    }

    public ObservableCollection<AssistantMessage> Messages { get; } = new();

    private CommandSource _composerSource = CommandSource.Typed;

    public CommandSource ComposerSource => _composerSource;

    public string ComposerText
    {
        get => _composerText;
        set
        {
            SetProperty(ref _composerText, value);

            // Any write through the public setter is user authorship — the
            // x:Bind TwoWay path and every test call site land here. This is
            // unconditional (not gated on SetProperty detecting a change):
            // re-assigning the same text the user is looking at (e.g. a
            // TextBox TwoWay sync firing after a no-op edit) still counts as
            // the user having touched it.
            _composerSource = CommandSource.Typed;
        }
    }

    /// <summary>The transcription path's write. Same append semantics as a
    /// user edit, but marks the text as machine-authored so a spoken
    /// "confirm" can't resolve a pending destructive command.</summary>
    private void AppendTranscribedText(string text)
    {
        var merged = string.IsNullOrWhiteSpace(_composerText)
            ? text
            : $"{_composerText.TrimEnd()} {text}";

        SetProperty(ref _composerText, merged, nameof(ComposerText));

        _composerSource = CommandSource.Transcribed;   // after the setter, not before
    }

    public bool IsPending
    {
        get => _isPending;
        private set
        {
            if (SetProperty(ref _isPending, value))
            {
                RaisePropertyChanged(nameof(IsNotPending));
            }
        }
    }

    /// <summary>Plain bool (not a WinUI Visibility) so this stays bindable
    /// from XAML without a converter, and the ViewModel stays free of
    /// WinUI types.</summary>
    public bool IsNotPending => !IsPending;

    public bool CanUseVoiceButton => _isVoiceAvailable && IsCoreConnected && !IsPending;

    public bool IsMicrophoneActive
    {
        get => _isListening;
        private set
        {
            if (SetProperty(ref _isListening, value))
            {
                RaiseVoiceAvailabilityProperties();
            }
        }
    }

    public bool IsSpeaking
    {
        get => _isSpeaking;
        private set
        {
            if (SetProperty(ref _isSpeaking, value))
            {
                RaiseVoiceAvailabilityProperties();
            }
        }
    }

    public bool IsVoiceBusy
    {
        get => _isVoiceBusy;
        private set
        {
            if (SetProperty(ref _isVoiceBusy, value))
            {
                RaiseVoiceAvailabilityProperties();
            }
        }
    }

    public bool CanStartVoiceInput => _isVoiceAvailable && IsCoreConnected && !IsPending && !IsVoiceBusy;

    public bool CanStopSpeaking => IsSpeaking;

    /// <summary>The mic+Core readiness state. Authoritative for the idle
    /// (not-mid-turn) status text — see <see cref="RefreshIdleVoiceState"/>.
    /// Mid-turn transitions ("Listening…", "Transcribing…", etc.) still set
    /// <see cref="VoiceStatusText"/> directly; wiring VoiceState through the
    /// full turn lifecycle is Task 7's job.</summary>
    public VoiceUiState VoiceState
    {
        get => _voiceState;
        private set
        {
            if (SetProperty(ref _voiceState, value))
            {
                VoiceStatusText = VoiceUiStateText.For(value);
            }
        }
    }

    public string VoiceStatusText
    {
        get => _voiceStatusText;
        private set => SetProperty(ref _voiceStatusText, value);
    }

    /// <summary>Safe, display-ready text only — never a raw exception,
    /// response body, or internal detail. Null when there is no error to
    /// show.</summary>
    public string? ErrorMessage
    {
        get => _errorMessage;
        private set => SetProperty(ref _errorMessage, value);
    }

    public string? VoiceErrorMessage
    {
        get => _voiceErrorMessage;
        private set => SetProperty(ref _voiceErrorMessage, value);
    }

    public async Task RefreshVoiceAvailabilityAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var availability = await _voiceDevice.VerifyAvailabilityAsync(cancellationToken);
            _isVoiceAvailable = availability.IsReady;
            VoiceState = MapAvailabilityToVoiceState(availability);
            VoiceErrorMessage = availability.IsReady ? null : availability.SafeMessage;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            _isVoiceAvailable = false;
            VoiceState = VoiceUiState.NoMicrophone;
            VoiceErrorMessage = VoiceDeviceAvailability.RecordingFailed().SafeMessage;
        }
        finally
        {
            RaiseVoiceAvailabilityProperties();
        }
    }

    // Routes the verification outcome through VoiceState (rather than
    // writing VoiceStatusText directly) so this call site can never desync
    // status text from button enablement — VoiceState's setter pushes into
    // VoiceStatusText automatically. This is the real-world startup path:
    // WindowsVoiceDevice.IsAvailable is false until VerifyAvailabilityAsync
    // confirms the mic, so the constructor always seeds VoiceState at
    // CheckingMicrophone; this is what moves it off that value for good.
    private VoiceUiState MapAvailabilityToVoiceState(VoiceDeviceAvailability availability) => availability.Kind switch
    {
        VoiceDeviceAvailabilityKind.Ready => IsCoreConnected ? VoiceUiState.ReadyToTalk : VoiceUiState.SttUnavailable,
        VoiceDeviceAvailabilityKind.PermissionDenied => VoiceUiState.PermissionDenied,
        VoiceDeviceAvailabilityKind.NoMicrophoneFound => VoiceUiState.NoMicrophone,
        VoiceDeviceAvailabilityKind.RecordingFailed => VoiceUiState.NoMicrophone,
        _ => VoiceUiState.NoMicrophone,
    };

    public async Task SendMessageAsync(CancellationToken cancellationToken = default)
    {
        if (IsPending)
        {
            // Duplicate submission while a request is already in flight —
            // ignored, not queued. Exactly one Core request per user click.
            return;
        }

        var trimmed = ComposerText.Trim();
        await SendMessageCoreAsync(trimmed, clearComposer: true, cancellationToken);
    }

    public async Task StartVoiceInputAsync(CancellationToken cancellationToken = default)
    {
        if (!_isVoiceAvailable)
        {
            await RefreshVoiceAvailabilityAsync(cancellationToken);
        }

        if (!CanStartVoiceInput)
        {
            return;
        }

        StopSpeaking();
        VoiceErrorMessage = null;
        IsVoiceBusy = true;
        IsMicrophoneActive = true;
        VoiceState = VoiceUiState.Listening;
        DesktopLogger.Info("voice.state=Listening");
        _voiceTurnCancellation?.Dispose();
        _voiceTurnCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

        try
        {
            _recordingStartTask = _voiceDevice.StartRecordingAsync(_voiceTurnCancellation.Token);
            await _recordingStartTask;
        }
        catch (OperationCanceledException)
        {
            IsMicrophoneActive = false;
            IsVoiceBusy = false;
            RestoreIdleVoiceState();
        }
        catch (VoiceCaptureException ex)
        {
            ApplyVoiceCaptureFailure(ex.Availability);
            _voiceDevice.CancelRecording();
        }
        catch (Exception) when (!cancellationToken.IsCancellationRequested)
        {
            ApplyVoiceCaptureFailure(VoiceDeviceAvailability.RecordingFailed());
            _voiceDevice.CancelRecording();
        }
    }

    public async Task FinishVoiceInputAsync(CancellationToken cancellationToken = default)
    {
        if (!IsMicrophoneActive)
        {
            return;
        }

        var turnCancellation = _voiceTurnCancellation;
        var linkedToken = turnCancellation?.Token ?? cancellationToken;
        IsMicrophoneActive = false;
        VoiceState = VoiceUiState.Transcribing;
        DesktopLogger.Info("voice.state=Transcribing");

        try
        {
            if (_recordingStartTask is not null)
            {
                await _recordingStartTask;
            }

            var audio = await _voiceDevice.StopRecordingAsync(linkedToken);

            if (audio.Length == 0)
            {
                FailTurn("No voice audio was captured.", "empty_capture");
                return;
            }

            if (!WavAudio.TryGetDurationMs(audio, out var durationMs))
            {
                FailTurn("The recording could not be read. Try again.", "malformed_wav");
                return;
            }

            if (durationMs < MinimumRecordingMs)
            {
                FailTurn(
                    "Recording is too short. Hold the button and speak for at least a quarter second.",
                    "too_short");
                return;
            }

            var transcription = await _coreClient.TranscribeSpeechAsync(audio, linkedToken);
            if (!transcription.IsSuccess)
            {
                ApplyVoiceFailure(transcription.Error!);
                return;
            }

            var text = transcription.Value!.Text?.Trim() ?? string.Empty;
            if (text.Length == 0)
            {
                // 200 OK with no words — silence, not success. Reporting
                // "Transcription Ready" over an empty composer is misleading.
                FailTurn("No speech was recognized. Try again.", "empty_transcript");
                return;
            }

            AppendTranscribedText(text);
            VoiceErrorMessage = null;
            VoiceState = VoiceUiState.TranscriptionReady;
            DesktopLogger.Info("voice.state=TranscriptionReady");
        }
        catch (OperationCanceledException)
        {
            RestoreIdleVoiceState();
            DesktopLogger.Info("voice.state=canceled");
        }
        catch (VoiceCaptureException ex)
        {
            ApplyVoiceCaptureFailure(ex.Availability);
        }
        catch (Exception)
        {
            FailTurn(VoiceDeviceAvailability.RecordingFailed().SafeMessage, "recording_failed");
        }
        finally
        {
            _recordingStartTask = null;
            IsVoiceBusy = false;
        }
    }

    private const int MinimumRecordingMs = 250;

    // reason is a fixed identifier, never audio or transcript content.
    private void FailTurn(string safeMessage, string reason)
    {
        VoiceErrorMessage = safeMessage;
        VoiceState = VoiceUiState.TranscriptionFailed;
        DesktopLogger.Info($"voice.state=TranscriptionFailed reason={reason}");
    }

    public void StopSpeaking()
    {
        _voiceDevice.StopPlayback();
        IsSpeaking = false;
        if (!IsMicrophoneActive && _isVoiceAvailable)
        {
            VoiceState = IdleState();
        }
    }

    private async Task<string?> SendMessageCoreAsync(
        string content,
        bool clearComposer,
        CancellationToken cancellationToken)
    {
        var trimmed = content.Trim();
        if (trimmed.Length == 0 || IsPending)
        {
            return null;
        }

        ErrorMessage = null;
        IsPending = true;
        RaiseVoiceAvailabilityProperties();
        Messages.Add(AssistantMessage.FromUser(trimmed));
        if (clearComposer)
        {
            ComposerText = string.Empty;
            _composerSource = CommandSource.Typed; // an empty composer has no author
        }

        try
        {
            var result = await _coreClient.SendMessageAsync(trimmed, cancellationToken);
            if (result.IsSuccess)
            {
                var reply = result.Value!.Reply;
                Messages.Add(AssistantMessage.FromAssistant(reply));
                return reply;
            }
            else
            {
                ErrorMessage = result.Error!.SafeMessage;
                return null;
            }
        }
        finally
        {
            IsPending = false;
            RaiseVoiceAvailabilityProperties();
        }
    }

    private void RaiseVoiceAvailabilityProperties()
    {
        RaisePropertyChanged(nameof(CanStartVoiceInput));
        RaisePropertyChanged(nameof(CanUseVoiceButton));
        RaisePropertyChanged(nameof(CanStopSpeaking));
    }

    private void ApplyVoiceFailure(CoreError error)
    {
        VoiceErrorMessage = error.SafeMessage;
        VoiceState = error.Kind is CoreErrorKind.CoreUnavailable or CoreErrorKind.CoreTimeout
            ? VoiceUiState.SttUnavailable
            : VoiceUiState.TranscriptionFailed;
        DesktopLogger.Info($"voice.state={VoiceState} kind={error.Kind}");
    }

    private void ApplyVoiceCaptureFailure(VoiceDeviceAvailability availability)
    {
        _isVoiceAvailable = false;
        VoiceState = MapAvailabilityToVoiceState(availability);
        VoiceErrorMessage = availability.SafeMessage;
        IsMicrophoneActive = false;
        IsVoiceBusy = false;
        RaiseVoiceAvailabilityProperties();
    }
}
