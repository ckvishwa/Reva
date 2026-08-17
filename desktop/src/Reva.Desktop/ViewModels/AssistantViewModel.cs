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
    private CancellationTokenSource? _speechPlaybackCancellation;
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

        VoiceState = IsCoreConnected ? VoiceUiState.ReadyToTalk : VoiceUiState.SttUnavailable;
        VoiceErrorMessage = IsCoreConnected ? null : "REVA Core is not connected.";
    }

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

    public string ComposerText
    {
        get => _composerText;
        set => SetProperty(ref _composerText, value);
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
            VoiceStatusText = availability.IsReady ? "Voice Ready" : "Voice Unavailable";
            VoiceErrorMessage = availability.IsReady ? null : availability.SafeMessage;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            _isVoiceAvailable = false;
            VoiceStatusText = "Voice Unavailable";
            VoiceErrorMessage = VoiceDeviceAvailability.RecordingFailed().SafeMessage;
        }
        finally
        {
            RaiseVoiceAvailabilityProperties();
        }
    }

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
        VoiceStatusText = "Listening…";
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
            VoiceStatusText = _isVoiceAvailable ? "Voice Ready" : "Voice Unavailable";
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
        VoiceStatusText = "Transcribing…";

        try
        {
            if (_recordingStartTask is not null)
            {
                await _recordingStartTask;
            }

            var audio = await _voiceDevice.StopRecordingAsync(linkedToken);
            if (audio.Length == 0)
            {
                VoiceErrorMessage = "No voice audio was captured.";
                VoiceStatusText = _isVoiceAvailable ? "Voice Ready" : "Voice Unavailable";
                return;
            }

            var transcription = await _coreClient.TranscribeSpeechAsync(audio, linkedToken);
            if (!transcription.IsSuccess)
            {
                ApplyVoiceFailure(transcription.Error!);
                return;
            }

            VoiceStatusText = "Thinking…";
            var reply = await SendMessageCoreAsync(
                transcription.Value!.Text,
                clearComposer: false,
                linkedToken);
            if (reply is null)
            {
                VoiceStatusText = "Voice Ready";
                return;
            }

            VoiceStatusText = "Speaking…";
            var language = VoiceLanguageResolver.Resolve(reply);
            var speech = await _coreClient.SynthesizeSpeechAsync(reply, language, linkedToken);
            if (!speech.IsSuccess)
            {
                ApplyVoiceFailure(speech.Error!);
                return;
            }

            _speechPlaybackCancellation?.Cancel();
            _speechPlaybackCancellation?.Dispose();
            _speechPlaybackCancellation = CancellationTokenSource.CreateLinkedTokenSource(linkedToken);
            IsSpeaking = true;
            await _voiceDevice.PlayAsync(speech.Value!, _speechPlaybackCancellation.Token);
            VoiceStatusText = _isVoiceAvailable ? "Voice Ready" : "Voice Unavailable";
        }
        catch (OperationCanceledException)
        {
            VoiceStatusText = _isVoiceAvailable ? "Voice Ready" : "Voice Unavailable";
        }
        catch (VoiceCaptureException ex)
        {
            ApplyVoiceCaptureFailure(ex.Availability);
        }
        catch (Exception)
        {
            ApplyVoiceCaptureFailure(VoiceDeviceAvailability.RecordingFailed());
        }
        finally
        {
            _recordingStartTask = null;
            IsSpeaking = false;
            IsVoiceBusy = false;
        }
    }

    public void StopSpeaking()
    {
        _speechPlaybackCancellation?.Cancel();
        _voiceDevice.StopPlayback();
        IsSpeaking = false;
        if (!IsMicrophoneActive && _isVoiceAvailable)
        {
            VoiceStatusText = "Voice Ready";
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
        VoiceStatusText = error.Kind is CoreErrorKind.CoreUnavailable or CoreErrorKind.CoreTimeout
            ? "Voice Unavailable"
            : "Voice Ready";
    }

    private void ApplyVoiceCaptureFailure(VoiceDeviceAvailability availability)
    {
        _isVoiceAvailable = false;
        VoiceStatusText = "Voice Unavailable";
        VoiceErrorMessage = availability.SafeMessage;
        IsMicrophoneActive = false;
        IsVoiceBusy = false;
        RaiseVoiceAvailabilityProperties();
    }
}
