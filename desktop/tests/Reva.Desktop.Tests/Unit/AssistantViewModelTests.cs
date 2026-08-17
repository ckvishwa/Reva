using Reva.Desktop.Contracts;
using Reva.Desktop.Services;
using Reva.Desktop.State;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class AssistantViewModelTests
{
    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly Func<string, CancellationToken, Task<CoreResult<TypedMessageResponse>>> _responder;
        private readonly Func<byte[], CancellationToken, Task<CoreResult<VoiceTranscriptionResponse>>>? _transcribeResponder;
        private readonly Func<string, string, CancellationToken, Task<CoreResult<byte[]>>>? _synthesizeResponder;

        public FakeCoreClient(
            Func<string, CancellationToken, Task<CoreResult<TypedMessageResponse>>> responder,
            Func<byte[], CancellationToken, Task<CoreResult<VoiceTranscriptionResponse>>>? transcribeResponder = null,
            Func<string, string, CancellationToken, Task<CoreResult<byte[]>>>? synthesizeResponder = null)
        {
            _responder = responder;
            _transcribeResponder = transcribeResponder;
            _synthesizeResponder = synthesizeResponder;
        }

        public int CallCount { get; private set; }

        public int TranscribeCallCount { get; private set; }

        public int SynthesizeCallCount { get; private set; }

        public List<string> ReceivedContents { get; } = new();

        public List<(string Text, string Language)> SpeechRequests { get; } = new();

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("AssistantViewModel never calls GetHealthAsync.");

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("AssistantViewModel never calls GetVersionAsync.");

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("AssistantViewModel never calls CreateMemoryAsync.");

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query, int limit, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("AssistantViewModel never calls QueryMemoriesAsync.");

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default)
        {
            CallCount++;
            ReceivedContents.Add(content);
            return _responder(content, cancellationToken);
        }

        public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
            byte[] wavAudio, CancellationToken cancellationToken = default)
        {
            TranscribeCallCount++;
            return _transcribeResponder!(wavAudio, cancellationToken);
        }

        public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(
            string text, string language, CancellationToken cancellationToken = default)
        {
            SynthesizeCallCount++;
            SpeechRequests.Add((text, language));
            return _synthesizeResponder!(text, language, cancellationToken);
        }
    }

    private sealed class FakeVoiceDevice : IVoiceDevice
    {
        private readonly TaskCompletionSource? _playbackStarted;
        private readonly TaskCompletionSource? _allowPlaybackToComplete;
        private readonly TaskCompletionSource? _recordingStarted;
        private readonly TaskCompletionSource? _allowRecordingToStart;
        private readonly Exception? _startException;
        private readonly Exception? _stopThrows;
        private readonly VoiceDeviceAvailability? _verifyResult;

        public FakeVoiceDevice(
            byte[]? recordedAudio = null,
            TaskCompletionSource? playbackStarted = null,
            TaskCompletionSource? allowPlaybackToComplete = null,
            TaskCompletionSource? recordingStarted = null,
            TaskCompletionSource? allowRecordingToStart = null,
            Exception? startException = null,
            bool isAvailable = true,
            VoiceDeviceAvailability? verifyResult = null,
            Exception? stopThrows = null)
        {
            RecordedAudio = recordedAudio ?? TestWav.Mono16k(TimeSpan.FromSeconds(1));
            _playbackStarted = playbackStarted;
            _allowPlaybackToComplete = allowPlaybackToComplete;
            _recordingStarted = recordingStarted;
            _allowRecordingToStart = allowRecordingToStart;
            _startException = startException;
            IsAvailable = isAvailable;
            _verifyResult = verifyResult;
            _stopThrows = stopThrows;
        }

        // Constructor-time IsAvailable seeds AssistantViewModel's initial
        // _isVoiceAvailable (mirroring WindowsVoiceDevice.IsAvailable, which
        // is false until VerifyAvailabilityAsync confirms the mic).
        // _verifyResult, when supplied, lets a test simulate that real-world
        // "starts unverified, verification then succeeds/fails independently"
        // shape instead of VerifyAvailabilityAsync just echoing IsAvailable.
        public bool IsAvailable { get; init; } = true;

        public byte[] RecordedAudio { get; }

        public int StartCallCount { get; private set; }

        public int StopCallCount { get; private set; }

        public int PlayCallCount { get; private set; }

        public int StopPlaybackCallCount { get; private set; }

        public Task<VoiceDeviceAvailability> VerifyAvailabilityAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(
                _verifyResult
                ?? (IsAvailable
                    ? VoiceDeviceAvailability.Ready()
                    : VoiceDeviceAvailability.NoMicrophoneFound()));

        public async Task StartRecordingAsync(CancellationToken cancellationToken = default)
        {
            StartCallCount++;
            _recordingStarted?.SetResult();
            if (_startException is not null)
            {
                throw _startException;
            }

            if (_allowRecordingToStart is not null)
            {
                await _allowRecordingToStart.Task.WaitAsync(cancellationToken);
            }
        }

        public Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default)
        {
            StopCallCount++;
            if (_stopThrows is not null)
            {
                throw _stopThrows;
            }

            return Task.FromResult(RecordedAudio);
        }

        public async Task PlayAsync(byte[] wavAudio, CancellationToken cancellationToken = default)
        {
            PlayCallCount++;
            _playbackStarted?.SetResult();
            if (_allowPlaybackToComplete is not null)
            {
                await _allowPlaybackToComplete.Task.WaitAsync(cancellationToken);
            }
        }

        public void StopPlayback()
        {
            StopPlaybackCallCount++;
        }

        public void CancelRecording()
        {
        }
    }

    private sealed class FakeCoreLifecycle : IRevaCoreLifecycle
    {
        public CoreLifecycleState State { get; set; } = CoreLifecycleState.Connected;

        public string StatusText => "Core Connected";

        public event EventHandler? StateChanged;

        public void RaiseStateChanged() => StateChanged?.Invoke(this, EventArgs.Empty);

        public Task StartAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;

        public void StopMonitoring()
        {
        }
    }

    private static TypedMessageResponse SuccessResponse(string reply) =>
        new(SchemaVersion: 1, CorrelationId: Guid.NewGuid().ToString(), Reply: reply, MemoryCreated: null);

    private static VoiceTranscriptionResponse SuccessTranscription(string text = "hello REVA") =>
        new(SchemaVersion: 1, Text: text, Language: "en", DurationMs: 900);

    private static FakeCoreClient ImmediateSuccessClient(string reply = "Received: hi") =>
        new((_, _) => Task.FromResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse(reply))));

    [Fact]
    public void InitialState_IsEmptyAndNotPending()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient());

        Assert.Empty(viewModel.Messages);
        Assert.False(viewModel.IsPending);
        Assert.Null(viewModel.ErrorMessage);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("\t\n")]
    public async Task SendMessageAsync_WhitespaceOnly_DoesNothing(string whitespace)
    {
        var client = ImmediateSuccessClient();
        var viewModel = new AssistantViewModel(client) { ComposerText = whitespace };

        await viewModel.SendMessageAsync();

        Assert.Equal(0, client.CallCount);
        Assert.Empty(viewModel.Messages);
        Assert.False(viewModel.IsPending);
    }

    [Fact]
    public async Task SendMessageAsync_ValidSubmit_MakesExactlyOneCoreRequest()
    {
        var client = ImmediateSuccessClient();
        var viewModel = new AssistantViewModel(client) { ComposerText = "hello REVA" };

        await viewModel.SendMessageAsync();

        Assert.Equal(1, client.CallCount);
        Assert.Equal(new[] { "hello REVA" }, client.ReceivedContents);
    }

    [Fact]
    public async Task SendMessageAsync_ClearsComposerAfterSubmit()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient()) { ComposerText = "hello REVA" };

        await viewModel.SendMessageAsync();

        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task SendMessageAsync_AppendsUserMessage_BeforeCoreResponds()
    {
        var tcs = new TaskCompletionSource<CoreResult<TypedMessageResponse>>();
        var client = new FakeCoreClient((_, _) => tcs.Task);
        var viewModel = new AssistantViewModel(client) { ComposerText = "hello REVA" };

        var sendTask = viewModel.SendMessageAsync();

        Assert.Single(viewModel.Messages);
        Assert.Equal(AssistantMessageRole.User, viewModel.Messages[0].Role);
        Assert.Equal("hello REVA", viewModel.Messages[0].Text);

        tcs.SetResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("ok")));
        await sendTask;
    }

    [Fact]
    public async Task SendMessageAsync_SetsIsPending_WhileRequestInFlight()
    {
        var tcs = new TaskCompletionSource<CoreResult<TypedMessageResponse>>();
        var client = new FakeCoreClient((_, _) => tcs.Task);
        var viewModel = new AssistantViewModel(client) { ComposerText = "hello REVA" };

        var sendTask = viewModel.SendMessageAsync();

        Assert.True(viewModel.IsPending);

        tcs.SetResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("ok")));
        await sendTask;

        Assert.False(viewModel.IsPending);
    }

    [Fact]
    public async Task SendMessageAsync_DuplicateSubmissionWhilePending_IsBlocked()
    {
        var tcs = new TaskCompletionSource<CoreResult<TypedMessageResponse>>();
        var client = new FakeCoreClient((_, _) => tcs.Task);
        var viewModel = new AssistantViewModel(client) { ComposerText = "hello REVA" };

        var firstSend = viewModel.SendMessageAsync();
        viewModel.ComposerText = "a second message";
        await viewModel.SendMessageAsync(); // should be a no-op: IsPending is true

        Assert.Equal(1, client.CallCount);
        Assert.Single(viewModel.Messages);

        tcs.SetResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("ok")));
        await firstSend;
    }

    [Fact]
    public async Task SendMessageAsync_Success_AppendsExactlyOneAssistantMessage()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient("Received: hello REVA"))
        {
            ComposerText = "hello REVA",
        };

        await viewModel.SendMessageAsync();

        Assert.Equal(2, viewModel.Messages.Count);
        Assert.Equal(AssistantMessageRole.Assistant, viewModel.Messages[1].Role);
        Assert.Equal("Received: hello REVA", viewModel.Messages[1].Text);
        Assert.Null(viewModel.ErrorMessage);
    }

    [Fact]
    public async Task SendMessageAsync_Failure_SetsSafeErrorMessage_AndAddsNoAssistantMessage()
    {
        var client = new FakeCoreClient((_, _) => Task.FromResult(
            CoreResult<TypedMessageResponse>.Failure(CoreErrorKind.CoreUnavailable, "REVA Core is not reachable.")));
        var viewModel = new AssistantViewModel(client) { ComposerText = "hello REVA" };

        await viewModel.SendMessageAsync();

        Assert.Equal("REVA Core is not reachable.", viewModel.ErrorMessage);
        Assert.Single(viewModel.Messages); // user message only, no assistant reply
    }

    [Fact]
    public async Task SendMessageAsync_IsPending_ResetsAfterSuccess()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient()) { ComposerText = "hi" };

        await viewModel.SendMessageAsync();

        Assert.False(viewModel.IsPending);
    }

    [Fact]
    public async Task SendMessageAsync_IsPending_ResetsAfterFailure()
    {
        var client = new FakeCoreClient((_, _) => Task.FromResult(
            CoreResult<TypedMessageResponse>.Failure(CoreErrorKind.CoreTimeout, "REVA Core did not respond in time.")));
        var viewModel = new AssistantViewModel(client) { ComposerText = "hi" };

        await viewModel.SendMessageAsync();

        Assert.False(viewModel.IsPending);
    }

    [Fact]
    public async Task SendMessageAsync_ErrorMessage_IsExactlySafeMessage_NoExtraContent()
    {
        const string safeMessage = "REVA Core reported an internal error.";
        var client = new FakeCoreClient((_, _) => Task.FromResult(
            CoreResult<TypedMessageResponse>.Failure(CoreErrorKind.CoreServerFailure, safeMessage)));
        var viewModel = new AssistantViewModel(client) { ComposerText = "hi" };

        await viewModel.SendMessageAsync();

        // Exact equality, not just "contains" — proves the ViewModel never
        // appends exception text, response bodies, or any other detail to
        // whatever RevaCoreClient already decided was safe to show.
        Assert.Equal(safeMessage, viewModel.ErrorMessage);
    }

    [Fact]
    public async Task SendMessageAsync_NeverExposesTokenValue_InMessagesOrError()
    {
        const string tokenLookingValue = "sk-should-never-appear-anywhere";
        var client = new FakeCoreClient((_, _) => Task.FromResult(
            CoreResult<TypedMessageResponse>.Failure(CoreErrorKind.CoreUnauthorized, "REVA authorization is unavailable.")));
        var viewModel = new AssistantViewModel(client) { ComposerText = "hi" };

        await viewModel.SendMessageAsync();

        Assert.DoesNotContain(tokenLookingValue, viewModel.ErrorMessage);
        Assert.DoesNotContain(viewModel.Messages, m => m.Text.Contains(tokenLookingValue));
    }

    [Fact]
    public async Task VoiceTurn_PressBeginsRecordingOnce()
    {
        var voiceDevice = new FakeVoiceDevice();
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice);

        await viewModel.StartVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StartCallCount);
        Assert.Equal(0, voiceDevice.StopCallCount);
        Assert.True(viewModel.IsMicrophoneActive);
        Assert.Equal(VoiceUiState.Listening, viewModel.VoiceState);
        Assert.Equal("Listening", viewModel.VoiceStatusText);
    }

    [Fact]
    public async Task VoiceTurn_PressClearsStaleErrorFromPreviousTurn()
    {
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromMilliseconds(100)));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // too short — leaves an error
        Assert.NotNull(viewModel.VoiceErrorMessage);

        await viewModel.StartVoiceInputAsync();

        Assert.Null(viewModel.VoiceErrorMessage);
        Assert.Equal(VoiceUiState.Listening, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceTurn_ReleaseStopsOnce_TranscribesOnce_PopulatesComposer_NeverSendsOrSpeaks()
    {
        var client = TranscribingClient("hello REVA");
        var voiceDevice = new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1)));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StartCallCount);
        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
        Assert.Equal(0, client.CallCount);
        Assert.Equal(0, client.SynthesizeCallCount);
        Assert.Equal(0, voiceDevice.PlayCallCount);
        Assert.Equal("hello REVA", viewModel.ComposerText);
        Assert.Empty(viewModel.Messages); // nothing auto-sent to the transcript
        Assert.Equal(VoiceUiState.TranscriptionReady, viewModel.VoiceState);
        Assert.Equal("Transcription Ready", viewModel.VoiceStatusText);
        Assert.False(viewModel.IsMicrophoneActive);
    }

    [Fact]
    public async Task VoiceTurn_ExistingComposerDraftIsPreserved_TranscriptIsAppended()
    {
        var client = TranscribingClient("and also this");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));
        viewModel.ComposerText = "typed draft";

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal("typed draft and also this", viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_EmptyTranscriptIsTreatedAsFailure_NotReady()
    {
        var client = TranscribingClient("   ");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
        Assert.NotNull(viewModel.VoiceErrorMessage);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_CanceledPointerStopsSafely()
    {
        var viewModel = new AssistantViewModel(
            TranscribingClient("hello"),
            new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // pointer-canceled routes through the same method

        Assert.False(viewModel.IsMicrophoneActive);
    }

    [Fact]
    public async Task VoiceTurn_DuplicateReleaseIsIgnored_StopsExactlyOnce()
    {
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1)));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // e.g. release followed by capture-lost

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
    }

    [Fact]
    public async Task VoiceTurn_ReleaseWhileStartupInProgress_WaitsThenStopsOnce()
    {
        var recordingStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var allowRecordingToStart = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(
            recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1)),
            recordingStarted: recordingStarted,
            allowRecordingToStart: allowRecordingToStart);
        var viewModel = new AssistantViewModel(client, voiceDevice);

        var startTask = viewModel.StartVoiceInputAsync();
        await recordingStarted.Task;
        var finishTask = viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, voiceDevice.StopCallCount);

        allowRecordingToStart.SetResult();
        await startTask;
        await finishTask;

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
    }

    [Fact]
    public async Task VoiceTurn_CancellationRestoresReadyState()
    {
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(stopThrows: new OperationCanceledException());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
        Assert.False(viewModel.IsVoiceBusy);
        Assert.True(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public async Task VoiceTurn_EmptyRecordingIsRejectedBeforeTranscription()
    {
        var client = NeverTranscribingClient();
        var voiceDevice = new FakeVoiceDevice(recordedAudio: Array.Empty<byte>());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(0, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
        Assert.NotNull(viewModel.VoiceErrorMessage);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_UnderTwoHundredFiftyMillisecondsIsRejectedBeforeTranscription()
    {
        var client = NeverTranscribingClient();
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromMilliseconds(100))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
        Assert.Contains("too short", viewModel.VoiceErrorMessage!, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_ExactlyTwoHundredFiftyMillisecondsIsAccepted()
    {
        var client = TranscribingClient("ok");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromMilliseconds(250))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionReady, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceTurn_MalformedWavIsRejectedBeforeTranscription()
    {
        var client = NeverTranscribingClient();
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 }));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceTurn_TranscriptionFailure_ServiceUnavailable_ShowsSttUnavailable_NeverAddsToChat()
    {
        var client = FailingTranscriptionClient(CoreErrorKind.CoreUnavailable, "REVA voice is unavailable.");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Empty(viewModel.Messages);
        Assert.Equal(0, client.CallCount);
        Assert.Equal("REVA voice is unavailable.", viewModel.VoiceErrorMessage);
        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_TranscriptionFailure_Timeout_ShowsSttUnavailable_WithVoiceSpecificMessage()
    {
        var client = FailingTranscriptionClient(CoreErrorKind.CoreTimeout, "REVA voice did not respond in time.");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal("REVA voice did not respond in time.", viewModel.VoiceErrorMessage);
        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceFailure_DoesNotBreakTypedChat()
    {
        var client = ImmediateSuccessClient("Received: typed still works");
        var voiceDevice = new FakeVoiceDevice(
            startException: new VoiceCaptureException(VoiceDeviceAvailability.NoMicrophoneFound()));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        viewModel.ComposerText = "typed still works";
        await viewModel.SendMessageAsync();

        Assert.Equal(VoiceUiState.NoMicrophone, viewModel.VoiceState);
        Assert.Equal(1, client.CallCount);
        Assert.Equal(2, viewModel.Messages.Count);
        Assert.Equal("typed still works", viewModel.Messages[0].Text);
        Assert.Equal("Received: typed still works", viewModel.Messages[1].Text);
    }

    [Fact]
    public async Task VoiceTurn_PermissionDenied_ShowsExactRequiredMessage()
    {
        var voiceDevice = new FakeVoiceDevice(
            startException: new VoiceCaptureException(VoiceDeviceAvailability.PermissionDenied()));
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice);

        await viewModel.StartVoiceInputAsync();

        Assert.False(viewModel.IsMicrophoneActive);
        Assert.False(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.PermissionDenied, viewModel.VoiceState);
        Assert.Equal(
            "Microphone permission is disabled. Enable it in Windows Settings.",
            viewModel.VoiceErrorMessage);
    }

    [Fact]
    public async Task TtsUnavailable_DoesNotDisableVoiceButton()
    {
        // No TTS call path exists in this slice — this proves
        // SynthesizeSpeechAsync is never invoked during a full successful turn,
        // so whatever state TTS is in cannot gate CanStartVoiceInput.
        var client = TranscribingClient("hi");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.SynthesizeCallCount);
        Assert.True(viewModel.CanStartVoiceInput);
    }

    private static FakeCoreClient TranscribingClient(string text) => new(
        (_, _) => throw new NotSupportedException("transcription-only slice must never call SendMessageAsync"),
        (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription(text))),
        (_, _, _) => throw new NotSupportedException("transcription-only slice must never call SynthesizeSpeechAsync"));

    private static FakeCoreClient NeverTranscribingClient() => new(
        (_, _) => throw new NotSupportedException(),
        (_, _) => throw new NotSupportedException("must be rejected before any Core call"),
        (_, _, _) => throw new NotSupportedException());

    private static FakeCoreClient FailingTranscriptionClient(CoreErrorKind kind, string message) => new(
        (_, _) => throw new NotSupportedException(),
        (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Failure(kind, message)),
        (_, _, _) => throw new NotSupportedException());

    [Fact]
    public void CanStartVoiceInput_MicReadyButCoreDisconnected_IsFalse()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.False(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void VoiceState_MicReadyButCoreDisconnected_ReportsSttUnavailable_NotReadyToTalk()
    {
        // The status must explain the disabled button. "Ready to Talk" next to a
        // greyed-out control is the contradiction this slice removes.
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);
        Assert.Equal("STT Unavailable", viewModel.VoiceStatusText);
    }

    [Fact]
    public void CanStartVoiceInput_MicReadyAndCoreConnected_IsTrue()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.True(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
    }

    [Fact]
    public void CanStartVoiceInput_NoLifecycleProvided_DefaultsToTrueWhenMicReady()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice());

        Assert.True(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void CoreDisconnectsAfterConstruction_UpdatesButtonAndStatusTogether()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);
        Assert.True(viewModel.CanStartVoiceInput);

        lifecycle.State = CoreLifecycleState.Unavailable;
        lifecycle.RaiseStateChanged();

        Assert.False(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);

        lifecycle.State = CoreLifecycleState.Connected;
        lifecycle.RaiseStateChanged();

        Assert.True(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
    }

    [Fact]
    public void CoreStateChange_DoesNotOverrideMicSpecificFailureStates()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var voiceDevice = new FakeVoiceDevice(isAvailable: false);
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice, lifecycle);

        lifecycle.RaiseStateChanged();

        Assert.NotEqual(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
    }

    // Regression coverage for the real-world startup sequence:
    // WindowsVoiceDevice.IsAvailable is false until VerifyAvailabilityAsync
    // confirms the mic, so the constructor always seeds VoiceState at
    // CheckingMicrophone. Root_Loaded then calls RefreshVoiceAvailabilityAsync
    // once at startup. Before the fix, that call updated VoiceStatusText and
    // _isVoiceAvailable directly but never touched VoiceState, so VoiceState
    // stayed stuck at CheckingMicrophone forever — which made every later
    // Core StateChanged event's RefreshIdleVoiceState() no-op (its guard
    // treats CheckingMicrophone as "leave it alone"), leaving VoiceStatusText
    // permanently out of sync with CanStartVoiceInput/CanUseVoiceButton.
    [Fact]
    public async Task RefreshVoiceAvailabilityAsync_MicBecomesReadyButCoreDisconnected_MovesOffCheckingMicrophone_ToSttUnavailable()
    {
        var voiceDevice = new FakeVoiceDevice(isAvailable: false, verifyResult: VoiceDeviceAvailability.Ready());
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice, lifecycle);

        // Sanity: constructor seeds CheckingMicrophone because the device
        // isn't verified yet (mirrors the real device's unverified default).
        Assert.Equal(VoiceUiState.CheckingMicrophone, viewModel.VoiceState);

        await viewModel.RefreshVoiceAvailabilityAsync();

        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);
        Assert.Equal("STT Unavailable", viewModel.VoiceStatusText);
        Assert.False(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public async Task RefreshVoiceAvailabilityAsync_MicBecomesReadyAndCoreConnected_MovesOffCheckingMicrophone_ToReadyToTalk()
    {
        var voiceDevice = new FakeVoiceDevice(isAvailable: false, verifyResult: VoiceDeviceAvailability.Ready());
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice, lifecycle);

        Assert.Equal(VoiceUiState.CheckingMicrophone, viewModel.VoiceState);

        await viewModel.RefreshVoiceAvailabilityAsync();

        Assert.Equal(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
        Assert.Equal("Ready to Talk", viewModel.VoiceStatusText);
        Assert.True(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void ComposerSource_Initially_IsTyped()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient());

        Assert.Equal(CommandSource.Typed, viewModel.ComposerSource);
    }

    [Fact]
    public async Task ComposerSource_AfterTranscription_IsTranscribed()
    {
        var client = TranscribingClient("confirm");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(CommandSource.Transcribed, viewModel.ComposerSource);
    }

    [Fact]
    public async Task ComposerSource_AfterUserEditsTranscribedText_ReturnsToTyped()
    {
        // Editing is an act of authorship — once the user has touched the text
        // it is theirs, and a typed confirm should work normally.
        var client = TranscribingClient("confirm");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));
        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        viewModel.ComposerText = "confirm";   // simulates SyncComposerTextFromTextBox

        Assert.Equal(CommandSource.Typed, viewModel.ComposerSource);
    }

    [Fact]
    public async Task ComposerSource_AfterSend_ResetsToTyped()
    {
        // TranscribingClient() can't be reused here — its SendMessageAsync
        // responder deliberately throws, since every other test using it
        // asserts the transcription-only slice never sends. This test needs
        // both paths to succeed: transcribe, then actually send.
        var client = new FakeCoreClient(
            (_, _) => Task.FromResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("ok"))),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))));
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));
        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        await viewModel.SendMessageAsync();

        Assert.Equal(CommandSource.Typed, viewModel.ComposerSource);
    }
}
