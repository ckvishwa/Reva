using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Reva.Desktop.Services;

namespace Reva.Desktop.Settings;

public sealed record CloudDisclosure(
    [property: JsonPropertyName("sent_when_on")] IReadOnlyList<string> SentWhenOn,
    [property: JsonPropertyName("never_sent")] IReadOnlyList<string> NeverSent,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("fallback")] string Fallback);

public sealed record CloudSettingsSnapshot(
    [property: JsonPropertyName("enabled")] bool Enabled,
    [property: JsonPropertyName("domains")] IReadOnlyDictionary<string, bool> Domains,
    [property: JsonPropertyName("key_configured")] bool KeyConfigured,
    [property: JsonPropertyName("model")] string Model,
    [property: JsonPropertyName("timeout_seconds")] double TimeoutSeconds,
    [property: JsonPropertyName("disclosure")] CloudDisclosure Disclosure);

/// <summary>A display-ready failure. The message never carries a token or key.</summary>
public sealed record SettingsError(string SafeMessage, string? Code = null);

public sealed class SettingsResult<T>
{
    private SettingsResult(T? value, SettingsError? error)
    {
        Value = value;
        Error = error;
    }

    public bool IsSuccess => Error is null;

    public T? Value { get; }

    public SettingsError? Error { get; }

    public static SettingsResult<T> Success(T value) => new(value, null);

    public static SettingsResult<T> Failure(SettingsError error) => new(default, error);
}

public interface ICloudSettingsApi
{
    Task<SettingsResult<CloudSettingsSnapshot>> GetAsync(CancellationToken ct = default);

    Task<SettingsResult<CloudSettingsSnapshot>> SetEnabledAsync(bool enabled, CancellationToken ct = default);

    Task<SettingsResult<CloudSettingsSnapshot>> SetDomainAsync(string domain, bool allowed, CancellationToken ct = default);

    /// <summary>Stores the key in Credential Manager through Core. The key is sent once and not kept.</summary>
    Task<SettingsResult<CloudSettingsSnapshot>> StoreKeyAsync(string apiKey, CancellationToken ct = default);

    Task<SettingsResult<CloudSettingsSnapshot>> RemoveKeyAsync(CancellationToken ct = default);
}

/// <summary>HTTP implementation over Core's loopback <c>/v1/settings/cloud</c> routes.</summary>
public sealed class CloudSettingsApi : ICloudSettingsApi
{
    private const string Base = "v1/settings/cloud";
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _http;
    private readonly ILocalTokenProvider _tokens;
    private readonly TimeSpan _timeout;

    public CloudSettingsApi(HttpClient http, ILocalTokenProvider tokens, TimeSpan? timeout = null)
    {
        _http = http;
        _tokens = tokens;
        _timeout = timeout ?? DesktopConfiguration.DefaultRequestTimeout;
    }

    public Task<SettingsResult<CloudSettingsSnapshot>> GetAsync(CancellationToken ct = default) =>
        SendAsync(HttpMethod.Get, Base, null, ct);

    public Task<SettingsResult<CloudSettingsSnapshot>> SetEnabledAsync(bool enabled, CancellationToken ct = default) =>
        SendAsync(HttpMethod.Put, Base, new JsonObject { ["enabled"] = enabled }, ct);

    public Task<SettingsResult<CloudSettingsSnapshot>> SetDomainAsync(string domain, bool allowed, CancellationToken ct = default) =>
        SendAsync(HttpMethod.Put, Base, new JsonObject { ["domains"] = new JsonObject { [domain] = allowed } }, ct);

    public Task<SettingsResult<CloudSettingsSnapshot>> StoreKeyAsync(string apiKey, CancellationToken ct = default) =>
        SendAsync(HttpMethod.Put, $"{Base}/key", new JsonObject { ["api_key"] = apiKey }, ct);

    public Task<SettingsResult<CloudSettingsSnapshot>> RemoveKeyAsync(CancellationToken ct = default) =>
        SendAsync(HttpMethod.Delete, $"{Base}/key", null, ct);

    private async Task<SettingsResult<CloudSettingsSnapshot>> SendAsync(
        HttpMethod method, string path, JsonObject? body, CancellationToken ct)
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
        HttpResponseMessage response;
        try
        {
            response = await _http.SendAsync(request, linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return Fail("REVA Core did not respond in time.");
        }
        catch (HttpRequestException)
        {
            return Fail("REVA Core is not reachable.");
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                return await InterpretAsync(response, ct).ConfigureAwait(false);
            }

            try
            {
                var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
                var value = await JsonSerializer.DeserializeAsync<CloudSettingsSnapshot>(stream, JsonOptions, ct)
                    .ConfigureAwait(false);
                return value is null ? Fail("REVA Core returned an empty response.") : SettingsResult<CloudSettingsSnapshot>.Success(value);
            }
            catch (JsonException)
            {
                return Fail("REVA Core returned a response REVA could not read.");
            }
        }
    }

    private static async Task<SettingsResult<CloudSettingsSnapshot>> InterpretAsync(HttpResponseMessage response, CancellationToken ct)
    {
        string? code = null;
        try
        {
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (JsonNode.Parse(text) is JsonObject body)
            {
                code = body["error"]?.GetValue<string>();
            }
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException)
        {
            // not our error shape: no detail
        }

        var message = (int)response.StatusCode switch
        {
            401 => "REVA Core rejected local authentication.",
            409 when code == "key_required" => "Add your Anthropic key first, then switch cloud on.",
            422 when code == "invalid_key" => "That doesn't look like an Anthropic API key (it starts with sk-ant-).",
            422 => "REVA could not accept that setting.",
            503 => "Windows Credential Manager isn't available, so the key can't be stored.",
            >= 500 => "REVA Core reported an internal error.",
            _ => "REVA Core returned an unexpected response.",
        };
        return SettingsResult<CloudSettingsSnapshot>.Failure(new SettingsError(message, code));
    }

    private static SettingsResult<CloudSettingsSnapshot> Fail(string message) =>
        SettingsResult<CloudSettingsSnapshot>.Failure(new SettingsError(message));
}
