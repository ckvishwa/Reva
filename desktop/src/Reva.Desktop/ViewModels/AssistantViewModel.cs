using System.Collections.ObjectModel;
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
    private string _composerText = string.Empty;
    private bool _isPending;
    private bool _isVoiceAvailable;
    private bool _isVoiceBusy;
    private bool _isListening;
    private bool _isSpeaking;
    private string _voiceStatusText = "Voice Unavailable";
    private string? _errorMessage;
    private string? _voiceErrorMessage;
    private CancellationTokenSource? _voiceTurnCancellation;
    private CancellationTokenSource? _speechPlaybackCancellation;
    private Task? _recordingStartTask;

    public AssistantViewModel(IRevaCoreClient coreClient, IVoiceDevice? voiceDevice = null)
    {
        _coreClient = coreClient;
        _voiceDevice = voiceDevice ?? new UnavailableVoiceDevice();
        _isVoiceAvailable = _voiceDevice.IsAvailable;
        _voiceStatusText = _isVoiceAvailable ? "Voice Ready" : "Voice Unavailable";
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

    public bool CanUseVoiceButton => _isVoiceAvailable && !IsPending;

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

    public bool CanStartVoiceInput => _isVoiceAvailable && !IsPending && !IsVoiceBusy;

    public bool CanStopSpeaking => IsSpeaking;

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
