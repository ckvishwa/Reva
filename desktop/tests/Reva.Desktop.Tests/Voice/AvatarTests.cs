using System.Text.Json;
using NAudio.Wave;
using Reva.Desktop.Avatar;
using Reva.Desktop.ViewModels;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Tests.Voice;

public class AvatarProtocolTests
{
    private static JsonElement Parse(string? json) => JsonDocument.Parse(json!).RootElement;

    [Fact]
    public void States_mouth_expressions_and_settings_are_built_exactly_as_the_schema_wants()
    {
        Assert.Equal("{\"type\":\"avatar.state\",\"state\":\"listening\",\"turn_epoch\":4}", AvatarProtocol.State("listening", 4));
        var mouth = Parse(AvatarProtocol.Mouth(120, 0.4321987, 3));
        Assert.Equal("avatar.mouth", mouth.GetProperty("type").GetString());
        Assert.Equal(120, mouth.GetProperty("t_ms").GetInt32());
        Assert.Equal(0.4322, mouth.GetProperty("rms").GetDouble());
        Assert.Equal(3, mouth.GetProperty("turn_epoch").GetInt32());
        Assert.Equal("{\"type\":\"avatar.expression\",\"name\":\"relaxed\",\"cause\":\"mood\"}", AvatarProtocol.Expression("relaxed", "mood", null));
        Assert.Equal(
            "{\"type\":\"avatar.settings\",\"enabled\":false,\"reduced_motion\":true,\"quality\":\"low\"}",
            AvatarProtocol.Settings(false, true, "low"));
        Assert.Equal("{\"type\":\"avatar.settings\",\"enabled\":true}", AvatarProtocol.Settings(true, null, null));
    }

    [Theory]
    [InlineData("dancing", 0)]
    [InlineData("idle", -1)]
    [InlineData("", 0)]
    public void An_invalid_state_is_never_built(string state, int epoch) => Assert.Null(AvatarProtocol.State(state, epoch));

    [Fact]
    public void A_mouth_level_is_clamped_and_nonsense_is_refused()
    {
        Assert.Equal(1.0, Parse(AvatarProtocol.Mouth(0, 7.5, 0)).GetProperty("rms").GetDouble());
        Assert.Equal(0.0, Parse(AvatarProtocol.Mouth(0, -3, 0)).GetProperty("rms").GetDouble());
        Assert.Null(AvatarProtocol.Mouth(0, double.NaN, 0));
        Assert.Null(AvatarProtocol.Mouth(0, double.PositiveInfinity, 0));
        Assert.Null(AvatarProtocol.Mouth(-1, 0.5, 0));
        Assert.Null(AvatarProtocol.Mouth(0, 0.5, -1));
    }

    [Fact]
    public void A_result_face_needs_a_verified_outcome_with_its_action_id()
    {
        Assert.Null(AvatarProtocol.Expression("happy", "verified_outcome", null));
        Assert.Null(AvatarProtocol.Expression("happy", "verified_outcome", "short"));
        var ok = Parse(AvatarProtocol.Expression("happy", "verified_outcome", "act-12345678"));
        Assert.Equal("act-12345678", ok.GetProperty("action_id").GetString());
        Assert.Null(AvatarProtocol.Expression("angry", "mood", null));
        Assert.Null(AvatarProtocol.Expression("happy", "flattery", null));
        Assert.Null(AvatarProtocol.Expression("happy", "mood", new string('x', 65)));
    }

    [Fact]
    public void Settings_refuse_an_unknown_quality() => Assert.Null(AvatarProtocol.Settings(true, null, "ultra"));

    [Theory]
    [InlineData("{\"type\":\"avatar.ready\"}", PageMessageKind.Ready)]
    [InlineData("{\"type\":\"avatar.error\",\"detail\":\"no model\"}", PageMessageKind.Error)]
    [InlineData("{\"type\":\"avatar.state\"}", PageMessageKind.Invalid)]
    [InlineData("not json", PageMessageKind.Invalid)]
    [InlineData("[]", PageMessageKind.Invalid)]
    [InlineData("", PageMessageKind.Invalid)]
    [InlineData(null, PageMessageKind.Invalid)]
    public void Only_ready_and_error_are_accepted_from_the_page(string? json, PageMessageKind expected) =>
        Assert.Equal(expected, AvatarProtocol.ParsePageMessage(json).Kind);

