using System.Text.Json;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Tests.Voice;

internal sealed class FakeClient : IVoiceSessionClient
{
    public readonly List<string> Sent = new();
    public readonly List<byte[]> Audio = new();
    public string? ConnectFailure;
    public byte[]? ReplyAudio = new byte[] { 1, 2, 3 };
    public bool IsConnected { get; private set; }

    public event Action<VoiceEvent>? EventReceived;

    public event Action<string>? Disconnected;

    public Task<string?> ConnectAsync(CancellationToken cancellationToken = default)
    {
        IsConnected = ConnectFailure is null;
        return Task.FromResult(ConnectFailure);
    }

    public Task SendControlAsync(string type, int? turnEpoch = null, CancellationToken cancellationToken = default)
    {
        lock (Sent)
        {
            Sent.Add(turnEpoch is null ? type : $"{type}@{turnEpoch}");
        }

        return Task.CompletedTask;
    }

    public Task SendAudioAsync(byte[] pcm, CancellationToken cancellationToken = default)
    {
        lock (Sent)
        {
            Sent.Add("audio");
            Audio.Add(pcm);
        }

        return Task.CompletedTask;
    }

    public Task<byte[]?> FetchAudioAsync(string path, CancellationToken cancellationToken = default) =>
        Task.FromResult(ReplyAudio);

    public Task CloseAsync()
    {
        IsConnected = false;
        return Task.CompletedTask;
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;

    public void Raise(string kind, int epoch, object? payload = null)
    {
        var json = JsonSerializer.SerializeToElement(payload ?? new { });
        EventReceived?.Invoke(new VoiceEvent(kind, epoch, json));
    }

    public void Drop() => Disconnected?.Invoke("The connection to REVA Core was lost.");

    public string[] Snapshot()
    {
        lock (Sent)
        {
            return Sent.ToArray();
        }
    }
}

internal sealed class FakeCapture : IAudioCapture
{
    public CaptureFailure? FailNextStart;
    public int Starts;
    public int Stops;
    public bool IsOpen { get; private set; }

    public event Action<byte[]>? Frame;

    public event Action? Lost;

    public IReadOnlyList<AudioDeviceInfo> ListDevices() =>
        new[] { new AudioDeviceInfo("mic-1", "Desk mic", true) };

    public void Start(string? deviceId)
    {
        if (FailNextStart is { } failure)
        {
            FailNextStart = null;
            throw new CaptureStartException(failure);
        }

        Starts++;
        IsOpen = true;
    }

    public void Stop()
    {
        Stops++;
        IsOpen = false;
    }

    public void Speak(int chunks = 3)
    {
        for (var i = 0; i < chunks; i++)
        {
            Frame?.Invoke(new byte[640]);
        }
    }

    public void Unplug()
    {
        IsOpen = false;
        Lost?.Invoke();
    }

    public void Dispose()
    {
    }
}

internal sealed class FakePlayback : IAudioPlayback
{
    public readonly List<int> Played = new();
    public int Flushes;
    public bool IsPlaying { get; private set; }

    public event Action<int>? Finished;

    public event Action<PlaybackLevel>? Level;

    public void EmitLevel(PlaybackLevel level) => Level?.Invoke(level);

    public void Play(byte[] wav, int turnEpoch)
    {
        Played.Add(turnEpoch);
        IsPlaying = true;
    }

    public void Flush()
    {
        Flushes++;
        IsPlaying = false;
    }

    public void FinishNaturally(int epoch)
    {
        IsPlaying = false;
        Finished?.Invoke(epoch);
    }

    public void Dispose()
    {
    }
}

internal sealed class FakeHotkey : IPushToTalkSource
{
    public bool Enabled;

    public event Action? Pressed;

    public event Action? Released;

    public void Enable() => Enabled = true;

    public void Disable() => Enabled = false;

    public void Press() => Pressed?.Invoke();

    public void Release() => Released?.Invoke();

