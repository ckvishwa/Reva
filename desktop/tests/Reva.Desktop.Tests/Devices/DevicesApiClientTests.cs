using System.Net;
using Reva.Desktop.Devices;
using Reva.Desktop.Tests.Finance;

namespace Reva.Desktop.Tests.Devices;

public class DevicesApiClientTests
{
    private static (DevicesApiClient Client, StubHandler Handler, StubTokens Tokens) Create(TimeSpan? timeout = null)
    {
        var handler = new StubHandler();
        var tokens = new StubTokens();
        var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") };
        return (new DevicesApiClient(http, tokens, timeout ?? TimeSpan.FromSeconds(5)), handler, tokens);
    }

    private static HttpResponseMessage Ok(string body) => StubHandler.Json(HttpStatusCode.OK, body);

    private const string EmptyGateway =
        """{"enabled":false,"listening":false,"host":null,"port":null,"tls_sha256":null,"error":null,"pairing":null}""";

    [Fact]
    public async Task Every_call_uses_its_route_and_sends_the_bearer_token()
    {
        var (client, handler, _) = Create();
        handler.Responder = (r, _) => Task.FromResult(Ok(r.RequestUri!.AbsolutePath switch
        {
            "/v1/devices" => $$"""{"gateway":{{EmptyGateway}},"devices":[]}""",
            "/v1/devices/gateway" => $$"""{"gateway":{{EmptyGateway}}}""",
            "/v1/devices/pairing" => """{"session_id":"S","qr_text":"REVA-PAIR1:x","expires_at":1800000120}""",
            "/v1/devices/pairing/approve" => """{"device_id":"d-1"}""",
            "/v1/devices/pairing/deny" => """{"denied":true}""",
            _ => """{"device_id":"d-1","revoked":true,"changed":true}""",
        }));

        await client.GetAsync();
        await client.SetGatewayEnabledAsync(true);
        await client.OpenPairingAsync();
        await client.ApprovePairingAsync("482913");
        await client.DenyPairingAsync();
        await client.RevokeAsync("d-1");

        Assert.Equal(
            new[]
            {
                (HttpMethod.Get, "/v1/devices"),
                (HttpMethod.Patch, "/v1/devices/gateway"),
                (HttpMethod.Post, "/v1/devices/pairing"),
                (HttpMethod.Post, "/v1/devices/pairing/approve"),
                (HttpMethod.Post, "/v1/devices/pairing/deny"),
                (HttpMethod.Post, "/v1/devices/d-1/revoke"),
            },
            handler.Requests.Select(r => (r.Method, r.PathAndQuery)));
        Assert.All(handler.Requests, r => Assert.Equal("Bearer secret-token", r.Authorization));
    }

    [Fact]
    public async Task Bodies_carry_only_what_core_needs()
    {
        var (client, handler, _) = Create();
        handler.Responder = (r, _) => Task.FromResult(Ok(r.RequestUri!.AbsolutePath.EndsWith("gateway", StringComparison.Ordinal)
            ? $$"""{"gateway":{{EmptyGateway}}}"""
            : """{"device_id":"d-1"}"""));

        await client.SetGatewayEnabledAsync(true);
        await client.ApprovePairingAsync("482913");

        Assert.Equal("""{"enabled":true}""", handler.Requests[0].Body);
        Assert.Equal("""{"fingerprint":"482913"}""", handler.Requests[1].Body);
    }

    [Fact]
    public async Task A_device_id_is_escaped_into_the_path()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(Ok("""{"device_id":"x","revoked":true,"changed":false}"""));

        await client.RevokeAsync("../v1/domains/finance/export?x=1");