    [Fact]
    public void A_long_error_detail_is_cut_and_an_oversized_message_is_refused()
    {
        var detail = AvatarProtocol.ParsePageMessage("{\"type\":\"avatar.error\",\"detail\":\"" + new string((char)120, 2100) + "\"}");
        Assert.Equal(PageMessageKind.Invalid, detail.Kind); // over the 2000 byte limit
        var cut = AvatarProtocol.ParsePageMessage("{\"type\":\"avatar.error\",\"detail\":\"" + new string('x', 600) + "\"}");
        Assert.Equal(200, cut.Detail!.Length);
    }
}

public class AvatarNavigationPolicyTests
{
    [Theory]
    [InlineData("https://reva-avatar.local/index.html", true)]
    [InlineData("https://reva-avatar.local/avatar.js", true)]
    [InlineData("https://REVA-AVATAR.LOCAL/placeholder.vrm", true)]
    [InlineData("https://reva-avatar.local/reva-1.0.vrm", true)]
    [InlineData("http://reva-avatar.local/index.html", false)]
    [InlineData("https://reva-avatar.local:8443/index.html", false)]
    [InlineData("https://reva-avatar.local/other.js", false)]
    [InlineData("https://reva-avatar.local/../secret", false)]
    [InlineData("https://reva-avatar.local.evil.com/index.html", false)]
    [InlineData("https://user@reva-avatar.local/index.html", false)]
    [InlineData("https://example.com/", false)]
    [InlineData("file:///C:/Windows/win.ini", false)]
    [InlineData("data:text/html,hi", false)]
    [InlineData("about:blank", false)]
    [InlineData("ws://127.0.0.1:8756/v1/voice/sessions/x/events", false)]
    [InlineData("http://127.0.0.1:8756/v1/memories", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    public void Only_the_avatars_own_files_on_its_own_host_are_allowed(string? uri, bool allowed) =>
        Assert.Equal(allowed, AvatarNavigationPolicy.IsAllowed(uri));

    [Fact]
    public void The_page_loads_once_and_may_never_navigate_again()
    {
        Assert.True(AvatarNavigationPolicy.IsAllowedNavigation(AvatarNavigationPolicy.StartUrl, alreadyLoaded: false));
        Assert.False(AvatarNavigationPolicy.IsAllowedNavigation(AvatarNavigationPolicy.StartUrl, alreadyLoaded: true));
        Assert.False(AvatarNavigationPolicy.IsAllowedNavigation("https://example.com/", alreadyLoaded: false));
    }
}

public sealed class AvatarSettingsTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "reva-avatar-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        if (Directory.Exists(_dir))
        {
            Directory.Delete(_dir, recursive: true);
        }
    }

    [Fact]
    public void The_defaults_are_on_follow_windows_medium()
    {
        var settings = new AvatarSettingsStore(_dir).Load();

        Assert.Equal(new AvatarSettings(true, null, "medium"), settings);
        Assert.True(settings.EffectiveReducedMotion(systemAnimationsEnabled: false));
        Assert.False(settings.EffectiveReducedMotion(systemAnimationsEnabled: true));
        Assert.False(settings with { ReducedMotion = false } is { } off && off.EffectiveReducedMotion(false));
        Assert.True((settings with { ReducedMotion = true }).EffectiveReducedMotion(true));
    }

    [Fact]
    public void Settings_survive_a_restart_and_a_damaged_file_means_the_defaults()
    {
        var store = new AvatarSettingsStore(_dir);
        store.Save(new AvatarSettings(false, true, "low"));

        Assert.Equal(new AvatarSettings(false, true, "low"), new AvatarSettingsStore(_dir).Load());
        File.WriteAllText(Path.Combine(_dir, "desktop-avatar.json"), "{not json");
        Assert.Equal(AvatarSettings.Default, store.Load());
        File.WriteAllText(Path.Combine(_dir, "desktop-avatar.json"), "{\"enabled\":true,\"quality\":\"ultra\"}");
        Assert.Equal(AvatarSettings.Default, store.Load());
    }

    [Fact]
    public void The_view_model_saves_and_applies_every_change()
    {
        var applied = new List<AvatarSettings>();
        var vm = new AvatarSettingsViewModel(new AvatarSettingsStore(_dir), applied.Add);

        vm.Enabled = false;
        vm.MotionIndex = 1;
        vm.QualityIndex = 0;

        Assert.Equal(new AvatarSettings(false, true, "low"), applied[^1]);
        Assert.Equal(3, applied.Count);
        Assert.Equal(new AvatarSettings(false, true, "low"), new AvatarSettingsStore(_dir).Load());
        Assert.Equal(new AvatarSettings(false, true, "low"), new AvatarSettingsViewModel(new AvatarSettingsStore(_dir)).Current);
    }
}

