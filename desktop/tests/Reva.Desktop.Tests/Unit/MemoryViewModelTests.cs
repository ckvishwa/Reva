using Reva.Desktop.Contracts;
using Reva.Desktop.Services;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class MemoryViewModelTests
{
    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly Func<string, CancellationToken, Task<CoreResult<MemoryCreateResponse>>>? _createResponder;
        private readonly Func<string, int, CancellationToken, Task<CoreResult<MemoryQueryResponse>>>? _queryResponder;

        public FakeCoreClient(
            Func<string, CancellationToken, Task<CoreResult<MemoryCreateResponse>>>? createResponder = null,
            Func<string, int, CancellationToken, Task<CoreResult<MemoryQueryResponse>>>? queryResponder = null)
        {
            _createResponder = createResponder;
            _queryResponder = queryResponder;
        }

        public int CreateCallCount { get; private set; }

        public int QueryCallCount { get; private set; }

        public List<string> ReceivedCreateContents { get; } = new();

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("MemoryViewModel never calls GetHealthAsync.");

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("MemoryViewModel never calls GetVersionAsync.");

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("MemoryViewModel never calls SendMessageAsync.");

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content, CancellationToken cancellationToken = default)
        {
            CreateCallCount++;
            ReceivedCreateContents.Add(content);
            return _createResponder!(content, cancellationToken);
        }

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query, int limit, CancellationToken cancellationToken = default)
        {
            QueryCallCount++;
            return _queryResponder!(query, limit, cancellationToken);
        }

        public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
            byte[] wavAudio, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("MemoryViewModel never calls TranscribeSpeechAsync.");

        public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(
            string text, string language, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("MemoryViewModel never calls SynthesizeSpeechAsync.");
    }

    private static MemoryCreateResponse SuccessCreateResponse() =>
        new(
            SchemaVersion: 1,
            Id: Guid.NewGuid().ToString(),
            Category: "note",
            CreatedAt: DateTimeOffset.UtcNow,
            CorrelationId: Guid.NewGuid().ToString());

    private static MemoryQueryResponse SuccessQueryResponse(params string[] contents) =>
        new(
            SchemaVersion: 1,
            Results: contents
                .Select(c => new MemoryQueryResponseItem(
                    SchemaVersion: 1,
                    Id: Guid.NewGuid().ToString(),
                    Content: c,
                    Category: "note",
                    Source: new MemorySourceReference(1, null, null, "device-1", "explicit_api_memory_creation"),
                    Tags: Array.Empty<string>(),
                    CreatedAt: DateTimeOffset.UtcNow,
                    UpdatedAt: DateTimeOffset.UtcNow))
                .ToList(),
            CorrelationId: Guid.NewGuid().ToString());

    private static FakeCoreClient ImmediateSuccessClient() =>
        new(
            createResponder: (_, _) => Task.FromResult(CoreResult<MemoryCreateResponse>.Success(SuccessCreateResponse())),
            queryResponder: (_, _, _) => Task.FromResult(CoreResult<MemoryQueryResponse>.Success(SuccessQueryResponse("cobalt"))));

    [Fact]
    public void InitialState_IsEmptyAndNotPending()
    {
        var viewModel = new MemoryViewModel(ImmediateSuccessClient());

        Assert.Equal(string.Empty, viewModel.MemoryText);
        Assert.False(viewModel.IsPending);
        Assert.Null(viewModel.StatusMessage);
        Assert.Null(viewModel.SearchResultText);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("\t\n")]
    public async Task RememberAsync_WhitespaceOnly_MakesNoRequest_AndCreatesNoMemory(string whitespace)
    {
        var client = ImmediateSuccessClient();
        var viewModel = new MemoryViewModel(client) { MemoryText = whitespace };

        await viewModel.RememberAsync();

        Assert.Equal(0, client.CreateCallCount);
        Assert.NotNull(viewModel.StatusMessage);
        Assert.False(viewModel.IsPending);
    }

    [Fact]
    public async Task RememberAsync_ValidSubmit_MakesExactlyOneCreateRequest()
    {
        var client = ImmediateSuccessClient();
        var viewModel = new MemoryViewModel(client) { MemoryText = "test-color-abc123 = cobalt" };

        await viewModel.RememberAsync();

        Assert.Equal(1, client.CreateCallCount);
        Assert.Equal(new[] { "test-color-abc123 = cobalt" }, client.ReceivedCreateContents);
    }

    [Fact]
    public async Task RememberAsync_Success_SetsStatusMessage_AndClearsMemoryText()
    {
        var viewModel = new MemoryViewModel(ImmediateSuccessClient()) { MemoryText = "remember this" };

        await viewModel.RememberAsync();

        Assert.Equal("Remembered.", viewModel.StatusMessage);
        Assert.Equal(string.Empty, viewModel.MemoryText);
    }

    [Fact]
    public async Task RememberAsync_Failure_SetsSafeErrorMessage_AndDoesNotClearMemoryText()
    {
        var client = new FakeCoreClient(
            createResponder: (_, _) => Task.FromResult(
                CoreResult<MemoryCreateResponse>.Failure(CoreErrorKind.CoreUnavailable, "REVA Core is not reachable.")));
        var viewModel = new MemoryViewModel(client) { MemoryText = "remember this" };

        await viewModel.RememberAsync();

        Assert.Equal("REVA Core is not reachable.", viewModel.StatusMessage);
        Assert.Equal("remember this", viewModel.MemoryText);
    }

    [Fact]
    public async Task RememberAsync_DuplicateSubmissionWhilePending_IsBlocked()
    {
        var tcs = new TaskCompletionSource<CoreResult<MemoryCreateResponse>>();
        var client = new FakeCoreClient(createResponder: (_, _) => tcs.Task);
        var viewModel = new MemoryViewModel(client) { MemoryText = "remember this" };

        var firstRemember = viewModel.RememberAsync();
        await viewModel.RememberAsync(); // should be a no-op: IsPending is true

        Assert.Equal(1, client.CreateCallCount);

        tcs.SetResult(CoreResult<MemoryCreateResponse>.Success(SuccessCreateResponse()));
        await firstRemember;
    }

    [Fact]
    public async Task RememberAsync_IsPending_TrueWhileInFlight_FalseAfter()
    {
        var tcs = new TaskCompletionSource<CoreResult<MemoryCreateResponse>>();
        var client = new FakeCoreClient(createResponder: (_, _) => tcs.Task);
        var viewModel = new MemoryViewModel(client) { MemoryText = "remember this" };

        var rememberTask = viewModel.RememberAsync();
        Assert.True(viewModel.IsPending);

        tcs.SetResult(CoreResult<MemoryCreateResponse>.Success(SuccessCreateResponse()));
        await rememberTask;

        Assert.False(viewModel.IsPending);
    }

    [Fact]
    public async Task RememberAsync_NeverExposesTokenValue_InStatusMessage()
    {
        const string tokenLookingValue = "sk-should-never-appear-anywhere";
        var client = new FakeCoreClient(
            createResponder: (_, _) => Task.FromResult(
                CoreResult<MemoryCreateResponse>.Failure(CoreErrorKind.CoreUnauthorized, "REVA authorization is unavailable.")));
        var viewModel = new MemoryViewModel(client) { MemoryText = "hi" };

        await viewModel.RememberAsync();

        Assert.DoesNotContain(tokenLookingValue, viewModel.StatusMessage);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public async Task SearchAsync_WhitespaceOnly_MakesNoRequest(string whitespace)
    {
        var client = ImmediateSuccessClient();
        var viewModel = new MemoryViewModel(client);

        await viewModel.SearchAsync(whitespace);

        Assert.Equal(0, client.QueryCallCount);
        Assert.NotNull(viewModel.SearchResultText);
    }

    [Fact]
    public async Task SearchAsync_ValidQuery_MakesExactlyOneQueryRequest()
    {
        var client = ImmediateSuccessClient();
        var viewModel = new MemoryViewModel(client);

        await viewModel.SearchAsync("cobalt");

        Assert.Equal(1, client.QueryCallCount);
    }

    [Fact]
    public async Task SearchAsync_Success_ShowsStoredContent()
    {
        var viewModel = new MemoryViewModel(ImmediateSuccessClient());

        await viewModel.SearchAsync("cobalt");

        Assert.Contains("cobalt", viewModel.SearchResultText);
    }

    [Fact]
    public async Task SearchAsync_NoResults_ShowsNoMatchesMessage()
    {
        var client = new FakeCoreClient(
            queryResponder: (_, _, _) => Task.FromResult(CoreResult<MemoryQueryResponse>.Success(SuccessQueryResponse())));
        var viewModel = new MemoryViewModel(client);

        await viewModel.SearchAsync("nonexistent-xyz");

        Assert.Equal("No matching memories found.", viewModel.SearchResultText);
    }

    [Fact]
    public async Task SearchAsync_Failure_SetsSafeErrorMessage()
    {
        var client = new FakeCoreClient(
            queryResponder: (_, _, _) => Task.FromResult(
                CoreResult<MemoryQueryResponse>.Failure(CoreErrorKind.CoreServerFailure, "REVA Core reported an internal error.")));
        var viewModel = new MemoryViewModel(client);

        await viewModel.SearchAsync("cobalt");

        Assert.Equal("REVA Core reported an internal error.", viewModel.SearchResultText);
    }
}