    public void Dispose()
    {
    }
}

public class VoiceLoopControllerTests
{
    private readonly FakeClient _client = new();
    private readonly FakeCapture _capture = new();
    private readonly FakePlayback _playback = new();
    private readonly FakeHotkey _hotkey = new();
    private readonly VoiceLoopController _loop;

    public VoiceLoopControllerTests()
    {
        _loop = new VoiceLoopController(_client, _capture, _playback, _hotkey, _ => Task.CompletedTask);
    }

    private static async Task Settle(FakeClient client, Func<string[], bool> done)
    {
        for (var i = 0; i < 200; i++)
        {
            if (done(client.Snapshot()))
            {
                return;
            }

            await Task.Delay(10);
        }

        throw new Xunit.Sdk.XunitException("timed out; sent: " + string.Join(", ", client.Snapshot()));
    }

    private async Task Talk()
    {
        await _loop.PressAsync();
        _capture.Speak();
        await _loop.ReleaseAsync();
    }

    [Fact]
    public async Task Starting_enables_the_hotkey_and_stays_idle_with_the_mic_closed()
    {
        await _loop.StartAsync();

        Assert.Equal(LiveVoiceState.Ready, _loop.State);
        Assert.True(_hotkey.Enabled);
        Assert.False(_loop.MicOpen);
        Assert.Equal(0, _capture.Starts);
    }

    [Fact]
    public async Task A_failed_connection_is_reported_and_nothing_else_starts()
    {
        _client.ConnectFailure = "REVA Core isn't reachable.";

        await _loop.StartAsync();

        Assert.Equal(LiveVoiceState.Error, _loop.State);
        Assert.Equal("REVA Core isn't reachable.", _loop.Message);
        Assert.False(_hotkey.Enabled);
    }

    [Fact]
    public async Task Listening_shows_only_while_the_mic_is_really_open_and_it_closes_on_release()
    {
        await _loop.StartAsync();

        await _loop.PressAsync();
        Assert.Equal(LiveVoiceState.Listening, _loop.State);
        Assert.True(_loop.MicOpen);

        await _loop.ReleaseAsync();
        Assert.False(_loop.MicOpen);
        Assert.NotEqual(LiveVoiceState.Listening, _loop.State);
    }

    [Fact]
    public async Task A_turn_sends_requested_open_down_audio_up_in_that_order()
    {
        await _loop.StartAsync();

        await Talk();
        await Settle(_client, sent => sent.Contains("ptt.up"));

        var sent = _client.Snapshot();
        Assert.Equal(
            new[] { "capture.requested", "capture.open", "ptt.down", "audio", "audio", "audio", "ptt.up" },
            sent);
    }

    [Fact]
    public async Task Audio_is_not_sent_when_push_to_talk_is_not_held()
    {
        await _loop.StartAsync();

        _capture.Speak(); // nothing is listening

        await Task.Delay(50);
        Assert.DoesNotContain("audio", _client.Snapshot());
    }

    [Fact]
    public async Task The_hotkey_drives_the_same_path_in_order()
    {
        await _loop.StartAsync();

        _hotkey.Press();
        await Settle(_client, sent => sent.Contains("ptt.down"));
        _capture.Speak(2);
        _hotkey.Release();
        await Settle(_client, sent => sent.Contains("ptt.up"));

        Assert.Equal(
            new[] { "capture.requested", "capture.open", "ptt.down", "audio", "audio", "ptt.up" },
            _client.Snapshot());
    }

    [Fact]
    public async Task A_muted_mic_never_opens_or_sends()
    {
        await _loop.StartAsync();
        await _loop.SetMicMutedAsync(true);

        await _loop.PressAsync();

        Assert.Equal(0, _capture.Starts);
        Assert.Equal("The microphone is muted.", _loop.Message);
        await Settle(_client, sent => sent.Contains("mic.mute"));
    }

    [Fact]
    public async Task Muting_while_talking_cancels_the_utterance_and_closes_the_mic()
    {
        await _loop.StartAsync();
        await _loop.PressAsync();
        _capture.Speak(1);

        await _loop.SetMicMutedAsync(true);

        Assert.False(_loop.MicOpen);
        await Settle(_client, sent => sent.Contains("ptt.cancel"));
        _capture.Speak(); // frames after the mute are dropped
        await Task.Delay(30);
        Assert.Single(_client.Snapshot(), "audio");
    }

