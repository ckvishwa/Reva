using Reva.Desktop.Services;
using Reva.Desktop.ViewModels;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Tests.Voice;

public class LiveVoiceViewModelTests
{
    private static (LiveVoiceViewModel vm, VoiceLoopController loop, FakeCapture capture, FakeClient client) Make()
    {
        var client = new FakeClient();
        var capture = new FakeCapture();
        var loop = new VoiceLoopController(client, capture, new FakePlayback(), new FakeHotkey(), _ => Task.CompletedTask);
        return (new LiveVoiceViewModel(loop), loop, capture, client);
    }

    [Fact]
    public async Task The_state_text_follows_the_loop_and_the_mic_dot_follows_the_device()
    {
        var (vm, _, _, _) = Make();
        Assert.False(vm.IsOn);
        Assert.Equal("Voice is off.", vm.StateText);

        await vm.TurnOnAsync();
        Assert.True(vm.IsOn);
        Assert.False(vm.MicOpen);
        Assert.Equal("Hold Ctrl+Space or the button to talk.", vm.StateText);

        await vm.TalkPressedAsync();
        Assert.True(vm.MicOpen);
        Assert.Equal("Listening…", vm.StateText);

        await vm.TalkReleasedAsync();
        Assert.False(vm.MicOpen);
    }

    [Fact]
    public async Task Property_changes_are_raised_through_the_post_hook()
    {
        var client = new FakeClient();
        var loop = new VoiceLoopController(client, new FakeCapture(), new FakePlayback(), null, _ => Task.CompletedTask);
        var posted = 0;
        var vm = new LiveVoiceViewModel(loop, action =>
        {
            posted++;
            action();
        });
        var raised = new List<string?>();
        vm.PropertyChanged += (_, e) => raised.Add(e.PropertyName);

        await vm.TurnOnAsync();

        Assert.True(posted > 0);
        Assert.Contains(nameof(LiveVoiceViewModel.StateText), raised);
        Assert.Contains(nameof(LiveVoiceViewModel.MicOpen), raised);
    }

    [Fact]
    public async Task Transcript_and_reply_are_labelled_for_the_screen()
    {
        var (vm, _, _, client) = Make();
        await vm.TurnOnAsync();

        client.Raise("speech.transcript.final", 0, new { text = "hello" });
        client.Raise("assistant.text.final", 0, new { text = "Hi." });

        Assert.Equal("You: hello", vm.Transcript);
        Assert.Equal("REVA: Hi.", vm.Reply);
    }

    [Fact]
    public async Task Choosing_a_microphone_sets_the_device_and_a_vanished_one_falls_back_to_default()
    {
        var (vm, loop, _, _) = Make();
        vm.RefreshMicrophones();
        var desk = Assert.Single(vm.Microphones);

        vm.SelectedMicrophone = desk;
        Assert.Equal("mic-1", loop.DeviceId);

        vm.SelectedMicrophone = new AudioDeviceInfo("mic-gone", "Unplugged", false);
        vm.RefreshMicrophones();
        Assert.Null(vm.SelectedMicrophone);
        Assert.Null(loop.DeviceId);
        await Task.CompletedTask;
    }
}

public class ArbitratedAudioCaptureTests
{
    private sealed class Inner : IAudioCapture
    {
        public bool IsOpen { get; private set; }
        public bool FailStart;

        public event Action<byte[]>? Frame;

        public event Action? Lost;

        public IReadOnlyList<AudioDeviceInfo> ListDevices() => Array.Empty<AudioDeviceInfo>();

        public void Start(string? deviceId)
        {
            if (FailStart)
            {
                throw new CaptureStartException(CaptureFailure.NoDevice);
            }

            IsOpen = true;
        }

        public void Stop() => IsOpen = false;

        public void Unplug()
        {
            IsOpen = false;
            Lost?.Invoke();
        }

        public void Emit(byte[] pcm) => Frame?.Invoke(pcm);

        public void Dispose()
        {
        }
    }

    [Fact]
    public async Task The_lease_is_held_while_the_mic_runs_and_freed_on_stop()
    {
        var arbiter = new MicrophoneArbiter();
        var capture = new ArbitratedAudioCapture(new Inner(), arbiter);

        capture.Start(null);
        Assert.Equal(MicrophoneOwner.HoldToTalk, arbiter.CurrentOwner);
        Assert.True(await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord) is null);

        capture.Stop();
        Assert.Null(arbiter.CurrentOwner);
    }

    [Fact]
    public async Task A_mic_held_by_another_feature_is_refused_without_starting_the_device()
    {
        var arbiter = new MicrophoneArbiter();
        await using var other = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);
        var inner = new Inner();
        var capture = new ArbitratedAudioCapture(inner, arbiter);

        var ex = Assert.Throws<CaptureStartException>(() => capture.Start(null));

        Assert.Equal(CaptureFailure.Failed, ex.Failure);
        Assert.False(inner.IsOpen);
        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
    }

    [Fact]
    public void A_device_that_fails_to_start_does_not_keep_the_lease()
    {
        var arbiter = new MicrophoneArbiter();
        var capture = new ArbitratedAudioCapture(new Inner { FailStart = true }, arbiter);

        Assert.Throws<CaptureStartException>(() => capture.Start(null));

        Assert.Null(arbiter.CurrentOwner);
    }

    [Fact]
    public void An_unplugged_device_frees_the_lease_and_reports_lost()
    {
        var arbiter = new MicrophoneArbiter();
        var inner = new Inner();
        var capture = new ArbitratedAudioCapture(inner, arbiter);
        var lost = 0;
        capture.Lost += () => lost++;
        capture.Start(null);

        inner.Unplug();

        Assert.Equal(1, lost);
        Assert.Null(arbiter.CurrentOwner);
    }

    [Fact]
    public async Task The_wake_word_hooks_run_before_start_and_after_stop()
    {
        var arbiter = new MicrophoneArbiter();
        var calls = new List<string>();
        var resumed = new TaskCompletionSource();
        var capture = new ArbitratedAudioCapture(
            new Inner(),
            arbiter,
            () =>
            {
                calls.Add("suspend");
                return Task.CompletedTask;
            },
            () =>
            {
                calls.Add("resume");
                resumed.TrySetResult();
                return Task.CompletedTask;
            });

        capture.Start(null);
        capture.Stop();
        await resumed.Task.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.Equal(new[] { "suspend", "resume" }, calls);
    }

    [Fact]
    public void Frames_pass_through()
    {
        var inner = new Inner();
        var capture = new ArbitratedAudioCapture(inner, new MicrophoneArbiter());
        byte[]? seen = null;
        capture.Frame += pcm => seen = pcm;

        inner.Emit(new byte[] { 1, 2 });

        Assert.Equal(new byte[] { 1, 2 }, seen);
    }
}
