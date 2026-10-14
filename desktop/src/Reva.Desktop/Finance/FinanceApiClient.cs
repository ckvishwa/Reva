using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Reva.Desktop.Services;

namespace Reva.Desktop.Finance;

/// <summary>
/// HTTP implementation of <see cref="IFinanceApi"/> over REVA Core's Finance routes. Uses the same
/// shared <see cref="HttpClient"/> and local-token provider as <see cref="RevaCoreClient"/>. Every
/// failure is normalised to a <see cref="FinanceError"/>; nothing else reaches the view models.
/// </summary>
public sealed class FinanceApiClient : IFinanceApi, IDomainChangesApi
{
    private const string Base = "v1/domains/finance";
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _http;
    private readonly ILocalTokenProvider _tokens;
    private readonly TimeSpan _requestTimeout;
    private readonly TimeSpan _bulkTimeout;

    public FinanceApiClient(
        HttpClient http, ILocalTokenProvider tokens, TimeSpan? requestTimeout = null, TimeSpan? bulkTimeout = null)
    {
        _http = http;
        _tokens = tokens;
        _requestTimeout = requestTimeout ?? DesktopConfiguration.DefaultRequestTimeout;
        _bulkTimeout = bulkTimeout ?? TimeSpan.FromSeconds(60);
    }

    public async Task<FinanceResult<IReadOnlyList<AccountBalance>>> GetBalancesAsync(CancellationToken ct = default) =>
        Rows(await GetAsync<FinanceReportResponse<AccountBalance>>($"{Base}/reports/account_balances", ct));

    public async Task<FinanceResult<IReadOnlyList<FinanceCategory>>> GetCategoriesAsync(CancellationToken ct = default) =>
        Items(await GetAsync<FinanceListResponse<FinanceCategory>>($"{Base}/categories", ct));

    public async Task<FinanceResult<IReadOnlyList<FinanceTransaction>>> GetTransactionsAsync(
        string? search, int limit, CancellationToken ct = default)
    {
        var path = $"{Base}/transactions?limit={limit}";
        if (!string.IsNullOrWhiteSpace(search))
        {
            path += "&q=" + Uri.EscapeDataString(search.Trim());
        }

        return Items(await GetAsync<FinanceListResponse<FinanceTransaction>>(path, ct));
    }

    public async Task<FinanceResult<IReadOnlyList<BudgetStatus>>> GetBudgetStatusAsync(
        string month, CancellationToken ct = default) =>
        Rows(await GetAsync<FinanceReportResponse<BudgetStatus>>(
            $"{Base}/reports/budget_status?month={Uri.EscapeDataString(month)}", ct));

    public async Task<FinanceResult<IReadOnlyList<FinanceBill>>> GetBillsAsync(CancellationToken ct = default) =>
        Rows(await GetAsync<FinanceReportResponse<FinanceBill>>($"{Base}/reports/upcoming_bills?days=366", ct));

    public async Task<FinanceResult<IReadOnlyList<NetWorthSnapshot>>> GetNetWorthSnapshotsAsync(CancellationToken ct = default) =>
        Items(await GetAsync<FinanceListResponse<NetWorthSnapshot>>($"{Base}/networth-snapshots", ct));

    public Task<FinanceResult<CommitResponse>> TakeNetWorthSnapshotAsync(CancellationToken ct = default) =>
        SendJsonAsync<CommitResponse>(HttpMethod.Post, $"{Base}/networth-snapshots", new JsonObject(), ct);

    public async Task<FinanceResult<IReadOnlyList<FinanceConflict>>> GetConflictsAsync(CancellationToken ct = default) =>
        Items(await GetAsync<FinanceListResponse<FinanceConflict>>($"{Base}/conflicts", ct));

    public Task<FinanceResult<CommitResponse>> ResolveConflictAsync(long conflictId, bool keepLocal, CancellationToken ct = default) =>
        SendJsonAsync<CommitResponse>(
            HttpMethod.Post,
            $"{Base}/conflicts/{conflictId}/resolve",
            new JsonObject { ["keep"] = keepLocal ? "local" : "remote" },
            ct);

    public async Task<FinanceResult<PrivacySettings>> GetPrivacyAsync(CancellationToken ct = default) =>
        Unwrap(await GetAsync<PrivacyResponse>($"{Base}/privacy", ct), r => r.Privacy);

    public async Task<FinanceResult<PrivacySettings>> SetPrivacyAsync(bool? sync, bool? hostedModelAccess, CancellationToken ct = default)
    {
        var body = new JsonObject();
        if (sync is not null)
        {
            body["sync"] = sync;
        }

        if (hostedModelAccess is not null)
        {
            body["hosted_model_access"] = hostedModelAccess;
        }

        return Unwrap(await SendJsonAsync<PrivacyResponse>(HttpMethod.Patch, $"{Base}/privacy", body, ct), r => r.Privacy);
    }

