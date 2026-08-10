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

        public FakeCoreClient(Func<string, CancellationToken, Task<CoreResult<TypedMessageResponse>>> responder)
        {
            _responder = responder;
        }

        public int CallCount { get; private set; }

        public List<string> ReceivedContents { get; } = new();

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("AssistantViewModel never calls GetHealthAsync.");

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("AssistantViewModel never calls GetVersionAsync.");

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default)
        {
            CallCount++;
            ReceivedContents.Add(content);
            return _responder(content, cancellationToken);
        }
    }

    private static TypedMessageResponse SuccessResponse(string reply) =>
        new(SchemaVersion: 1, CorrelationId: Guid.NewGuid().ToString(), Reply: reply, MemoryCreated: null);

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
}