    [Fact]
    public async Task Unplugging_the_mic_returns_to_a_safe_idle_and_tells_core()
    {
        await _loop.StartAsync();
        await _loop.PressAsync();

        _capture.Unplug();
        await Settle(_client, sent => sent.Contains("capture.lost"));
        for (var i = 0; i < 100 && _loop.State == LiveVoiceState.Listening; i++)
        {
            await Task.Delay(10);
        }

        Assert.Equal(LiveVoiceState.Ready, _loop.State);
        Assert.Equal("The microphone was disconnected.", _loop.Message);
        Assert.False(_loop.MicOpen);
    }

    [Fact]
    public async Task After_a_lost_mic_the_next_press_starts_a_fresh_capture_request()
    {
        await _loop.StartAsync();
        await _loop.PressAsync();
        _capture.Unplug();
        await Settle(_client, sent => sent.Contains("capture.lost"));
        await Task.Delay(30);

        await _loop.PressAsync();
        await Settle(_client, sent => sent.Count(s => s == "capture.requested") == 2);

        Assert.Equal(2, _client.Snapshot().Count(s => s == "capture.requested"));
    }

    [Theory]
    [InlineData(CaptureFailure.NoDevice, "No microphone was found.", false)]
    [InlineData(CaptureFailure.PermissionDenied, "Windows is blocking microphone access for REVA.", true)]
    [InlineData(CaptureFailure.Failed, "The microphone could not be started.", false)]
    public async Task A_microphone_that_cannot_start_is_explained_and_never_listens(
        CaptureFailure failure, string message, bool denied)
    {
        await _loop.StartAsync();
        _capture.FailNextStart = failure;

        await _loop.PressAsync();
        await Task.Delay(30);

        Assert.Equal(message, _loop.Message);
        Assert.NotEqual(LiveVoiceState.Listening, _loop.State);
        Assert.Equal(denied, _client.Snapshot().Contains("capture.denied"));
        Assert.DoesNotContain("ptt.down", _client.Snapshot());
    }

    [Fact]
    public async Task A_reply_for_the_current_epoch_is_played_and_its_end_is_reported()
    {
        await _loop.StartAsync();
        _client.Raise("session.state", 1, new { state = "speaking" });

        _client.Raise("tts.started", 1, new { purpose = "reply", audio_path = "/v1/voice/sessions/s/audio/a" });
        for (var i = 0; i < 100 && _playback.Played.Count == 0; i++)
        {
            await Task.Delay(10);
        }

        Assert.Equal(new[] { 1 }, _playback.Played);
        Assert.Equal(LiveVoiceState.Speaking, _loop.State);
        _playback.FinishNaturally(1);
        await Settle(_client, sent => sent.Contains("playback.finished@1"));
    }

    [Fact]
    public async Task A_reply_from_an_older_epoch_is_never_played()
    {
        await _loop.StartAsync();
        _client.Raise("session.state", 3, new { state = "listening" }); // a newer epoch is known

        _client.Raise("tts.started", 2, new { purpose = "reply", audio_path = "/v1/voice/sessions/s/audio/a" });
        await Task.Delay(50);

        Assert.Empty(_playback.Played);
    }

    [Fact]
    public async Task A_newer_epoch_cuts_playback_at_once()
    {
        await _loop.StartAsync();
        var before = _playback.Flushes;

        _client.Raise("session.state", 5, new { state = "listening" });

        Assert.True(_playback.Flushes > before);
        Assert.Equal(5, _loop.TurnEpoch);
    }

    [Fact]
    public async Task Pressing_push_to_talk_flushes_playback_before_anything_is_sent()
    {
        await _loop.StartAsync();
        _playback.Play(new byte[1], 1);
        var before = _playback.Flushes;

        await _loop.PressAsync();

        Assert.True(_playback.Flushes > before);
        Assert.False(_playback.IsPlaying);
    }