    public Task<FinanceResult<CommitResponse>> AddAccountAsync(NewAccountRequest request, CancellationToken ct = default) =>
        SendJsonAsync<CommitResponse>(
            HttpMethod.Post,
            $"{Base}/accounts",
            new JsonObject
            {
                ["name"] = request.Name,
                ["kind"] = request.Kind,
                ["currency"] = request.Currency,
                ["opening_balance_minor"] = request.OpeningBalanceMinor,
            },
            ct);

    public Task<FinanceResult<CommitResponse>> AddTransactionAsync(NewTransactionRequest request, CancellationToken ct = default)
    {
        var body = new JsonObject
        {
            ["account_id"] = request.AccountId,
            ["date"] = request.Date,
            ["amount_minor"] = request.AmountMinor,
            ["description"] = request.Description,
            ["source"] = "manual",
        };
        if (!string.IsNullOrWhiteSpace(request.Category))
        {
            body["category"] = request.Category;
        }

        if (!string.IsNullOrWhiteSpace(request.Notes))
        {
            body["notes"] = request.Notes;
        }

        return SendJsonAsync<CommitResponse>(HttpMethod.Post, $"{Base}/transactions", body, ct);
    }

    public Task<FinanceResult<ImportReport>> ImportAsync(
        string format, byte[] data, string? accountId, CsvMapping? mapping, bool dryRun, CancellationToken ct = default)
    {
        var options = new JsonObject { ["dry_run"] = dryRun };
        if (accountId is not null)
        {
            options["account_id"] = accountId;
        }

        if (mapping is not null)
        {
            var map = new JsonObject
            {
                ["date"] = mapping.Date,
                ["date_format"] = mapping.DateFormat,
                ["description"] = mapping.Description,
                ["delimiter"] = mapping.Delimiter,
                ["decimal_separator"] = mapping.DecimalSeparator,
                ["invert_sign"] = mapping.InvertSign,
            };
            if (mapping.Amount is not null)
            {
                map["amount"] = mapping.Amount;
            }

            if (mapping.Debit is not null)
            {
                map["debit"] = mapping.Debit;
            }

            if (mapping.Credit is not null)
            {
                map["credit"] = mapping.Credit;
            }

            if (mapping.Category is not null)
            {
                map["category"] = mapping.Category;
            }

            options["mapping"] = map;
        }

        var body = new JsonObject
        {
            ["format"] = format,
            ["data_base64"] = Convert.ToBase64String(data),
            ["options"] = options,
        };
        return SendJsonAsync<ImportReport>(HttpMethod.Post, $"{Base}/import", body, ct, _bulkTimeout);
    }

