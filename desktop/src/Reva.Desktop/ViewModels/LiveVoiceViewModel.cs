using Reva.Desktop.State;
using Reva.Desktop.Voice;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Binds <see cref="VoiceLoopController"/> to the Talk page. It has no WinUI types, so it is
/// tested from the plain test project. The controller raises events on worker threads;
/// <c>post</c> hands each refresh to the UI thread.
/// </summary>
public sealed class LiveVoiceViewModel : ObservableObject
{
    private readonly VoiceLoopController _loop;
    private readonly Action<Action> _post;
    private IReadOnlyList<AudioDeviceInfo> _microphones = Array.Empty<AudioDeviceInfo>();
    private AudioDeviceInfo? _selectedMicrophone;

    public VoiceLoopController Loop => _loop;

    public LiveVoiceViewModel(VoiceLoopController loop, Action<Action>? post = null)
    {
        _loop = loop;
        _post = post ?? (action => action());
        _loop.Changed += () => _post(Refresh);
    }

    public bool IsOn => _loop.State is not (LiveVoiceState.Off or LiveVoiceState.Error);

    public bool CanTalk => _loop.State is LiveVoiceState.Ready or LiveVoiceState.Listening
        or LiveVoiceState.Thinking or LiveVoiceState.Approval or LiveVoiceState.Speaking;

    public string StateText => _loop.State switch
    {
        LiveVoiceState.Off => "Voice is off.",
        LiveVoiceState.Connecting => "Connecting…",
        LiveVoiceState.Ready => _loop.MicMuted ? "Microphone muted." : "Hold Ctrl+Space or the button to talk.",
        LiveVoiceState.Listening => "Listening…",
        LiveVoiceState.Thinking => "Thinking…",
        LiveVoiceState.Approval => "Waiting for your approval.",
        LiveVoiceState.Speaking => _loop.SpeakerMuted ? "Reply ready (speaker muted)." : "Speaking…",
        _ => "Voice stopped.",
    };

    public string? Message => _loop.Message;

    public string? Transcript => _loop.LastTranscript is null ? null : $"You: {_loop.LastTranscript}";

    public string? Reply => _loop.LastReply is null ? null : $"REVA: {_loop.LastReply}";

    public string? Notice => _loop.LastNotice;

    /// <summary>True only while the microphone device is really open.</summary>
    public bool MicOpen => _loop.MicOpen;

    public bool MicMuted => _loop.MicMuted;

    public bool SpeakerMuted => _loop.SpeakerMuted;

    public IReadOnlyList<AudioDeviceInfo> Microphones
    {
        get => _microphones;
        private set => SetProperty(ref _microphones, value);
    }

    public AudioDeviceInfo? SelectedMicrophone
    {
        get => _selectedMicrophone;
        set
        {
            if (SetProperty(ref _selectedMicrophone, value))
            {
                _loop.DeviceId = value?.Id; // null means "the default microphone"
            }
        }
    }

    public void RefreshMicrophones()
    {
        var devices = _loop.ListMicrophones();
        Microphones = devices;
        if (_selectedMicrophone is not null && devices.All(d => d.Id != _selectedMicrophone.Id))
        {
            SelectedMicrophone = null; // the chosen mic is gone: fall back to the default
        }
    }

    public Task TurnOnAsync() => _loop.StartAsync();

    public Task TurnOffAsync() => _loop.StopAsync();

    public Task TalkPressedAsync() => _loop.PressAsync();

    public Task TalkReleasedAsync() => _loop.ReleaseAsync();

    public Task SetMicMutedAsync(bool muted) => _loop.SetMicMutedAsync(muted);

    public Task SetSpeakerMutedAsync(bool muted) => _loop.SetSpeakerMutedAsync(muted);

    public Task StopSpeakingAsync() => _loop.InterruptAsync();

    private void Refresh()
    {
        foreach (var name in new[]
        {
            nameof(IsOn), nameof(CanTalk), nameof(StateText), nameof(Message), nameof(Transcript),
            nameof(Reply), nameof(Notice), nameof(MicOpen), nameof(MicMuted), nameof(SpeakerMuted),
        })
        {
            RaisePropertyChanged(name);
        }
    }
}