    [Fact]
    public async Task A_muted_speaker_skips_playback_but_still_reports_the_reply_finished()
    {
        await _loop.StartAsync();
        await _loop.SetSpeakerMutedAsync(true);
        _client.Raise("session.state", 1, new { state = "speaking" });

        _client.Raise("tts.started", 1, new { purpose = "reply", audio_path = "/v1/voice/sessions/s/audio/a" });

        await Settle(_client, sent => sent.Contains("playback.finished@1"));
        Assert.Empty(_playback.Played);
    }

    [Fact]
    public async Task Muting_the_speaker_mid_reply_stops_it_and_reports_finished()
    {
        await _loop.StartAsync();
        _client.Raise("session.state", 1, new { state = "speaking" });
        _playback.Play(new byte[1], 1);

        await _loop.SetSpeakerMutedAsync(true);

        Assert.False(_playback.IsPlaying);
        await Settle(_client, sent => sent.Contains("playback.finished@1"));
    }

    [Fact]
    public async Task A_reply_that_cannot_be_fetched_does_not_hang_the_session()
    {
        await _loop.StartAsync();
        _client.ReplyAudio = null;
        _client.Raise("session.state", 1, new { state = "speaking" });

        _client.Raise("tts.started", 1, new { purpose = "reply", audio_path = "/v1/voice/sessions/s/audio/a" });

        await Settle(_client, sent => sent.Contains("playback.finished@1"));
        Assert.Empty(_playback.Played);
    }

    [Fact]
    public async Task Transcript_and_reply_text_are_kept_for_the_screen()
    {
        await _loop.StartAsync();

        _client.Raise("speech.transcript.final", 0, new { text = "add twelve dollars for lunch" });
        _client.Raise("assistant.text.final", 0, new { text = "Add $12.00 for lunch? Say yes to confirm." });

        Assert.Equal("add twelve dollars for lunch", _loop.LastTranscript);
        Assert.Equal("Add $12.00 for lunch? Say yes to confirm.", _loop.LastReply);
    }

    [Theory]
    [InlineData("STT_UNAVAILABLE", "Speech recognition isn't available right now.")]
    [InlineData("STT_NO_TRANSCRIPT", "I didn't catch that.")]
    [InlineData("TTS_UNAVAILABLE", "I couldn't speak that reply. The text is above.")]
    [InlineData("SOMETHING_NEW", "Something went wrong with voice.")]
    public async Task Core_errors_become_fixed_safe_sentences(string code, string expected)
    {
        await _loop.StartAsync();

        _client.Raise("error", 0, new { code, recoverable = true });

        Assert.Equal(expected, _loop.Message);
    }

    [Fact]
    public async Task Losing_the_connection_closes_the_mic_and_the_hotkey()
    {
        await _loop.StartAsync();
        await _loop.PressAsync();

        _client.Drop();
        for (var i = 0; i < 100 && _loop.State != LiveVoiceState.Error; i++)
        {
            await Task.Delay(10);
        }

        Assert.Equal(LiveVoiceState.Error, _loop.State);
        Assert.False(_loop.MicOpen);
        Assert.False(_hotkey.Enabled);
    }

    [Fact]
    public async Task Stopping_closes_everything_and_goes_off()
    {
        await _loop.StartAsync();
        await _loop.PressAsync();

        await _loop.StopAsync();

        Assert.Equal(LiveVoiceState.Off, _loop.State);
        Assert.False(_loop.MicOpen);
        Assert.False(_hotkey.Enabled);
        Assert.False(_client.IsConnected);
    }

    [Fact]
    public async Task Interrupt_cuts_playback_and_tells_core()
    {
        await _loop.StartAsync();
        _playback.Play(new byte[1], 1);

        await _loop.InterruptAsync();

        Assert.False(_playback.IsPlaying);
        await Settle(_client, sent => sent.Contains("interrupt"));
    }

    [Fact]
    public async Task Pressing_before_the_session_starts_does_nothing()
    {
        await _loop.PressAsync();

        Assert.Equal(0, _capture.Starts);
        Assert.Empty(_client.Snapshot());
    }
}
