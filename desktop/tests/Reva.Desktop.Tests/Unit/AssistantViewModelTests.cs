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

        public FakeVoiceDevice(
            byte[]? recordedAudio = null,
            TaskCompletionSource? playbackStarted = null,
            TaskCompletionSource? allowPlaybackToComplete = null)
        {
            RecordedAudio = recordedAudio ?? new byte[] { 1, 2, 3 };
            _playbackStarted = playbackStarted;
            _allowPlaybackToComplete = allowPlaybackToComplete;
        }

        public bool IsAvailable { get; init; } = true;

        public byte[] RecordedAudio { get; }

        public int StartCallCount { get; private set; }

        public int StopCallCount { get; private set; }

        public int PlayCallCount { get; private set; }

        public int StopPlaybackCallCount { get; private set; }

        public Task StartRecordingAsync(CancellationToken cancellationToken = default)
        {
            StartCallCount++;
            return Task.CompletedTask;
        }

        public Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default)
        {
            StopCallCount++;
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
    public async Task VoiceTurn_TranscribesThenUsesExistingMessagePipelineThenSpeaksReply()
    {
        var client = new FakeCoreClient(
            (_, _) => Task.FromResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("Received: hello REVA"))),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello REVA"))),
            (_, _, _) => Task.FromResult(CoreResult<byte[]>.Success(new byte[] { 82, 73, 70, 70 })));
        var voiceDevice = new FakeVoiceDevice();
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();

        Assert.True(viewModel.IsMicrophoneActive);
        Assert.Equal("Listening…", viewModel.VoiceStatusText);

        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StartCallCount);
        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
        Assert.Equal(1, client.CallCount);
        Assert.Equal(new[] { "hello REVA" }, client.ReceivedContents);
        Assert.Equal(1, client.SynthesizeCallCount);
        Assert.Equal(("Received: hello REVA", "en"), client.SpeechRequests.Single());
        Assert.Equal(1, voiceDevice.PlayCallCount);
        Assert.Equal(2, viewModel.Messages.Count);
        Assert.Equal(AssistantMessageRole.User, viewModel.Messages[0].Role);
        Assert.Equal("hello REVA", viewModel.Messages[0].Text);
        Assert.Equal("Received: hello REVA", viewModel.Messages[1].Text);
        Assert.Equal("Voice Ready", viewModel.VoiceStatusText);
    }

    [Fact]
    public async Task VoiceTurn_TranscriptionFailure_DoesNotAddRecordingToChat()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Failure(
                CoreErrorKind.CoreUnavailable,
                "REVA voice is unavailable.")),
            (_, _, _) => throw new NotSupportedException());
        var viewModel = new AssistantViewModel(client, new FakeVoiceDevice());

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Empty(viewModel.Messages);
        Assert.Equal(0, client.CallCount);
        Assert.Equal("REVA voice is unavailable.", viewModel.VoiceErrorMessage);
        Assert.Equal("Voice Unavailable", viewModel.VoiceStatusText);
    }

    [Fact]
    public async Task VoiceTurn_SpeechFailure_KeepsAssistantTextVisible()
    {
        var client = new FakeCoreClient(
            (_, _) => Task.FromResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("Received: hello"))),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => Task.FromResult(CoreResult<byte[]>.Failure(
                CoreErrorKind.CoreUnavailable,
                "REVA voice is unavailable.")));
        var voiceDevice = new FakeVoiceDevice();
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(2, viewModel.Messages.Count);
        Assert.Equal("Received: hello", viewModel.Messages[1].Text);
        Assert.Equal(0, voiceDevice.PlayCallCount);
        Assert.Equal("REVA voice is unavailable.", viewModel.VoiceErrorMessage);
        Assert.Equal("Voice Unavailable", viewModel.VoiceStatusText);
    }

    [Fact]
    public async Task VoiceTurn_UsesTeluguLanguageForTeluguDominantAssistantOutput()
    {
        var client = new FakeCoreClient(
            (_, _) => Task.FromResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("ఇది సమాధానం"))),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => Task.FromResult(CoreResult<byte[]>.Success(new byte[] { 82, 73, 70, 70 })));
        var viewModel = new AssistantViewModel(client, new FakeVoiceDevice());

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(("ఇది సమాధానం", "te"), client.SpeechRequests.Single());
    }

    [Fact]
    public async Task StopSpeaking_HaltsActivePlaybackImmediately()
    {
        var playbackStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var allowPlaybackToComplete = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var client = new FakeCoreClient(
            (_, _) => Task.FromResult(CoreResult<TypedMessageResponse>.Success(SuccessResponse("Received: hello"))),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => Task.FromResult(CoreResult<byte[]>.Success(new byte[] { 82, 73, 70, 70 })));
        var voiceDevice = new FakeVoiceDevice(
            playbackStarted: playbackStarted,
            allowPlaybackToComplete: allowPlaybackToComplete);
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        var finishTask = viewModel.FinishVoiceInputAsync();
        await playbackStarted.Task;

        Assert.True(viewModel.IsSpeaking);
        Assert.Equal("Speaking…", viewModel.VoiceStatusText);

        viewModel.StopSpeaking();
        await finishTask;

        Assert.False(viewModel.IsSpeaking);
        Assert.True(voiceDevice.StopPlaybackCallCount > 0);
        Assert.Equal("Voice Ready", viewModel.VoiceStatusText);
    }
}