    public async Task<FinanceResult<byte[]>> ExportAsync(string format, CancellationToken ct = default)
    {
        using var request = await NewRequestAsync(HttpMethod.Get, $"{Base}/export?format={Uri.EscapeDataString(format)}", ct);
        if (request.Failure is not null)
        {
            return FinanceResult<byte[]>.Failure(request.Failure);
        }

        var (response, failure) = await SendAsync(request.Message!, _bulkTimeout, ct);
        if (failure is not null)
        {
            return FinanceResult<byte[]>.Failure(failure);
        }

        using (response)
        {
            var error = await InterpretStatusAsync(response!, ct);
            if (error is not null)
            {
                return FinanceResult<byte[]>.Failure(error);
            }

            return FinanceResult<byte[]>.Success(await response!.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false));
        }
    }

    public async Task<FinanceResult<TodaySummary>> GetTodayAsync(CancellationToken ct = default) =>
        await GetAsync<TodaySummary>("v1/today", ct);

    // ------------------------------------------------------------------------------------------

    private static FinanceResult<IReadOnlyList<T>> Items<T>(FinanceResult<FinanceListResponse<T>> result) =>
        Unwrap(result, r => r.Items);

    private static FinanceResult<IReadOnlyList<T>> Rows<T>(FinanceResult<FinanceReportResponse<T>> result) =>
        Unwrap(result, r => r.Rows);

    public async Task<FinanceResult<DomainChange>> WaitForChangeAsync(
        string domain, long? since, TimeSpan wait, CancellationToken ct = default)
    {
        // Core never waits longer than 30 s; the client timeout leaves room for the answer to arrive.
        var seconds = (int)Math.Clamp(Math.Ceiling(wait.TotalSeconds), 0, 30);
        var path = $"v1/domains/changes?domain={Uri.EscapeDataString(domain)}&timeout={seconds}";
        if (since is { } baseline)
        {
            path += $"&since={baseline}";
        }

        var result = await SendAsync<ChangesResponse>(
            HttpMethod.Get, path, null, TimeSpan.FromSeconds(seconds + 10), ct).ConfigureAwait(false);
        return Unwrap(result, r => new DomainChange(r.Domain, r.Counter, r.Changed));
    }

    private sealed record ChangesResponse(string Domain, long Counter, bool Changed);

    private static FinanceResult<TOut> Unwrap<TIn, TOut>(FinanceResult<TIn> result, Func<TIn, TOut> select) =>
        result.IsSuccess ? FinanceResult<TOut>.Success(select(result.Value!)) : FinanceResult<TOut>.Failure(result.Error!);

    private Task<FinanceResult<T>> GetAsync<T>(string path, CancellationToken ct) =>
        SendAsync<T>(HttpMethod.Get, path, null, _requestTimeout, ct);

    private Task<FinanceResult<T>> SendJsonAsync<T>(
        HttpMethod method, string path, JsonObject body, CancellationToken ct, TimeSpan? timeout = null) =>
        SendAsync<T>(method, path, body, timeout ?? _requestTimeout, ct);

    private async Task<FinanceResult<T>> SendAsync<T>(
        HttpMethod method, string path, JsonObject? body, TimeSpan timeout, CancellationToken ct)
    {
        using var request = await NewRequestAsync(method, path, ct);
        if (request.Failure is not null)
        {
            return FinanceResult<T>.Failure(request.Failure);
        }

        if (body is not null)
        {
            request.Message!.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        }

        var (response, failure) = await SendAsync(request.Message!, timeout, ct);
        if (failure is not null)
        {
            return FinanceResult<T>.Failure(failure);
        }

        using (response)
        {
            var error = await InterpretStatusAsync(response!, ct);
            if (error is not null)
            {
                return FinanceResult<T>.Failure(error);
            }

            try
            {
                var stream = await response!.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
                var value = await JsonSerializer.DeserializeAsync<T>(stream, JsonOptions, ct).ConfigureAwait(false);
                return value is null
                    ? FinanceResult<T>.Failure(FinanceErrorKind.InvalidResponse, "REVA Core returned an empty response.")
                    : FinanceResult<T>.Success(value);
            }
            catch (JsonException)
            {
                return FinanceResult<T>.Failure(
                    FinanceErrorKind.InvalidResponse, "REVA Core returned a response REVA could not read.");
            }
        }
    }

    private sealed class PreparedRequest : IDisposable
    {
        public HttpRequestMessage? Message { get; init; }

        public FinanceError? Failure { get; init; }

        public void Dispose() => Message?.Dispose();
    }

    private async Task<PreparedRequest> NewRequestAsync(HttpMethod method, string path, CancellationToken ct)
    {
        var token = await _tokens.GetTokenAsync(ct).ConfigureAwait(false);
        if (!token.IsAvailable)
        {
            return new PreparedRequest
            {
                Failure = new FinanceError(FinanceErrorKind.Unauthorized, "REVA authorization is unavailable."),
            };
        }

        var message = new HttpRequestMessage(method, path);
        message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
        return new PreparedRequest { Message = message };
    }

    private async Task<(HttpResponseMessage? Response, FinanceError? Failure)> SendAsync(
        HttpRequestMessage request, TimeSpan timeout, CancellationToken ct)
    {
        using var timeoutCts = new CancellationTokenSource(timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, timeoutCts.Token);
        try
        {
            var response = await _http.SendAsync(request, HttpCompletionOption.ResponseContentRead, linked.Token)
                .ConfigureAwait(false);
            return (response, null);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return (null, new FinanceError(FinanceErrorKind.Timeout, "REVA Core did not respond in time."));
        }
        catch (HttpRequestException)
        {
            return (null, new FinanceError(FinanceErrorKind.Unavailable, "REVA Core is not reachable."));
        }
    }

    private static async Task<FinanceError?> InterpretStatusAsync(HttpResponseMessage response, CancellationToken ct)
    {
        if (response.IsSuccessStatusCode)
        {
            return null;
        }

        string? code = null;
        string? field = null;
        string? detail = null;
        try
        {
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (JsonNode.Parse(text) is JsonObject body)
            {
                code = body["error"]?.GetValue<string>();
                field = body["field"]?.GetValue<string>();
                detail = body["detail"]?.GetValue<string>();
            }
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException)
        {
            // A body that is not our error shape is treated as having no detail.
        }

        return (int)response.StatusCode switch
        {
            401 => new FinanceError(FinanceErrorKind.Unauthorized, "REVA Core rejected local authentication."),
            423 => new FinanceError(
                FinanceErrorKind.Locked, "Finance is locked: REVA has no key that opens the Finance data on this PC."),
            422 => new FinanceError(
                FinanceErrorKind.Validation, ValidationMessage(field, detail), field, detail),
            409 => new FinanceError(FinanceErrorKind.Conflict, detail ?? "That change conflicts with existing data.", field, detail),
            404 => new FinanceError(FinanceErrorKind.NotFound, "That record was not found."),
            410 => new FinanceError(FinanceErrorKind.Deleted, "That record was deleted."),
            503 => new FinanceError(FinanceErrorKind.Unavailable, "Finance is not available in this build of REVA Core."),
            >= 500 => new FinanceError(FinanceErrorKind.ServerFailure, "REVA Core reported an internal error."),
            _ => new FinanceError(FinanceErrorKind.InvalidResponse, "REVA Core returned an unexpected response."),
        };
    }

    private static string ValidationMessage(string? field, string? detail) =>
        (field, detail) switch
        {
            (not null, not null) => $"{field}: {detail}",
            (null, not null) => detail,
            _ => "REVA could not accept that input.",
        };
}
