using System.Net;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class RevaCoreClientTests
{
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
}