        Assert.Single(handler.Requests);
        Assert.StartsWith("/v1/devices/..%2Fv1%2Fdomains%2Ffinance%2Fexport%3Fx%3D1/revoke", handler.Requests[0].PathAndQuery);
    }

    [Fact]
    public async Task Without_a_token_nothing_is_sent()
    {
        var (client, handler, tokens) = Create();
        tokens.Available = false;

        var result = await client.GetAsync();

        Assert.Equal(DevicesErrorKind.Unauthorized, result.Error!.Kind);
        Assert.Empty(handler.Requests);
    }

    [Theory]
    [InlineData(401, """{"error":"Unauthorized"}""", DevicesErrorKind.Unauthorized)]
    [InlineData(404, """{"error":"unknown_device"}""", DevicesErrorKind.NotFound)]
    [InlineData(409, """{"error":"gateway_off"}""", DevicesErrorKind.GatewayOff)]
    [InlineData(409, """{"error":"gateway_unavailable","detail":"no local network address was found"}""", DevicesErrorKind.GatewayOff)]
    [InlineData(409, """{"error":"nothing_to_approve"}""", DevicesErrorKind.State)]
    [InlineData(409, """{"error":"fingerprint_mismatch"}""", DevicesErrorKind.State)]
    [InlineData(409, """{"error":"kernel_refused"}""", DevicesErrorKind.State)]
    [InlineData(422, """{"error":"validation_error"}""", DevicesErrorKind.Validation)]
    [InlineData(500, """{"error":"internal_error"}""", DevicesErrorKind.ServerFailure)]
    [InlineData(418, "not json at all", DevicesErrorKind.InvalidResponse)]
    public async Task Failures_become_safe_errors(int status, string body, DevicesErrorKind kind)
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(StubHandler.Json((HttpStatusCode)status, body));

        var result = await client.RevokeAsync("d-1");

        Assert.False(result.IsSuccess);
        Assert.Equal(kind, result.Error!.Kind);
        Assert.DoesNotContain("secret-token", result.Error.SafeMessage);
        Assert.DoesNotContain("Traceback", result.Error.SafeMessage);
    }

    [Fact]
    public async Task A_gateway_that_could_not_start_shows_cores_reason()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(StubHandler.Json(
            HttpStatusCode.Conflict, """{"error":"gateway_unavailable","detail":"the gateway could not listen on 10.0.0.2:47821: is the port already in use?"}"""));

        var result = await client.SetGatewayEnabledAsync(true);

        Assert.Equal(DevicesErrorKind.GatewayOff, result.Error!.Kind);
        Assert.Equal("the gateway could not listen on 10.0.0.2:47821: is the port already in use?", result.Error.SafeMessage);
    }

    [Fact]
    public async Task Unreachable_unreadable_and_slow_cores_are_reported_not_thrown()
    {
        var (client, handler, _) = Create(TimeSpan.FromMilliseconds(100));

        handler.Responder = (_, _) => throw new HttpRequestException("down");
        Assert.Equal(DevicesErrorKind.Unavailable, (await client.GetAsync()).Error!.Kind);

        handler.Responder = (_, _) => Task.FromResult(Ok("{ not json"));
        Assert.Equal(DevicesErrorKind.InvalidResponse, (await client.GetAsync()).Error!.Kind);

        handler.Responder = (_, _) => Task.FromResult(Ok("null"));
        Assert.Equal(DevicesErrorKind.InvalidResponse, (await client.GetAsync()).Error!.Kind);

        handler.Responder = async (_, ct) =>
        {
            await Task.Delay(Timeout.Infinite, ct);
            return Ok("{}");
        };
        Assert.Equal(DevicesErrorKind.Timeout, (await client.GetAsync()).Error!.Kind);
    }

    [Fact]
    public async Task The_token_never_appears_in_a_url_a_body_or_an_error()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(StubHandler.Json(HttpStatusCode.InternalServerError, """{"error":"x"}"""));

        var result = await client.OpenPairingAsync();

        Assert.DoesNotContain("secret-token", handler.Requests[0].PathAndQuery);
        Assert.Null(handler.Requests[0].Body);
        Assert.DoesNotContain("secret-token", result.Error!.SafeMessage);
    }
}