public class LevelPacerTests
{
    [Fact]
    public void Items_come_out_after_the_delay_in_order()
    {
        var pacer = new LevelPacer<int>(delayMs: 40);
        pacer.Add(1, nowMs: 100);
        pacer.Add(2, nowMs: 116);

        Assert.Empty(pacer.TakeDue(139));
        Assert.Equal(new[] { 1 }, pacer.TakeDue(140));
        Assert.Equal(new[] { 2 }, pacer.TakeDue(300));
        Assert.Empty(pacer.TakeDue(400));
    }

    [Fact]
    public void A_full_queue_drops_the_oldest_and_clear_empties_it()
    {
        var pacer = new LevelPacer<int>(0, capacity: 3);
        for (var i = 1; i <= 5; i++)
        {
            pacer.Add(i, 0);
        }

        Assert.Equal(3, pacer.Count);
        Assert.Equal(new[] { 3, 4, 5 }, pacer.TakeDue(0));
        pacer.Add(9, 0);
        pacer.Clear();
        Assert.Equal(0, pacer.Count);
    }

    [Fact]
    public void The_delay_is_clamped()
    {
        Assert.Equal(500, new LevelPacer<int>(5000).DelayMs);
        Assert.Equal(0, new LevelPacer<int>(-5).DelayMs);
    }
}

public class MeteringSampleProviderTests
{
    private sealed class Tone : ISampleProvider
    {
        private readonly float _value;
        private int _left;

        public Tone(int rate, int channels, int frames, float value)
        {
            WaveFormat = WaveFormat.CreateIeeeFloatWaveFormat(rate, channels);
            _left = frames;
            _value = value;
        }

        public WaveFormat WaveFormat { get; }

        public int Read(float[] buffer, int offset, int count)
        {
            var frames = Math.Min(count / WaveFormat.Channels, _left);
            for (var i = 0; i < frames * WaveFormat.Channels; i++)
            {
                buffer[offset + i] = _value;
            }

            _left -= frames;
            return frames * WaveFormat.Channels;
        }
    }

    [Fact]
    public void It_reports_about_sixty_levels_a_second_with_the_right_loudness_and_leaves_the_audio_alone()
    {
        var levels = new List<(int Pos, double Rms)>();
        var meter = new MeteringSampleProvider(new Tone(24000, 1, 24000, 0.5f), (p, r) => levels.Add((p, r)));
        var buffer = new float[2400];
        var total = 0;
        int read;
        while ((read = meter.Read(buffer, 0, buffer.Length)) > 0)
        {
            Assert.All(buffer.Take(read), s => Assert.Equal(0.5f, s));
            total += read;
        }

        Assert.Equal(24000, total);
        Assert.InRange(levels.Count, 58, 61);
        Assert.All(levels, l => Assert.Equal(0.5, l.Rms, 3));
        Assert.True(levels.Zip(levels.Skip(1)).All(pair => pair.Second.Pos > pair.First.Pos));
        Assert.InRange(levels[^1].Pos, 980, 1000);
    }

    [Fact]
    public void Silence_reports_zero_and_stereo_is_averaged()
    {
        var silent = new List<double>();
        var quiet = new MeteringSampleProvider(new Tone(16000, 2, 1600, 0f), (_, r) => silent.Add(r));
        var buffer = new float[3200];
        while (quiet.Read(buffer, 0, buffer.Length) > 0)
        {
        }

        Assert.All(silent, r => Assert.Equal(0.0, r));
        Assert.NotEmpty(silent);
    }

    [Fact]
    public void Nothing_is_reported_once_the_audio_has_stopped_being_pulled()
    {
        var count = 0;
        var meter = new MeteringSampleProvider(new Tone(24000, 1, 24000, 0.5f), (_, _) => count++);
        meter.Read(new float[800], 0, 800); // a bit of audio, then the device stops reading
        var after = count;

        Thread.Sleep(50);

        Assert.Equal(after, count);
    }
}

internal sealed class FakeAvatarSink : IAvatarSink
{
    public readonly List<string> Posted = new();

    public event Action<PageMessage>? PageMessageReceived;

    public void Post(string json)
    {
        lock (Posted)
        {
            Posted.Add(json);
        }
    }

    public void PageSays(PageMessageKind kind) => PageMessageReceived?.Invoke(new PageMessage(kind, null));

    public string[] Snapshot()
    {
        lock (Posted)
        {
            return Posted.ToArray();
        }
    }

    public JsonElement[] OfType(string type) =>
        Snapshot().Select(j => JsonDocument.Parse(j).RootElement).Where(e => e.GetProperty("type").GetString() == type).ToArray();
}

