using System.Diagnostics;
using Reva.Desktop.Contracts;
using Reva.Desktop.Services;
using Reva.Desktop.State;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class WakeWordCoordinatorTests
{
    [Fact]
    public async Task WakeOpenCommand_ReachesCommandRouter_AndNeverCoreChat()
    {
        var client = TranscribingClient("Hey Reva open chrome");
        var router = new RecordingCommandRouter(new CommandRouteResult(CommandOutcome.Executed, "Opened Google Chrome."));
        var assistant = new AssistantViewModel(client, commandRouter: router);
        var coordinator = NewCoordinator(client, assistant, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal(1, router.CallCount);
        Assert.Equal(("open chrome", CommandSource.Transcribed), router.Received.Single());
        Assert.Equal(0, client.CallCount);
        Assert.Equal(2, assistant.Messages.Count);
        Assert.Equal("Opened Google Chrome.", assistant.Messages[1].Text);
    }

    [Fact]
    public async Task WakeCloseCommand_CreatesConfirmation_ButDoesNotClose()
    {
        var client = TranscribingClient("Hey Reva close chrome");
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var assistant = new AssistantViewModel(client, commandRouter: new CommandRouter(executor));
        var coordinator = NewCoordinator(client, assistant, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal(1, executor.IsRunningCallCount);
        Assert.Equal(0, executor.CloseCallCount);
        Assert.Contains("Close Google Chrome?", assistant.Messages.Last().Text);
    }

    [Fact]
    public async Task WakeSpokenConfirm_CannotApproveClosure_ButTypedConfirmStillCan()
    {
        var client = TranscribingClient("Hey Reva close chrome", "Hey Reva confirm");
        var executor = new FakeAppExecutor { IsRunningResult = true };
        var assistant = new AssistantViewModel(client, commandRouter: new CommandRouter(executor));
        var coordinator = NewCoordinator(client, assistant, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();
        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal(0, executor.CloseCallCount);
        Assert.Equal("confirm", assistant.ComposerText);

        assistant.ComposerText = "confirm";
        await assistant.SendMessageAsync();

        Assert.Equal(1, executor.CloseCallCount);
    }

    [Fact]
    public async Task OrdinaryWakeTranscript_PopulatesComposer_WithoutCoreChat()
    {
        var client = TranscribingClient("Hey Reva remember milk");
        var router = new RecordingCommandRouter(new CommandRouteResult(CommandOutcome.NotACommand, null));
        var assistant = new AssistantViewModel(client, commandRouter: router);
        var coordinator = NewCoordinator(client, assistant, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal("remember milk", assistant.ComposerText);
        Assert.Equal(1, router.CallCount);
        Assert.Equal(0, client.CallCount);
        Assert.Empty(assistant.Messages);
    }

    [Fact]
    public async Task HoldToTalkBlocksWakeCapture()
    {
        var client = TranscribingClient("Hey Reva open chrome");
        var assistant = new AssistantViewModel(client, commandRouter: new RecordingCommandRouter(
            new CommandRouteResult(CommandOutcome.Executed, "Opened Google Chrome.")));
        var coordinator = NewCoordinator(client, assistant, out var detector, out var arbiter);
        await coordinator.EnableAsync(DefaultConfig());
        await coordinator.SuspendForHoldToTalkAsync();
        await using var holdLease = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.NotNull(holdLease);
        Assert.Equal(0, client.TranscribeCallCount);
    }

    [Fact]
    public async Task WakeCaptureBlocksHoldToTalk()
    {
        var client = TranscribingClient("Hey Reva open chrome");
        var assistant = new AssistantViewModel(client, commandRouter: new RecordingCommandRouter(
            new CommandRouteResult(CommandOutcome.Executed, "Opened Google Chrome.")));
        var wakeVoice = new BlockingVoiceDevice();
        var arbiter = new MicrophoneArbiter();
        var holdVoice = new ArbiterVoiceDevice(new FakeVoiceDevice(), arbiter);
        var coordinator = NewCoordinator(client, assistant, wakeVoice, arbiter, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await wakeVoice.Started.Task.WaitAsync(TimeSpan.FromSeconds(5));

        await Assert.ThrowsAsync<VoiceCaptureException>(() => holdVoice.StartRecordingAsync());

        wakeVoice.AllowStop.SetResult();
        await coordinator.WaitForTurnAsync();
    }

    [Fact]
    public async Task DetectorResumesAfterSttFailure()
    {
        var client = FailingTranscriptionClient(CoreErrorKind.CoreUnavailable, "REVA voice is unavailable.");
        var assistant = new AssistantViewModel(client, commandRouter: new RecordingCommandRouter(
            new CommandRouteResult(CommandOutcome.NotACommand, null)));
        var coordinator = NewCoordinator(client, assistant, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.True(detector.IsRunning);
        Assert.Equal(2, detector.StartCallCount);
    }

    [Fact]
    public async Task DetectorResumesAfterCancellation()
    {
        var client = ThrowingTranscriptionClient(new OperationCanceledException());
        var assistant = new AssistantViewModel(client, commandRouter: new RecordingCommandRouter(
            new CommandRouteResult(CommandOutcome.NotACommand, null)));
        var coordinator = NewCoordinator(client, assistant, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.True(detector.IsRunning);
        Assert.Equal(2, detector.StartCallCount);
    }

    [Fact]
    public async Task Logs_DoNotContainTranscriptAudioOrExceptionDetails()
    {
        const string transcript = "Hey Reva sensitive private transcript";
        const string exceptionDetail = "C:\\Secret\\device-failure";
        var client = TranscribingClient(transcript);
        var assistant = new AssistantViewModel(client, commandRouter: new RecordingCommandRouter(
            new CommandRouteResult(CommandOutcome.NotACommand, null)));
        var voice = new FakeVoiceDevice(stopException: new InvalidOperationException(exceptionDetail));
        var coordinator = NewCoordinator(client, assistant, voice, new MicrophoneArbiter(), out var detector);
        using var listener = new CapturingTraceListener();
        Trace.Listeners.Add(listener);

        try
        {
            await coordinator.EnableAsync(DefaultConfig());
            detector.RaiseDetected(WakePhrase.HeyReva);
            await coordinator.WaitForTurnAsync();
            var logText = string.Join(Environment.NewLine, listener.Messages);

            Assert.DoesNotContain(transcript, logText);
            Assert.DoesNotContain(exceptionDetail, logText);
            Assert.DoesNotContain(Convert.ToBase64String(TestWav.Mono16k(TimeSpan.FromMilliseconds(250))), logText);
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    private static WakeWordConfiguration DefaultConfig() =>
        new(new[] { new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f) });

    private static WakeWordCoordinator NewCoordinator(
        FakeCoreClient client,
        AssistantViewModel assistant,
        out FakeWakeWordDetector detector,
        out MicrophoneArbiter arbiter)
    {
        arbiter = new MicrophoneArbiter();
        detector = new FakeWakeWordDetector();
        return NewCoordinator(client, assistant, new FakeVoiceDevice(), arbiter, out detector);
    }

    private static WakeWordCoordinator NewCoordinator(
        FakeCoreClient client,
        AssistantViewModel assistant,
        out FakeWakeWordDetector detector)
    {
        return NewCoordinator(client, assistant, out detector, out _);
    }

    private static WakeWordCoordinator NewCoordinator(
        FakeCoreClient client,
        AssistantViewModel assistant,
        IVoiceDevice voiceDevice,
        MicrophoneArbiter arbiter,
        out FakeWakeWordDetector detector)
    {
        detector = new FakeWakeWordDetector();
        return new WakeWordCoordinator(
            detector,
            arbiter,
            voiceDevice,
            client,
            assistant,
            new FakeChimePlayer());
    }

    private sealed class RecordingCommandRouter : ICommandRouter
    {
        private readonly CommandRouteResult _result;

        public RecordingCommandRouter(CommandRouteResult result) => _result = result;

        public int CallCount { get; private set; }

        public List<(string Text, CommandSource Source)> Received { get; } = new();

        public Task<CommandRouteResult> RouteAsync(
            string text,
            CommandSource source,
            CancellationToken cancellationToken = default)
        {
            CallCount++;
            Received.Add((text, source));
            return Task.FromResult(_result);
        }
    }

    private sealed class FakeAppExecutor : IAppExecutor
    {
        public bool IsRunningResult { get; init; }
        public int IsRunningCallCount { get; private set; }
        public int CloseCallCount { get; private set; }

        public Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default) =>
            Task.FromResult(true);

        public Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
        {
            IsRunningCallCount++;
            return Task.FromResult(IsRunningResult);
        }

        public Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default)
        {
            CloseCallCount++;
            return Task.FromResult(AppCloseOutcome.CloseRequested);
        }
    }

    private sealed class FakeWakeWordDetector : IWakeWordDetector
    {
        public event EventHandler<WakeWordDetection>? Detected;

        public bool IsRunning { get; private set; }
        public int StartCallCount { get; private set; }
        public int StopCallCount { get; private set; }

        public Task StartAsync(
            WakeWordConfiguration configuration,
            IMicrophoneLease lease,
            CancellationToken cancellationToken = default)
        {
            StartCallCount++;
            IsRunning = true;
            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken cancellationToken = default)
        {
            StopCallCount++;
            IsRunning = false;
            return Task.CompletedTask;
        }

        public void RaiseDetected(WakePhrase phrase) =>
            Detected?.Invoke(this, new WakeWordDetection(phrase, DateTimeOffset.UtcNow));

        public ValueTask DisposeAsync()
        {
            IsRunning = false;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class FakeChimePlayer : IChimePlayer
    {
        public int PlayCallCount { get; private set; }

        public Task PlayAsync(CancellationToken cancellationToken = default)
        {
            PlayCallCount++;
            return Task.CompletedTask;
        }
    }

    private class FakeVoiceDevice : IVoiceDevice
    {
        private readonly Exception? _stopException;

        public FakeVoiceDevice(Exception? stopException = null) => _stopException = stopException;

        public bool IsAvailable => true;
        public int StartCallCount { get; private set; }
        public int StopCallCount { get; private set; }

        public Task<VoiceDeviceAvailability> VerifyAvailabilityAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(VoiceDeviceAvailability.Ready());

        public virtual Task StartRecordingAsync(CancellationToken cancellationToken = default)
        {
            StartCallCount++;
            return Task.CompletedTask;
        }

        public virtual Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default)
        {
            StopCallCount++;
            if (_stopException is not null)
            {
                throw _stopException;
            }

            return Task.FromResult(TestWav.Mono16k(TimeSpan.FromSeconds(1)));
        }

        public Task PlayAsync(byte[] wavAudio, CancellationToken cancellationToken = default) =>
            Task.CompletedTask;

        public void StopPlayback()
        {
        }

        public void CancelRecording()
        {
        }
    }

    private sealed class BlockingVoiceDevice : FakeVoiceDevice
    {
        public TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource AllowStop { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public override Task StartRecordingAsync(CancellationToken cancellationToken = default)
        {
            Started.SetResult();
            return Task.CompletedTask;
        }

        public override async Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default)
        {
            await AllowStop.Task.WaitAsync(cancellationToken);
            return TestWav.Mono16k(TimeSpan.FromSeconds(1));
        }
    }

    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly Queue<string> _transcripts;
        private readonly CoreError? _transcriptionFailure;
        private readonly Exception? _transcriptionException;

        public FakeCoreClient(
            IEnumerable<string>? transcripts = null,
            CoreError? transcriptionFailure = null,
            Exception? transcriptionException = null)
        {
            _transcripts = new Queue<string>(transcripts ?? Array.Empty<string>());
            _transcriptionFailure = transcriptionFailure;
            _transcriptionException = transcriptionException;
        }

        public int CallCount { get; private set; }
        public int TranscribeCallCount { get; private set; }

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content,
            CancellationToken cancellationToken = default)
        {
            CallCount++;
            throw new NotSupportedException("Wake-word tests must not call Core chat.");
        }

        public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
            byte[] wavAudio,
            CancellationToken cancellationToken = default)
        {
            TranscribeCallCount++;
            if (_transcriptionException is not null)
            {
                throw _transcriptionException;
            }

            if (_transcriptionFailure is not null)
            {
                return Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Failure(
                    _transcriptionFailure.Kind,
                    _transcriptionFailure.SafeMessage));
            }

            var text = _transcripts.Dequeue();
            return Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(
                new VoiceTranscriptionResponse(1, text, "en", 900)));
        }

        public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(
            string text,
            string language,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("Wake-word tests must not call TTS.");

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query,
            int limit,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }

    private static FakeCoreClient TranscribingClient(params string[] transcripts) =>
        new(transcripts);

    private static FakeCoreClient FailingTranscriptionClient(CoreErrorKind kind, string safeMessage) =>
        new(transcriptionFailure: new CoreError(kind, safeMessage));

    private static FakeCoreClient ThrowingTranscriptionClient(Exception exception) =>
        new(transcriptionException: exception);

    private sealed class CapturingTraceListener : TraceListener
    {
        public List<string> Messages { get; } = new();

        public override void Write(string? message)
        {
            if (message is not null)
            {
                Messages.Add(message);
            }
        }

        public override void WriteLine(string? message)
        {
            if (message is not null)
            {
                Messages.Add(message);
            }
        }
    }
}
