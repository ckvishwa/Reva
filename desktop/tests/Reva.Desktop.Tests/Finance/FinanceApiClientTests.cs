using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Reva.Desktop.Finance;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Finance;

internal sealed record RecordedRequest(HttpMethod Method, string PathAndQuery, string? Authorization, string? Body);

internal sealed class StubHandler : HttpMessageHandler
{
    public List<RecordedRequest> Requests { get; } = new();

    public Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> Responder { get; set; } =
        (_, _) => Task.FromResult(Json(HttpStatusCode.OK, "{}"));

    public static HttpResponseMessage Json(HttpStatusCode status, string body) =>
        new(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
        Requests.Add(new RecordedRequest(
            request.Method, request.RequestUri!.PathAndQuery, request.Headers.Authorization?.ToString(), body));
        return await Responder(request, cancellationToken);
    }
}

internal sealed class StubTokens : ILocalTokenProvider
{
    public bool Available { get; set; } = true;

    public Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(Available ? TokenLoadResult.Available("secret-token") : TokenLoadResult.Unavailable());
}

public class FinanceApiClientTests
{
    private static (FinanceApiClient Client, StubHandler Handler, StubTokens Tokens) Create(TimeSpan? timeout = null)
    {
        var handler = new StubHandler();
        var tokens = new StubTokens();
        var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") };
        return (new FinanceApiClient(http, tokens, timeout ?? TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(5)), handler, tokens);
    }

    private static HttpResponseMessage Ok(string body) => StubHandler.Json(HttpStatusCode.OK, body);

    [Fact]
    public async Task Reads_use_the_right_routes_and_always_send_the_bearer_token()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(Ok("""{"rows": [], "items": []}"""));

        await client.GetBalancesAsync();
        await client.GetCategoriesAsync();
        await client.GetTransactionsAsync(null, 100);
        await client.GetTransactionsAsync("  café au lait  ", 25);
        await client.GetBudgetStatusAsync("last_month");
        await client.GetBillsAsync();
        await client.GetNetWorthSnapshotsAsync();
        await client.GetConflictsAsync();

