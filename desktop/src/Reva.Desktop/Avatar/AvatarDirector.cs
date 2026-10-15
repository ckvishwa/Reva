using System.Text.Json;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Avatar;

/// <summary>Where avatar messages go (the WebView2 page, or a fake in tests).</summary>
public interface IAvatarSink
{
    void Post(string json);

    /// <summary>The page said it is ready (so the director re-sends the current state) or failed.</summary>
    event Action<PageMessage>? PageMessageReceived;
}

/// <summary>
/// Turns what is really happening in the voice loop into avatar messages. It decides nothing itself:
///  * "listening" is sent only while the microphone device is open (AR-WIN-004, AR-VA-009), never
///    because a state label says so;
///  * the mouth follows the loudness of the audio actually being played, only for the current
///    turn_epoch and only while speaking (FR-AV-003, FR-AV-004);
///  * a face from Core is forwarded only if it is a valid schema message, and a result face
///    (verified_outcome) only with the action id Core gave (AR-VA-011);
///  * every message carries the turn_epoch, so the page can drop anything that arrives late.
/// </summary>
public sealed class AvatarDirector : IDisposable
{
    private readonly VoiceLoopController _loop;
    private readonly IAvatarSink _sink;
    private readonly LevelPacer<PlaybackLevel> _pacer;
    private readonly Func<long> _nowMs;
    private readonly object _lock = new();
    private string? _lastState;
    private int _lastEpoch = -1;
    private AvatarSettings _settings = AvatarSettings.Default;
    private bool _systemAnimations = true;
    private bool _windowVisible = true;
    private bool _pageReady;

    public AvatarDirector(
        VoiceLoopController loop,
        IAvatarSink sink,
        int lipSyncDelayMs = 40,
        Func<long>? nowMs = null)
    {
        _loop = loop;
        _sink = sink;
        _pacer = new LevelPacer<PlaybackLevel>(lipSyncDelayMs);
        _nowMs = nowMs ?? (() => Environment.TickCount64);
        _loop.Changed += OnLoopChanged;
        _loop.CoreEvent += OnCoreEvent;
        _loop.PlaybackLevel += OnLevel;
        _sink.PageMessageReceived += OnPageMessage;
    }

    /// <summary>Extra delay between the sound handed to the device and the mouth (set from the offset measurement).</summary>
    public int LipSyncDelayMs
    {
        get => _pacer.DelayMs;
        set => _pacer.DelayMs = value;
    }

    public AvatarSettings Settings => _settings;

    public bool PageReady => _pageReady;

    public void ApplySettings(AvatarSettings settings, bool systemAnimationsEnabled)
    {
        lock (_lock)
        {
            _settings = settings;
            _systemAnimations = systemAnimationsEnabled;
        }

        PostSettings();
    }

    /// <summary>The window was minimised or restored: nothing is drawn while it is hidden (AR-WIN-007).</summary>
    public void SetWindowVisible(bool visible)
    {
        lock (_lock)
        {
            _windowVisible = visible;
        }

        PostSettings();
    }

    /// <summary>Sends mouth levels whose delay has passed. Called by a timer (or a test) with the current time.</summary>
    public void Pump()
    {
        foreach (var level in _pacer.TakeDue(_nowMs()))
        {
            if (level.Epoch != _loop.TurnEpoch || _loop.State != LiveVoiceState.Speaking)
            {
                continue; // late: the turn moved on while it waited
            }

            Post(AvatarProtocol.Mouth(level.PositionMs, level.Rms, level.Epoch));
        }
    }

    public static string AvatarStateFor(LiveVoiceState state, bool micOpen) => state switch
    {
        LiveVoiceState.Listening => micOpen ? "listening" : "idle",
        LiveVoiceState.Thinking => "thinking",
        LiveVoiceState.Approval => "approval",
        LiveVoiceState.Speaking => "speaking",
        LiveVoiceState.Error => "error",
        _ => "idle",
    };

    private void OnLoopChanged()
    {
        var state = AvatarStateFor(_loop.State, _loop.MicOpen);
        var epoch = _loop.TurnEpoch;
        lock (_lock)
        {
            if (state == _lastState && epoch == _lastEpoch)
            {
                return;
            }

            _lastState = state;
            _lastEpoch = epoch;
        }

        if (state != "speaking")
        {
            _pacer.Clear(); // an interrupt or the end of speech: queued mouth movement must not play out
        }

        Post(AvatarProtocol.State(state, epoch));
    }

    private void OnCoreEvent(VoiceEvent ev)
    {
        if (ev.Kind != "assistant.text.final" || ev.Payload.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        if (!ev.Payload.TryGetProperty("avatar_event", out var face) || face.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        string? Text(string name) =>
            face.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

        var message = AvatarProtocol.Expression(Text("name") ?? string.Empty, Text("cause") ?? string.Empty, Text("action_id"));
        if (message is not null && Text("type") == "avatar.expression")
        {
            Post(message);
        }
    }

    private void OnLevel(PlaybackLevel level)
    {
        if (level.Epoch != _loop.TurnEpoch)
        {
            return;
        }

        _pacer.Add(level, _nowMs());
    }

    private void OnPageMessage(PageMessage message)
    {
        if (message.Kind != PageMessageKind.Ready)
        {
            return;
        }

        lock (_lock)
        {
            _pageReady = true;
            _lastState = null; // send the current state again: a fresh page knows nothing
        }

        PostSettings();
        OnLoopChanged();
    }

    private void PostSettings()
    {
        AvatarSettings settings;
        bool visible;
        bool animations;
        lock (_lock)
        {
            settings = _settings;
            visible = _windowVisible;
            animations = _systemAnimations;
        }

        Post(AvatarProtocol.Settings(
            settings.Enabled && visible,
            settings.EffectiveReducedMotion(animations),
            settings.Quality));
    }

    private void Post(string? json)
    {
        if (json is not null)
        {
            _sink.Post(json);
        }
    }

    public void Dispose()
    {
        _loop.Changed -= OnLoopChanged;
        _loop.CoreEvent -= OnCoreEvent;
        _loop.PlaybackLevel -= OnLevel;
        _sink.PageMessageReceived -= OnPageMessage;
    }
}
