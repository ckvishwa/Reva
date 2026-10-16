using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Reva.Desktop.Services;

namespace Reva.Desktop.Devices;

/// <summary>
/// HTTP implementation of <see cref="IDevicesApi"/> over REVA Core's loopback Devices routes. Same shared
/// <see cref="HttpClient"/> and local-token provider as the other clients; the token is only ever put in the
/// Authorization header. Every failure becomes a <see cref="DevicesError"/>.
/// </summary>
public sealed class DevicesApiClient : IDevicesApi
{
    private const string Base = "v1/devices";
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _http;
    private readonly ILocalTokenProvider _tokens;
    private readonly TimeSpan _timeout;

    public DevicesApiClient(HttpClient http, ILocalTokenProvider tokens, TimeSpan? timeout = null)
    {
        _http = http;
        _tokens = tokens;
        _timeout = timeout ?? DesktopConfiguration.DefaultRequestTimeout;
    }

    public Task<DevicesResult<DevicesSnapshot>> GetAsync(CancellationToken ct = default) =>
        SendAsync<DevicesSnapshot>(HttpMethod.Get, Base, null, ct);

    public async Task<DevicesResult<GatewayStatus>> SetGatewayEnabledAsync(bool enabled, CancellationToken ct = default)
    {
        var result = await SendAsync<GatewayEnvelope>(
            HttpMethod.Patch, $"{Base}/gateway", new JsonObject { ["enabled"] = enabled }, ct);
        return result.IsSuccess
            ? DevicesResult<GatewayStatus>.Success(result.Value!.Gateway)
            : DevicesResult<GatewayStatus>.Failure(result.Error!);
    }

    public Task<DevicesResult<OpenedPairing>> OpenPairingAsync(CancellationToken ct = default) =>
        SendAsync<OpenedPairing>(HttpMethod.Post, $"{Base}/pairing", null, ct);

    public Task<DevicesResult<ApprovedPairing>> ApprovePairingAsync(string fingerprint, CancellationToken ct = default) =>
        SendAsync<ApprovedPairing>(
            HttpMethod.Post, $"{Base}/pairing/approve", new JsonObject { ["fingerprint"] = fingerprint }, ct);

    public Task<DevicesResult<DeniedPairing>> DenyPairingAsync(CancellationToken ct = default) =>
        SendAsync<DeniedPairing>(HttpMethod.Post, $"{Base}/pairing/deny", null, ct);

    public Task<DevicesResult<RevokeOutcome>> RevokeAsync(string deviceId, CancellationToken ct = default) =>
        SendAsync<RevokeOutcome>(
            HttpMethod.Post, $"{Base}/{Uri.EscapeDataString(deviceId)}/revoke", null, ct);

    public Task<DevicesResult<PhoneAccessOutcome>> SetPhoneAccessAsync(
        string deviceId, bool openApps, bool closeApps, CancellationToken ct = default) =>
        SendAsync<PhoneAccessOutcome>(
            HttpMethod.Patch,
            $"{Base}/{Uri.EscapeDataString(deviceId)}/pc-access",
            new JsonObject { ["open_apps"] = openApps, ["close_apps"] = closeApps },
            ct);

    private async Task<DevicesResult<T>> SendAsync<T>(HttpMethod method, string path, JsonObject? body, CancellationToken ct)
    {
        var token = await _tokens.GetTokenAsync(ct).ConfigureAwait(false);
        if (!token.IsAvailable)
        {
            return DevicesResult<T>.Failure(new DevicesError(DevicesErrorKind.Unauthorized, "REVA authorization is unavailable."));
        }

        using var request = new HttpRequestMessage(method, path);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
        if (body is not null)
        {
            request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        }

        using var timeoutCts = new CancellationTokenSource(_timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, timeoutCts.Token);
        HttpResponseMessage response;
        try
        {
            response = await _http.SendAsync(request, HttpCompletionOption.ResponseContentRead, linked.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return DevicesResult<T>.Failure(new DevicesError(DevicesErrorKind.Timeout, "REVA Core did not respond in time."));
        }
        catch (HttpRequestException)
        {
            return DevicesResult<T>.Failure(new DevicesError(DevicesErrorKind.Unavailable, "REVA Core is not reachable."));
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                return DevicesResult<T>.Failure(await InterpretAsync(response, ct).ConfigureAwait(false));
            }

            try
            {
                var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
                var value = await JsonSerializer.DeserializeAsync<T>(stream, JsonOptions, ct).ConfigureAwait(false);
                return value is null
                    ? DevicesResult<T>.Failure(new DevicesError(DevicesErrorKind.InvalidResponse, "REVA Core returned an empty response."))
                    : DevicesResult<T>.Success(value);
            }
            catch (JsonException)
            {
                return DevicesResult<T>.Failure(
                    new DevicesError(DevicesErrorKind.InvalidResponse, "REVA Core returned a response REVA could not read."));
            }
        }
    }

    private static async Task<DevicesError> InterpretAsync(HttpResponseMessage response, CancellationToken ct)
    {
        string? code = null;
        string? detail = null;
        try
        {
            var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            if (JsonNode.Parse(text) is JsonObject body)
            {
                code = body["error"]?.GetValue<string>();
                detail = body["detail"]?.GetValue<string>();
            }
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException)
        {
            // A body that is not our error shape carries no detail.
        }

        return (int)response.StatusCode switch
        {
            401 => new DevicesError(DevicesErrorKind.Unauthorized, "REVA Core rejected local authentication.", code),
            404 => new DevicesError(DevicesErrorKind.NotFound, "That device was not found.", code),
            422 => new DevicesError(DevicesErrorKind.Validation, "REVA could not accept that input.", code, detail),
            409 => Conflict(code, detail),
            >= 500 => new DevicesError(DevicesErrorKind.ServerFailure, "REVA Core reported an internal error.", code),
            _ => new DevicesError(DevicesErrorKind.InvalidResponse, "REVA Core returned an unexpected response.", code),
        };
    }

    private static DevicesError Conflict(string? code, string? detail) => code switch
    {
        "gateway_off" => new DevicesError(DevicesErrorKind.GatewayOff, "Turn the pairing gateway on first.", code),
        "gateway_unavailable" => new DevicesError(
            DevicesErrorKind.GatewayOff, detail ?? "The pairing gateway could not start.", code, detail),
        "nothing_to_approve" => new DevicesError(DevicesErrorKind.State, "No phone is waiting for approval.", code),
        "fingerprint_mismatch" => new DevicesError(
            DevicesErrorKind.State, "Those digits do not match the pairing in progress. Nothing was approved.", code),
        "kernel_refused" => new DevicesError(
            DevicesErrorKind.State, "REVA refused this phone because it claims another device's identity.", code),
        _ => new DevicesError(DevicesErrorKind.State, "That does not fit the current pairing.", code, detail),
    };
}
