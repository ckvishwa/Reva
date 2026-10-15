using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Reva.Desktop.Services;
using Reva.Desktop.Settings;

namespace Reva.Desktop.Actions;

public sealed record ActionState(
    string ActionId,
    string Capability,
    string Status,
    string? Speak,
    string? Prompt,
    DateTimeOffset? Deadline,
    ActionOrder? Order);

public sealed record AppRow(string Key, string DisplayName, IReadOnlyList<string> Aliases, bool Builtin);

public sealed record WaitingApp(string Key, string DisplayName);

public sealed record AppsSnapshot(IReadOnlyList<AppRow> Apps, IReadOnlyList<WaitingApp> Waiting);

public sealed record ActivityRow(string Time, string Request, string From, string Result, string? Evidence);

public interface IActionsApi
{
    /// <summary>A click on the confirm card. <paramref name="via"/> is always "click" from this app.</summary>
    Task<SettingsResult<ActionState>> DecideAsync(string actionId, bool approve, CancellationToken ct = default);

    /// <summary>The executor's report. The Core turns it into words; this app never does.</summary>
    Task<SettingsResult<ActionState>> ReportAsync(
        string actionId, string grantId, ActionReport report, CancellationToken ct = default);

    Task<SettingsResult<AppsSnapshot>> GetAppsAsync(CancellationToken ct = default);

    Task<SettingsResult<AppsSnapshot>> ReportDiscoveredAsync(
        IReadOnlyList<(string Key, string DisplayName)> found, CancellationToken ct = default);

    Task<SettingsResult<AppsSnapshot>> ApproveAppAsync(
        string key, string? displayName, IReadOnlyList<string> aliases, CancellationToken ct = default);

    Task<SettingsResult<AppsSnapshot>> RemoveAppAsync(string key, CancellationToken ct = default);

    Task<SettingsResult<IReadOnlyList<ActivityRow>>> GetActivityAsync(int limit, CancellationToken ct = default);
}

/// <summary>HTTP over Core's loopback <c>/v1/actions</c>, <c>/v1/apps</c> and <c>/v1/activity</c>.</summary>
public sealed class ActionsApi : IActionsApi
{
    private readonly HttpClient _http;
    private readonly ILocalTokenProvider _tokens;
    private readonly TimeSpan _timeout;

    public ActionsApi(HttpClient http, ILocalTokenProvider tokens, TimeSpan? timeout = null)
    {
        _http = http;
        _tokens = tokens;
        _timeout = timeout ?? DesktopConfiguration.DefaultRequestTimeout;
    }

    public async Task<SettingsResult<ActionState>> DecideAsync(string actionId, bool approve, CancellationToken ct = default) =>
        Map(await SendAsync(
            HttpMethod.Post,
            $"v1/actions/{Uri.EscapeDataString(actionId)}/approval",
            new JsonObject { ["decision"] = approve ? "approve" : "deny", ["via"] = "click" },
            ct).ConfigureAwait(false), ParseAction);

    public async Task<SettingsResult<ActionState>> ReportAsync(
        string actionId, string grantId, ActionReport report, CancellationToken ct = default)
    {
        var body = new JsonObject { ["grant_id"] = grantId, ["status"] = report.Status };
        if (report.Evidence is { } evidence)
        {
            body["evidence"] = new JsonObject { ["kind"] = evidence.Kind, ["ref"] = evidence.Reference };
        }

        return Map(
            await SendAsync(HttpMethod.Put, $"v1/actions/{Uri.EscapeDataString(actionId)}", body, ct).ConfigureAwait(false),
            ParseAction);
    }

    public async Task<SettingsResult<AppsSnapshot>> GetAppsAsync(CancellationToken ct = default) =>
        Map(await SendAsync(HttpMethod.Get, "v1/apps", null, ct).ConfigureAwait(false), ParseApps);

    public async Task<SettingsResult<AppsSnapshot>> ReportDiscoveredAsync(
        IReadOnlyList<(string Key, string DisplayName)> found, CancellationToken ct = default)
    {
        var apps = new JsonArray();
        foreach (var (key, name) in found)
        {
            apps.Add(new JsonObject { ["key"] = key, ["display_name"] = name });
        }

        return Map(
            await SendAsync(HttpMethod.Put, "v1/apps/discovered", new JsonObject { ["apps"] = apps }, ct).ConfigureAwait(false),
            ParseApps);
    }

    public async Task<SettingsResult<AppsSnapshot>> ApproveAppAsync(
        string key, string? displayName, IReadOnlyList<string> aliases, CancellationToken ct = default)
    {
        var body = new JsonObject { ["aliases"] = new JsonArray(aliases.Select(a => (JsonNode?)JsonValue.Create(a)).ToArray()) };
        if (displayName is not null)
        {
            body["display_name"] = displayName;
        }

        return Map(
            await SendAsync(HttpMethod.Put, $"v1/apps/{Uri.EscapeDataString(key)}", body, ct).ConfigureAwait(false),
            ParseApps);
    }

    public async Task<SettingsResult<AppsSnapshot>> RemoveAppAsync(string key, CancellationToken ct = default) =>
        Map(await SendAsync(HttpMethod.Delete, $"v1/apps/{Uri.EscapeDataString(key)}", null, ct).ConfigureAwait(false), ParseApps);

    public async Task<SettingsResult<IReadOnlyList<ActivityRow>>> GetActivityAsync(int limit, CancellationToken ct = default) =>
        Map(await SendAsync(HttpMethod.Get, $"v1/activity?limit={limit}", null, ct).ConfigureAwait(false), ParseActivity);

    // ------------------------------------------------------------------ parsing

