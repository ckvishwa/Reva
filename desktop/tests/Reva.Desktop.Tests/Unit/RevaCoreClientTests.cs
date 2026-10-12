using System.Net;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class RevaCoreClientTests
{
    [Fact]
    public async Task ReasoningSettings_RoundTripUsesAuthenticatedLocalApi()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"cloud_reasoning":true,"leaves_device":{"text":"Final transcript and capability names","audio":"Never","screens":"Never","memory":"Never","domain_data":"Never"}}""");
        var (client, capture) = AuthenticatedClientFor(handler);

        var result = await client.SetReasoningSettingsAsync(true);

        Assert.True(result.IsSuccess);
        Assert.True(result.Value!.CloudReasoning);
        Assert.Equal(HttpMethod.Patch, capture.LastRequest!.Method);
        Assert.Equal("/v1/settings/reasoning", capture.LastRequest.RequestUri!.AbsolutePath);
        Assert.Contains("\"cloud_reasoning\":true", capture.LastRequestBody);
        Assert.Equal("Bearer", capture.LastRequest.Headers.Authorization!.Scheme);
    }

    [Fact]
    public async Task SaveAnthropicKey_DoesNotPutSecretInUrl()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.OK, """{"saved":true}""");
        var (client, capture) = AuthenticatedClientFor(handler);

        var result = await client.SaveAnthropicKeyAsync("test-secret-never-log");

        Assert.True(result.IsSuccess);
        Assert.Equal("/v1/settings/reasoning/key", capture.LastRequest!.RequestUri!.AbsolutePath);
        Assert.DoesNotContain("test-secret-never-log", capture.LastRequest.RequestUri.ToString());
    }

    private sealed class NullTokenProvider : ILocalTokenProvider
    {
        public Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(TokenLoadResult.Unavailable());
    }

    private sealed class FakeTokenProvider : ILocalTokenProvider
    {
        private readonly string _token;

        public FakeTokenProvider(string token) => _token = token;

        public Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(TokenLoadResult.Available(_token));
    }

    private static RevaCoreClient ClientFor(HttpMessageHandler handler)
    {
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") };
        return new RevaCoreClient(httpClient, new NullTokenProvider());
    }

    private static (RevaCoreClient Client, FakeHttpMessageHandler Handler) AuthenticatedClientFor(
        HttpMessageHandler handler, string token = "test-token-value")
    {
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") };
        var client = new RevaCoreClient(httpClient, new FakeTokenProvider(token));
        return (client, (FakeHttpMessageHandler)handler);
    }

    private static RevaCoreClient ClientWith(
        HttpMessageHandler handler, TimeSpan requestTimeout, TimeSpan sttRequestTimeout,
        TimeSpan? messageTimeout = null) =>
        new(
            new HttpClient(handler)
            {
                BaseAddress = new Uri("http://127.0.0.1:8756/"),
                Timeout = Timeout.InfiniteTimeSpan,
            },
            new FakeTokenProvider("t"),
            requestTimeout,
            sttRequestTimeout,
            messageTimeout ?? requestTimeout);

    [Fact]
    public async Task GetHealthAsync_ParsesSuccessResponse()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"status":"healthy","db_schema_version":1,"started_at":"2026-08-10T12:00:00Z"}""");
        var client = ClientFor(handler);

        var result = await client.GetHealthAsync();

        Assert.True(result.IsSuccess);
        Assert.Equal("healthy", result.Value!.Status);
        Assert.Equal(1, result.Value.DbSchemaVersion);
    }

    [Fact]
    public async Task GetVersionAsync_ParsesSuccessResponse()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.OK, """{"version":"0.1.0"}""");
        var client = ClientFor(handler);

        var result = await client.GetVersionAsync();

        Assert.True(result.IsSuccess);
        Assert.Equal("0.1.0", result.Value!.Version);
    }

    [Fact]
    public async Task GetHealthAsync_ConnectionRefused_MapsToCoreUnavailable()
    {
        var client = ClientFor(FakeHttpMessageHandler.ThrowingConnectionRefused());

        var result = await client.GetHealthAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreUnavailable, result.Error!.Kind);
    }

    [Fact]
    public async Task GetHealthAsync_Timeout_MapsToCoreTimeout()
    {
        var client = ClientFor(FakeHttpMessageHandler.ThrowingTimeout());

        var result = await client.GetHealthAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreTimeout, result.Error!.Kind);
    }

    [Fact]
    public async Task GetHealthAsync_Unauthorized_MapsToCoreUnauthorized()
    {
        var client = ClientFor(FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.Unauthorized));

        var result = await client.GetHealthAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreUnauthorized, result.Error!.Kind);
    }

    [Fact]
    public async Task GetHealthAsync_ServerError_MapsToCoreServerFailure()
    {
        var client = ClientFor(FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.InternalServerError));

        var result = await client.GetHealthAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreServerFailure, result.Error!.Kind);
    }

    [Fact]
    public async Task GetHealthAsync_MalformedJson_MapsToCoreInvalidResponse()
    {
        var client = ClientFor(FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.OK, "not valid json"));

        var result = await client.GetHealthAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreInvalidResponse, result.Error!.Kind);
    }

    [Fact]
    public async Task GetHealthAsync_UnexpectedStatusCode_MapsToCoreInvalidResponse()
    {
        var client = ClientFor(FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.NotFound));

        var result = await client.GetHealthAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreInvalidResponse, result.Error!.Kind);
    }

    [Fact]
    public async Task GetHealthAsync_ErrorMessage_NeverContainsServerResponseBody()
    {
        // Even if a server response body happened to contain something
        // sensitive-looking, the normalized error message must be a fixed
        // safe string, never derived from the raw response.
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.Unauthorized, """{"error":"token abc-super-secret-value is invalid"}""");
        var client = ClientFor(handler);

        var result = await client.GetHealthAsync();

        Assert.False(result.IsSuccess);
        Assert.DoesNotContain("abc-super-secret-value", result.Error!.SafeMessage);
    }

    [Fact]
    public async Task SendMessageAsync_ParsesSuccessResponse()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"correlation_id":"11111111-1111-1111-1111-111111111111","reply":"Received: hi","memory_created":null}""");
        var (client, _) = AuthenticatedClientFor(handler);

        var result = await client.SendMessageAsync("hi");

        Assert.True(result.IsSuccess);
        Assert.Equal("Received: hi", result.Value!.Reply);
        Assert.Null(result.Value.MemoryCreated);
    }

    [Fact]
    public async Task SendMessageAsync_PostsToV1MessagesWithBearerToken()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"correlation_id":"11111111-1111-1111-1111-111111111111","reply":"ok","memory_created":null}""");
        var (client, fakeHandler) = AuthenticatedClientFor(handler, "test-token-value");

        await client.SendMessageAsync("hello REVA");

        Assert.NotNull(fakeHandler.LastRequest);
        Assert.Equal(HttpMethod.Post, fakeHandler.LastRequest!.Method);
        Assert.Equal("http://127.0.0.1:8756/v1/messages", fakeHandler.LastRequest.RequestUri!.ToString());
        Assert.Equal("Bearer", fakeHandler.LastRequest.Headers.Authorization!.Scheme);
        Assert.Equal("test-token-value", fakeHandler.LastRequest.Headers.Authorization.Parameter);

        Assert.Contains("\"content\":\"hello REVA\"", fakeHandler.LastRequestBody);
    }

    [Fact]
    public async Task SendMessageAsync_TokenUnavailable_MapsToCoreUnauthorized_WithoutSendingRequest()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.OK, "{}");
        var client = ClientFor(handler); // NullTokenProvider => token unavailable

        var result = await client.SendMessageAsync("hi");

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreUnauthorized, result.Error!.Kind);
        Assert.Null(((FakeHttpMessageHandler)handler).LastRequest);
    }

    [Fact]
    public async Task SendMessageAsync_ServerError_MapsToCoreServerFailure()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.InternalServerError);
        var (client, _) = AuthenticatedClientFor(handler);

        var result = await client.SendMessageAsync("hi");

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreServerFailure, result.Error!.Kind);
    }

    [Fact]
    public async Task CreateMemoryAsync_ParsesSuccessResponse()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.Created,
            """{"schema_version":1,"id":"019fed00-0000-7000-8000-000000000000","category":"note","created_at":"2026-08-10T12:00:00Z","correlation_id":"11111111-1111-1111-1111-111111111111"}""");
        var (client, _) = AuthenticatedClientFor(handler);

        var result = await client.CreateMemoryAsync("test-color-abc123 = cobalt");

        Assert.True(result.IsSuccess);
        Assert.Equal("note", result.Value!.Category);
        Assert.Equal("019fed00-0000-7000-8000-000000000000", result.Value.Id);
    }

    [Fact]
    public async Task CreateMemoryAsync_PostsToV1MemoriesWithBearerTokenAndContent()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.Created,
            """{"schema_version":1,"id":"x","category":"note","created_at":"2026-08-10T12:00:00Z","correlation_id":"11111111-1111-1111-1111-111111111111"}""");
        var (client, fakeHandler) = AuthenticatedClientFor(handler, "test-token-value");

        await client.CreateMemoryAsync("remember this fact");

        Assert.Equal(HttpMethod.Post, fakeHandler.LastRequest!.Method);
        Assert.Equal("http://127.0.0.1:8756/v1/memories", fakeHandler.LastRequest.RequestUri!.ToString());
        Assert.Equal("test-token-value", fakeHandler.LastRequest.Headers.Authorization!.Parameter);
        Assert.Contains("\"content\":\"remember this fact\"", fakeHandler.LastRequestBody);
    }

    [Fact]
    public async Task CreateMemoryAsync_TokenUnavailable_MapsToCoreUnauthorized_WithoutSendingRequest()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.Created, "{}");
        var client = ClientFor(handler); // NullTokenProvider => token unavailable

        var result = await client.CreateMemoryAsync("hi");

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreUnauthorized, result.Error!.Kind);
        Assert.Null(((FakeHttpMessageHandler)handler).LastRequest);
    }

    [Fact]
    public async Task CreateMemoryAsync_ServerRejection_MapsToCoreInvalidResponse()
    {
        // Mirrors Core's real 400 for e.g. empty-after-strip content.
        var handler = FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.BadRequest, """{"error":"content must not be empty"}""");
        var (client, _) = AuthenticatedClientFor(handler);

        var result = await client.CreateMemoryAsync("   ");

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreInvalidResponse, result.Error!.Kind);
    }

    [Fact]
    public async Task QueryMemoriesAsync_ParsesSuccessResponse()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"results":[{"schema_version":1,"id":"m1","content":"cobalt","category":"note","source":{"schema_version":1,"conversation_id":null,"message_id":null,"origin_device_id":"d1","note":"explicit_api_memory_creation"},"tags":[],"created_at":"2026-08-10T12:00:00Z","updated_at":"2026-08-10T12:00:00Z"}],"correlation_id":"11111111-1111-1111-1111-111111111111"}""");
        var (client, _) = AuthenticatedClientFor(handler);

        var result = await client.QueryMemoriesAsync("cobalt", 5);

        Assert.True(result.IsSuccess);
        Assert.Single(result.Value!.Results);
        Assert.Equal("cobalt", result.Value.Results[0].Content);
    }

    [Fact]
    public async Task QueryMemoriesAsync_EmptyResults_ParsesSafely()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"results":[],"correlation_id":"11111111-1111-1111-1111-111111111111"}""");
        var (client, _) = AuthenticatedClientFor(handler);

        var result = await client.QueryMemoriesAsync("nonexistent-xyz", 5);

        Assert.True(result.IsSuccess);
        Assert.Empty(result.Value!.Results);
    }

    [Fact]
    public async Task QueryMemoriesAsync_GetsFromV1MemoriesWithEncodedQueryAndLimit()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"results":[],"correlation_id":"11111111-1111-1111-1111-111111111111"}""");
        var (client, fakeHandler) = AuthenticatedClientFor(handler);

        await client.QueryMemoriesAsync("test color", 7);

        Assert.Equal(HttpMethod.Get, fakeHandler.LastRequest!.Method);
        // AbsoluteUri (not ToString()): Uri.ToString() unescapes %20 back to
        // a literal space for display, which would hide an encoding bug.
        Assert.Equal(
            "http://127.0.0.1:8756/v1/memories?q=test%20color&limit=7",
            fakeHandler.LastRequest.RequestUri!.AbsoluteUri);
    }

    [Fact]
    public async Task TranscribeSpeechAsync_PostsWavToVoiceEndpointWithBearerToken()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"text":"hello REVA","language":"en","duration_ms":900}""");
        var (client, fakeHandler) = AuthenticatedClientFor(handler);

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.True(result.IsSuccess);
        Assert.Equal("hello REVA", result.Value!.Text);
        Assert.Equal(HttpMethod.Post, fakeHandler.LastRequest!.Method);
        Assert.Equal("http://127.0.0.1:8756/v1/voice/transcriptions", fakeHandler.LastRequest.RequestUri!.ToString());
        Assert.Equal("audio/wav", fakeHandler.LastRequest.Content!.Headers.ContentType!.MediaType);
        Assert.Equal("Bearer", fakeHandler.LastRequest.Headers.Authorization!.Scheme);
    }

    [Fact]
    public async Task SynthesizeSpeechAsync_PostsTextAndReturnsWavBytes()
    {
        var handler = new FakeHttpMessageHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(new byte[] { 82, 73, 70, 70 }),
        }));
        var (client, fakeHandler) = AuthenticatedClientFor(handler);

        var result = await client.SynthesizeSpeechAsync("Good morning.", "en");

        Assert.True(result.IsSuccess);
        Assert.Equal(new byte[] { 82, 73, 70, 70 }, result.Value);
        Assert.Equal(HttpMethod.Post, fakeHandler.LastRequest!.Method);
        Assert.Equal("http://127.0.0.1:8756/v1/voice/speech", fakeHandler.LastRequest.RequestUri!.ToString());
        Assert.Contains("\"text\":\"Good morning.\"", fakeHandler.LastRequestBody);
        Assert.Contains("\"language\":\"en\"", fakeHandler.LastRequestBody);
        Assert.Equal("Bearer", fakeHandler.LastRequest.Headers.Authorization!.Scheme);
    }

    [Fact]
    public async Task VoiceUnavailable_MapsToSafeVoiceMessage()
    {
        var handler = FakeHttpMessageHandler.ReturningStatus(HttpStatusCode.ServiceUnavailable);
        var (client, _) = AuthenticatedClientFor(handler);

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreUnavailable, result.Error!.Kind);
        Assert.Equal("REVA voice is unavailable.", result.Error.SafeMessage);
    }

    private const string TranscriptionJson =
        """{"schema_version":1,"text":"hello","language":"en","duration_ms":900}""";

    [Fact]
    public async Task TranscribeSpeechAsync_Timeout_MapsToVoiceTimeoutMessage_NotGenericCoreMessage()
    {
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromSeconds(5), HttpStatusCode.OK, TranscriptionJson),
            requestTimeout: TimeSpan.FromSeconds(10),
            sttRequestTimeout: TimeSpan.FromMilliseconds(100));

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreTimeout, result.Error!.Kind);
        Assert.Equal("REVA voice did not respond in time.", result.Error.SafeMessage);
    }

    [Fact]
    public async Task TranscribeSpeechAsync_SlowerThanRequestTimeoutButFasterThanSttTimeout_Succeeds()
    {
        // The test v1 was missing: proves the STT call actually selects the
        // longer STT timeout rather than the short general one. Fails if
        // TranscribeSpeechAsync forgets to pass timeout: _sttRequestTimeout.
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromMilliseconds(400), HttpStatusCode.OK, TranscriptionJson),
            requestTimeout: TimeSpan.FromMilliseconds(50),
            sttRequestTimeout: TimeSpan.FromSeconds(5));

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.True(result.IsSuccess);
        Assert.Equal("hello", result.Value!.Text);
    }

    [Fact]
    public async Task SendMessageAsync_ExceedingRequestTimeout_StillReturnsGenericCoreTimeoutMessage()
    {
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromSeconds(5), HttpStatusCode.OK, "{}"),
            requestTimeout: TimeSpan.FromMilliseconds(100),
            sttRequestTimeout: TimeSpan.FromSeconds(30));

        var result = await client.SendMessageAsync("hi");

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreTimeout, result.Error!.Kind);
        Assert.Equal("REVA Core did not respond in time.", result.Error.SafeMessage);
    }

    [Fact]
    public async Task SendMessageAsync_UsesPlannerBudgetBeyondGeneralTimeout()
    {
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromMilliseconds(300), HttpStatusCode.OK,
                """{"schema_version":1,"correlation_id":"c","reply":"Tokyo.","memory_created":null}"""),
            requestTimeout: TimeSpan.FromMilliseconds(50),
            sttRequestTimeout: TimeSpan.FromSeconds(30),
            messageTimeout: TimeSpan.FromSeconds(2));

        var result = await client.SendMessageAsync("what's the capital of Japan?");

        Assert.True(result.IsSuccess);
        Assert.Equal("Tokyo.", result.Value!.Reply);
    }

    [Fact]
    public async Task SendMessageAsync_CallerCancellation_PropagatesOperationCanceled()
    {
        // Documents the deliberate semantic change: caller cancellation is no
        // longer laundered into a CoreTimeout failure result.
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromSeconds(5), HttpStatusCode.OK, "{}"),
            requestTimeout: TimeSpan.FromSeconds(30),
            sttRequestTimeout: TimeSpan.FromSeconds(30));
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(50));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => client.SendMessageAsync("hi", cts.Token));
    }
}