public class AvatarDirectorTests
{
    private readonly FakeClient _client = new();
    private readonly FakeCapture _capture = new();
    private readonly FakePlayback _playback = new();
    private readonly FakeAvatarSink _sink = new();
    private readonly VoiceLoopController _loop;
    private readonly AvatarDirector _director;
    private long _now = 1000;

    public AvatarDirectorTests()
    {
        _loop = new VoiceLoopController(_client, _capture, _playback, null, _ => Task.CompletedTask);
        _director = new AvatarDirector(_loop, _sink, lipSyncDelayMs: 40, nowMs: () => _now);
    }

    private static string StateOf(JsonElement e) => e.GetProperty("state").GetString()!;

    [Fact]
    public async Task The_avatar_is_idle_until_the_microphone_is_really_open_then_listening_then_idle_again()
    {
        await _loop.StartAsync();
        Assert.Equal("idle", StateOf(_sink.OfType("avatar.state").Last()));

        await _loop.PressAsync();
        Assert.Equal("listening", StateOf(_sink.OfType("avatar.state").Last()));

        await _loop.ReleaseAsync();
        Assert.NotEqual("listening", StateOf(_sink.OfType("avatar.state").Last()));
    }

    [Fact]
    public void A_listening_label_without_an_open_microphone_shows_idle()
    {
        Assert.Equal("idle", AvatarDirector.AvatarStateFor(LiveVoiceState.Listening, micOpen: false));
        Assert.Equal("listening", AvatarDirector.AvatarStateFor(LiveVoiceState.Listening, micOpen: true));
    }

    [Theory]
    [InlineData(LiveVoiceState.Off, "idle")]
    [InlineData(LiveVoiceState.Connecting, "idle")]
    [InlineData(LiveVoiceState.Ready, "idle")]
    [InlineData(LiveVoiceState.Thinking, "thinking")]
    [InlineData(LiveVoiceState.Approval, "approval")]
    [InlineData(LiveVoiceState.Speaking, "speaking")]
    [InlineData(LiveVoiceState.Error, "error")]
    public void Every_voice_state_has_an_avatar_state(LiveVoiceState state, string expected) =>
        Assert.Equal(expected, AvatarDirector.AvatarStateFor(state, micOpen: false));

    [Fact]
    public async Task Core_states_reach_the_avatar_with_the_turn_epoch_including_approval()
    {
        await _loop.StartAsync();

        _client.Raise("session.state", 2, new { state = "reasoning" });
        _client.Raise("session.state", 2, new { state = "approval_pending" });
        _client.Raise("session.state", 3, new { state = "speaking" });

        var states = _sink.OfType("avatar.state").Select(e => (StateOf(e), e.GetProperty("turn_epoch").GetInt32())).ToList();
        Assert.Contains(("thinking", 2), states);
        Assert.Contains(("approval", 2), states);
        Assert.Equal(("speaking", 3), states[^1]);
    }

    [Fact]
    public async Task The_same_state_is_not_sent_twice()
    {
        await _loop.StartAsync();
        _client.Raise("session.state", 1, new { state = "reasoning" });
        var count = _sink.OfType("avatar.state").Length;

        _client.Raise("assistant.text.final", 1, new { text = "x" });
        _client.Raise("speech.transcript.final", 1, new { text = "y" });

        Assert.Equal(count, _sink.OfType("avatar.state").Length);
    }

    private async Task Speaking(int epoch)
    {
        await _loop.StartAsync();
        _client.Raise("session.state", epoch, new { state = "speaking" });
    }

    [Fact]
    public async Task The_mouth_follows_the_played_audio_after_the_lip_sync_delay()
    {
        await Speaking(2);

        _playback.EmitLevel(new PlaybackLevel(2, 100, 0.3));
        _director.Pump();
        Assert.Empty(_sink.OfType("avatar.mouth")); // not yet: the sound has not come out of the speakers

        _now += 41;
        _director.Pump();

        var mouth = _sink.OfType("avatar.mouth").Single();
        Assert.Equal(0.3, mouth.GetProperty("rms").GetDouble());
        Assert.Equal(2, mouth.GetProperty("turn_epoch").GetInt32());
        Assert.Equal(100, mouth.GetProperty("t_ms").GetInt32());
    }

    [Fact]
    public async Task Levels_from_an_older_turn_or_while_not_speaking_never_reach_the_mouth()
    {
        await Speaking(3);
        _playback.EmitLevel(new PlaybackLevel(2, 0, 0.9)); // an older reply
        _now += 100;
        _director.Pump();
        Assert.Empty(_sink.OfType("avatar.mouth"));

        _client.Raise("session.state", 3, new { state = "listening" });
        _playback.EmitLevel(new PlaybackLevel(3, 0, 0.9)); // not speaking any more
        _now += 100;
        _director.Pump();
        Assert.Empty(_sink.OfType("avatar.mouth"));
    }