        Assert.Equal(
            new[]
            {
                "/v1/domains/finance/reports/account_balances",
                "/v1/domains/finance/categories",
                "/v1/domains/finance/transactions?limit=100",
                "/v1/domains/finance/transactions?limit=25&q=caf%C3%A9%20au%20lait",
                "/v1/domains/finance/reports/budget_status?month=last_month",
                "/v1/domains/finance/reports/upcoming_bills?days=366",
                "/v1/domains/finance/networth-snapshots",
                "/v1/domains/finance/conflicts",
            },
            handler.Requests.Select(r => r.PathAndQuery));
        Assert.All(handler.Requests, r =>
        {
            Assert.Equal(HttpMethod.Get, r.Method);
            Assert.Equal("Bearer secret-token", r.Authorization);
        });
    }

    [Fact]
    public async Task Today_and_privacy_reads()
    {
        var (client, handler, _) = Create();
        handler.Responder = (r, _) => Task.FromResult(Ok(r.RequestUri!.PathAndQuery.StartsWith("/v1/today", StringComparison.Ordinal)
            ? """{"as_of":"2026-10-12","domains":{"finance":{"budget_left_this_month":[],"bills_due_7_days":[]}}}"""
            : """{"privacy":{"sync":true,"hosted_model_access":false}}"""));

        var today = await client.GetTodayAsync();
        var privacy = await client.GetPrivacyAsync();

        Assert.Equal("2026-10-12", today.Value!.AsOf);
        Assert.Equal(new PrivacySettings(true, false), privacy.Value);
        Assert.Equal(new[] { "/v1/today", "/v1/domains/finance/privacy" }, handler.Requests.Select(r => r.PathAndQuery));
    }

    [Fact]
    public async Task Writes_send_exactly_the_documented_json()
    {
        var (client, handler, _) = Create();
        handler.Responder = (r, _) => Task.FromResult(Ok(r.RequestUri!.AbsolutePath.EndsWith("/privacy", StringComparison.Ordinal)
            ? """{"privacy":{"sync":false,"hosted_model_access":false}}"""
            : """{"event_id":"E","aggregate_id":"x-0000001","version":1}"""));

        await client.AddAccountAsync(new NewAccountRequest("Visa", "credit", "USD", -25_000));
        await client.AddTransactionAsync(new NewTransactionRequest("acct-1", "2026-10-12", -1_200, "Lunch", "lunch", "with Sam"));
        await client.AddTransactionAsync(new NewTransactionRequest("acct-1", "2026-10-12", 500, "Refund", null, null));
        await client.TakeNetWorthSnapshotAsync();
        await client.ResolveConflictAsync(7, keepLocal: true);
        await client.ResolveConflictAsync(8, keepLocal: false);
        await client.SetPrivacyAsync(false, null);
        await client.SetPrivacyAsync(null, true);

        var r = handler.Requests;
        Assert.Equal(HttpMethod.Post, r[0].Method);
        Assert.Equal("/v1/domains/finance/accounts", r[0].PathAndQuery);
        Assert.Equal("""{"name":"Visa","kind":"credit","currency":"USD","opening_balance_minor":-25000}""", r[0].Body);
        Assert.Equal(
            """{"account_id":"acct-1","date":"2026-10-12","amount_minor":-1200,"description":"Lunch","source":"manual","category":"lunch","notes":"with Sam"}""",
            r[1].Body);
        Assert.Equal(
            """{"account_id":"acct-1","date":"2026-10-12","amount_minor":500,"description":"Refund","source":"manual"}""",
            r[2].Body);
        Assert.Equal("/v1/domains/finance/networth-snapshots", r[3].PathAndQuery);
        Assert.Equal("{}", r[3].Body);
        Assert.Equal(("/v1/domains/finance/conflicts/7/resolve", """{"keep":"local"}"""), (r[4].PathAndQuery, r[4].Body));
        Assert.Equal(("/v1/domains/finance/conflicts/8/resolve", """{"keep":"remote"}"""), (r[5].PathAndQuery, r[5].Body));
        Assert.Equal(HttpMethod.Patch, r[6].Method);
        Assert.Equal("""{"sync":false}""", r[6].Body);
        Assert.Equal("""{"hosted_model_access":true}""", r[7].Body);
        Assert.All(r, x => Assert.Equal("Bearer secret-token", x.Authorization));
    }

    [Fact]
    public async Task Import_sends_the_file_as_base64_with_the_mapping_and_the_dry_run_flag()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(Ok(
            """{"accepted":1,"duplicates":0,"rejected":[],"rows":[],"dry_run":true,"batch_id":"B"}"""));
        var mapping = new CsvMapping("Date", "%d/%m/%Y", "Memo", null, "Debit", "Credit", "Category", ";", ",", true);

        var result = await client.ImportAsync("csv", new byte[] { 1, 2, 3 }, "acct-1", mapping, dryRun: true);

        Assert.True(result.IsSuccess);
        var body = JsonNode.Parse(handler.Requests[0].Body!)!;
        Assert.Equal("/v1/domains/finance/import", handler.Requests[0].PathAndQuery);
        Assert.Equal("csv", (string?)body["format"]);
        Assert.Equal(Convert.ToBase64String(new byte[] { 1, 2, 3 }), (string?)body["data_base64"]);
        var options = body["options"]!;
        Assert.True((bool)options["dry_run"]!);
        Assert.Equal("acct-1", (string?)options["account_id"]);
        var map = options["mapping"]!;
        Assert.Equal("Date", (string?)map["date"]);
        Assert.Equal("%d/%m/%Y", (string?)map["date_format"]);
        Assert.Equal("Debit", (string?)map["debit"]);
        Assert.Equal("Credit", (string?)map["credit"]);
        Assert.Null(map["amount"]);
        Assert.Equal(";", (string?)map["delimiter"]);
        Assert.Equal(",", (string?)map["decimal_separator"]);
        Assert.True((bool)map["invert_sign"]!);
    }

    [Fact]
    public async Task A_json_restore_sends_no_account_and_no_mapping()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(Ok("""{"accepted":0,"duplicates":0,"rejected":[],"rows":[],"dry_run":false,"batch_id":"B"}"""));

        await client.ImportAsync("json", new byte[] { 123, 125 }, null, null, dryRun: false);

        var options = JsonNode.Parse(handler.Requests[0].Body!)!["options"]!.AsObject();
        Assert.False((bool)options["dry_run"]!);
        Assert.False(options.ContainsKey("account_id"));
        Assert.False(options.ContainsKey("mapping"));
    }

    [Fact]
    public async Task Export_returns_the_raw_bytes()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(new byte[] { 0xEF, 0xBB, 0xBF, 65 }),
        });

        var result = await client.ExportAsync("csv");

        Assert.Equal(new byte[] { 0xEF, 0xBB, 0xBF, 65 }, result.Value);
        Assert.Equal("/v1/domains/finance/export?format=csv", handler.Requests[0].PathAndQuery);
    }

    [Theory]
    [InlineData(401, """{"error":"Unauthorized"}""", FinanceErrorKind.Unauthorized, null)]
    [InlineData(423, """{"error":"domain_locked"}""", FinanceErrorKind.Locked, null)]
    [InlineData(422, """{"error":"validation_error","field":"amount_minor","detail":"must not be zero"}""", FinanceErrorKind.Validation, "amount_minor")]
    [InlineData(409, """{"error":"conflict","detail":"an account named \"Main\" already exists"}""", FinanceErrorKind.Conflict, null)]
    [InlineData(404, """{"error":"not_found"}""", FinanceErrorKind.NotFound, null)]
    [InlineData(410, """{"error":"deleted"}""", FinanceErrorKind.Deleted, null)]
    [InlineData(503, """{"error":"domain_kernel_unavailable"}""", FinanceErrorKind.Unavailable, null)]
    [InlineData(500, """{"error":"internal_error"}""", FinanceErrorKind.ServerFailure, null)]
    [InlineData(418, "teapot", FinanceErrorKind.InvalidResponse, null)]
    public async Task Failures_become_one_safe_error_kind(int status, string body, FinanceErrorKind kind, string? field)
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(StubHandler.Json((HttpStatusCode)status, body));

        var result = await client.GetBalancesAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(kind, result.Error!.Kind);
        Assert.Equal(field, result.Error.Field);
    }

    [Fact]
    public async Task Validation_errors_carry_the_field_and_core_detail_for_the_form()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(StubHandler.Json(
            HttpStatusCode.UnprocessableEntity, """{"error":"validation_error","field":"category","detail":"no category or alias named \"x\""}"""));

        var result = await client.AddTransactionAsync(new NewTransactionRequest("a", "2026-10-12", -1, "x", "x", null));

        Assert.Equal("category: no category or alias named \"x\"", result.Error!.SafeMessage);
        Assert.Equal("category", result.Error.Field);
        Assert.Equal("no category or alias named \"x\"", result.Error.Detail);
    }

    [Fact]
    public async Task Server_error_bodies_never_reach_the_message()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(StubHandler.Json(
            HttpStatusCode.InternalServerError, """{"error":"internal_error","detail":"Traceback C:\\secret\\path token=abc"}"""));

        var result = await client.GetBalancesAsync();

        Assert.Equal("REVA Core reported an internal error.", result.Error!.SafeMessage);
        Assert.DoesNotContain("secret", result.Error.SafeMessage);
    }

    [Fact]
    public async Task Without_a_token_nothing_is_sent()
    {
        var (client, handler, tokens) = Create();
        tokens.Available = false;

        var result = await client.GetBalancesAsync();

        Assert.Equal(FinanceErrorKind.Unauthorized, result.Error!.Kind);
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task A_core_that_is_not_running_is_reported_as_unavailable()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => throw new HttpRequestException("connection refused");

        var result = await client.GetBalancesAsync();

        Assert.Equal(FinanceErrorKind.Unavailable, result.Error!.Kind);
        Assert.Equal("REVA Core is not reachable.", result.Error.SafeMessage);
    }

    [Fact]
    public async Task A_core_that_does_not_answer_times_out_without_hanging()
    {
        var (client, handler, _) = Create(TimeSpan.FromMilliseconds(50));
        handler.Responder = async (_, ct) =>
        {
            await Task.Delay(Timeout.Infinite, ct);
            return Ok("{}");
        };

        var result = await client.GetBalancesAsync();

        Assert.Equal(FinanceErrorKind.Timeout, result.Error!.Kind);
    }

    [Fact]
    public async Task Caller_cancellation_is_not_turned_into_a_timeout()
    {
        var (client, handler, _) = Create();
        handler.Responder = async (_, ct) =>
        {
            await Task.Delay(Timeout.Infinite, ct);
            return Ok("{}");
        };
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(30));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.GetBalancesAsync(cts.Token));
    }

    [Fact]
    public async Task A_body_that_is_not_json_is_an_invalid_response_not_a_crash()
    {
        var (client, handler, _) = Create();
        handler.Responder = (_, _) => Task.FromResult(Ok("<html>oops</html>"));

        var result = await client.GetBalancesAsync();

        Assert.Equal(FinanceErrorKind.InvalidResponse, result.Error!.Kind);
    }
}