    public static ActionState? ParseAction(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        string? Text(string name) =>
            root.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

        var id = Text("action_id");
        var status = Text("status");
        if (id is null || status is null)
        {
            return null;
        }

        DateTimeOffset? deadline = DateTimeOffset.TryParse(Text("deadline"), out var parsed) ? parsed : null;
        return new ActionState(id, Text("capability") ?? string.Empty, status, Text("speak"), Text("prompt"), deadline, ParseOrder(root));
    }

    public static ActionOrder? ParseOrder(JsonElement root)
    {
        if (!root.TryGetProperty("order", out var order) || order.ValueKind != JsonValueKind.Object
            || !order.TryGetProperty("grant", out var grantElement)
            || !GrantVerifier.TryParseGrant(grantElement, out var grant)
            || !order.TryGetProperty("signature", out var signature) || signature.ValueKind != JsonValueKind.String
            || !order.TryGetProperty("capability", out var capability) || capability.ValueKind != JsonValueKind.String
            || !order.TryGetProperty("args", out var args))
        {
            return null;
        }

        var target = order.TryGetProperty("target_device_id", out var t) && t.ValueKind == JsonValueKind.String ? t.GetString()! : string.Empty;
        return new ActionOrder(grant, signature.GetString()!, capability.GetString()!, args.Clone(), target);
    }

    private static AppsSnapshot? ParseApps(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("apps", out var apps) || apps.ValueKind != JsonValueKind.Array)
        {
            return null;
        }

        var rows = apps.EnumerateArray()
            .Select(a => new AppRow(
                a.GetProperty("key").GetString() ?? string.Empty,
                a.GetProperty("display_name").GetString() ?? string.Empty,
                a.GetProperty("aliases").EnumerateArray().Select(x => x.GetString() ?? string.Empty).ToList(),
                a.GetProperty("builtin").GetBoolean()))
            .ToList();
        var waiting = root.TryGetProperty("waiting", out var w) && w.ValueKind == JsonValueKind.Array
            ? w.EnumerateArray().Select(x => new WaitingApp(x.GetProperty("key").GetString() ?? string.Empty, x.GetProperty("display_name").GetString() ?? string.Empty)).ToList()
            : new List<WaitingApp>();
        return new AppsSnapshot(rows, waiting);
    }

    private static IReadOnlyList<ActivityRow>? ParseActivity(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array)
        {
            return null;
        }

        return items.EnumerateArray()
            .Select(i => new ActivityRow(
                i.GetProperty("time").GetString() ?? string.Empty,
                i.GetProperty("request").GetString() ?? string.Empty,
                i.GetProperty("from").GetString() ?? string.Empty,
                i.GetProperty("result").GetString() ?? string.Empty,
                i.TryGetProperty("evidence", out var e) && e.ValueKind == JsonValueKind.String ? e.GetString() : null))
            .ToList();
    }

    private static SettingsResult<T> Map<T>(SettingsResult<JsonElement> raw, Func<JsonElement, T?> parse)
        where T : class
    {
        if (!raw.IsSuccess)
        {
            return SettingsResult<T>.Failure(raw.Error!);
        }

        try
        {
            var value = parse(raw.Value);
            return value is null
                ? SettingsResult<T>.Failure(new SettingsError("REVA Core returned a response REVA could not read."))
                : SettingsResult<T>.Success(value);
        }
        catch (Exception ex) when (ex is KeyNotFoundException or InvalidOperationException or FormatException)
        {
            return SettingsResult<T>.Failure(new SettingsError("REVA Core returned a response REVA could not read."));
        }
    }

    // ------------------------------------------------------------------ transport

    private async Task<SettingsResult<JsonElement>> SendAsync(HttpMethod method, string path, JsonObject? body, CancellationToken ct)
    {
        var token = await _tokens.GetTokenAsync(ct).ConfigureAwait(false);
        if (!token.IsAvailable)
        {
            return Fail("REVA authorization is unavailable.");
        }

        using var request = new HttpRequestMessage(method, path);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
        if (body is not null)
        {
            request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        }

        using var timeout = new CancellationTokenSource(_timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, timeout.Token);
        try
        {
            using var response = await _http.SendAsync(request, linked.Token).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                return Fail(Describe((int)response.StatusCode, await ReadErrorAsync(response, ct).ConfigureAwait(false)), ErrorCode: (int)response.StatusCode);
            }

            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
            return SettingsResult<JsonElement>.Success(document.RootElement.Clone());
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return Fail("REVA Core did not respond in time.");
        }
        catch (HttpRequestException)
        {
            return Fail("REVA Core is not reachable.");
        }
        catch (JsonException)
        {
            return Fail("REVA Core returned a response REVA could not read.");
        }
    }

    private static async Task<string?> ReadErrorAsync(HttpResponseMessage response, CancellationToken ct)
    {
        try
        {
            return JsonNode.Parse(await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false)) is JsonObject o
                ? o["error"]?.GetValue<string>()
                : null;
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException)
        {
            return null;
        }
    }

    private static string Describe(int status, string? code) => status switch
    {
        401 => "REVA Core rejected local authentication.",
        403 => "REVA Core did not accept that grant.",
        404 => "REVA no longer knows that request.",
        422 => code is { Length: > 0 and < 120 } ? $"REVA could not accept that: {code.Replace('_', ' ')}." : "REVA could not accept that.",
        429 => "Too many requests are waiting. Try again in a moment.",
        503 => "Actions are unavailable because the key vault could not be used.",
        >= 500 => "REVA Core reported an internal error.",
        _ => "REVA Core returned an unexpected response.",
    };

    private static SettingsResult<JsonElement> Fail(string message, int? ErrorCode = null) =>
        SettingsResult<JsonElement>.Failure(new SettingsError(message, ErrorCode?.ToString()));
}