    [Fact]
    public async Task An_interrupt_drops_queued_mouth_movement_instead_of_playing_it_out()
    {
        await Speaking(2);
        _playback.EmitLevel(new PlaybackLevel(2, 0, 0.8));
        _playback.EmitLevel(new PlaybackLevel(2, 16, 0.8));

        _client.Raise("session.state", 3, new { state = "listening" }); // barge-in: new epoch, no longer speaking
        _now += 200;
        _director.Pump();

        Assert.Empty(_sink.OfType("avatar.mouth"));
        Assert.Equal("idle", StateOf(_sink.OfType("avatar.state").Last())); // mic is not open, so not listening
    }

    [Fact]
    public async Task A_face_from_core_is_forwarded_only_when_it_is_valid()
    {
        await _loop.StartAsync();

        _client.Raise("assistant.text.final", 1, new { text = "t", avatar_event = new { type = "avatar.expression", name = "relaxed", cause = "mood" } });
        _client.Raise("assistant.text.final", 1, new { text = "t", avatar_event = new { type = "avatar.expression", name = "happy", cause = "verified_outcome" } });
        _client.Raise("assistant.text.final", 1, new { text = "t", avatar_event = new { type = "avatar.expression", name = "angry", cause = "mood" } });
        _client.Raise("assistant.text.final", 1, new { text = "t", avatar_event = new { type = "avatar.state", name = "happy", cause = "mood" } });
        _client.Raise("assistant.text.final", 1, new { text = "t", avatar_event = "nonsense" });
        _client.Raise("assistant.text.final", 1, new { text = "no face here" });
        _client.Raise("assistant.text.final", 1, new { text = "t", avatar_event = new { type = "avatar.expression", name = "happy", cause = "verified_outcome", action_id = "act-12345678" } });

        var faces = _sink.OfType("avatar.expression").Select(e => (e.GetProperty("name").GetString(), e.GetProperty("cause").GetString())).ToList();
        Assert.Equal(new[] { ("relaxed", "mood"), ("happy", "verified_outcome") }, faces);
    }

    [Fact]
    public void Settings_go_to_the_page_and_hiding_the_window_turns_drawing_off()
    {
        _director.ApplySettings(new AvatarSettings(true, null, "high"), systemAnimationsEnabled: false);
        var first = _sink.OfType("avatar.settings").Last();
        Assert.True(first.GetProperty("enabled").GetBoolean());
        Assert.True(first.GetProperty("reduced_motion").GetBoolean()); // Windows animations are off
        Assert.Equal("high", first.GetProperty("quality").GetString());

        _director.SetWindowVisible(false);
        Assert.False(_sink.OfType("avatar.settings").Last().GetProperty("enabled").GetBoolean());
        _director.SetWindowVisible(true);
        Assert.True(_sink.OfType("avatar.settings").Last().GetProperty("enabled").GetBoolean());

        _director.ApplySettings(new AvatarSettings(false, false, "low"), systemAnimationsEnabled: true);
        var off = _sink.OfType("avatar.settings").Last();
        Assert.False(off.GetProperty("enabled").GetBoolean());
        Assert.False(off.GetProperty("reduced_motion").GetBoolean());
    }

    [Fact]
    public async Task A_page_that_has_just_loaded_is_given_the_settings_and_the_current_state_again()
    {
        await _loop.StartAsync();
        _client.Raise("session.state", 5, new { state = "reasoning" });
        var before = _sink.Snapshot().Length;

        _sink.PageSays(PageMessageKind.Ready);

        var after = _sink.Snapshot().Skip(before).Select(j => JsonDocument.Parse(j).RootElement).ToList();
        Assert.Contains(after, e => e.GetProperty("type").GetString() == "avatar.settings");
        Assert.Contains(after, e => e.GetProperty("type").GetString() == "avatar.state" && StateOf(e) == "thinking" && e.GetProperty("turn_epoch").GetInt32() == 5);
        Assert.True(_director.PageReady);
    }

    [Fact]
    public async Task An_error_from_the_page_changes_nothing_and_the_director_stops_listening_when_disposed()
    {
        await _loop.StartAsync();
        var count = _sink.Snapshot().Length;

        _sink.PageSays(PageMessageKind.Error);
        Assert.Equal(count, _sink.Snapshot().Length);

        _director.Dispose();
        _client.Raise("session.state", 9, new { state = "reasoning" });
        Assert.Equal(count, _sink.Snapshot().Length);
    }
}
