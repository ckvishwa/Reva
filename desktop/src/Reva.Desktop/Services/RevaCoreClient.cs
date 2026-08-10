using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using Reva.Desktop.Contracts;

namespace Reva.Desktop.Services;

/// <summary>
/// HttpClient-backed <see cref="IRevaCoreClient"/>. One shared HttpClient
/// instance (caller-owned, injected) — never created per-request.
/// </summary>
public sealed class RevaCoreClient : IRevaCoreClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _httpClient;
    private readonly ILocalTokenProvider _tokenProvider;

    public RevaCoreClient(HttpClient httpClient, ILocalTokenProvider tokenProvider)
    {
        _httpClient = httpClient;
        _tokenProvider = tokenProvider;
    }

    public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
        SendAsync<HealthStatus>(HttpMethod.Get, "health", requiresAuth: false, cancellationToken);

    public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
        SendAsync<VersionInfo>(HttpMethod.Get, "version", requiresAuth: false, cancellationToken);

    private async Task<CoreResult<T>> SendAsync<T>(
        HttpMethod method,
        string relativePath,
        bool requiresAuth,
        CancellationToken cancellationToken,
        HttpContent? content = null)
    {
        using var request = new HttpRequestMessage(method, relativePath);
        if (content is not null)
        {
            request.Content = content;
        }

        if (requiresAuth)
        {
            var tokenResult = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
            if (!tokenResult.IsAvailable)
            {
                return CoreResult<T>.Failure(
                    CoreErrorKind.CoreUnauthorized, "REVA authorization is unavailable.");
            }

            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", tokenResult.Token);
        }

        HttpResponseMessage response;
        try
        {
            response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            // HttpClient throws TaskCanceledException for its own Timeout,
            // distinct from caller-requested cancellation (which we let
            // propagate normally rather than normalizing).
            return CoreResult<T>.Failure(CoreErrorKind.CoreTimeout, "REVA Core did not respond in time.");
        }
        catch (HttpRequestException)
        {
            return CoreResult<T>.Failure(CoreErrorKind.CoreUnavailable, "REVA Core is not reachable.");
        }

        using (response)
        {
            return await InterpretResponseAsync<T>(response, cancellationToken).ConfigureAwait(false);
        }
    }

    private static async Task<CoreResult<T>> InterpretResponseAsync<T>(
        HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.StatusCode == HttpStatusCode.Unauthorized)
        {
            return CoreResult<T>.Failure(
                CoreErrorKind.CoreUnauthorized, "REVA Core rejected local authentication.");
        }

        if ((int)response.StatusCode >= 500)
        {
            return CoreResult<T>.Failure(
                CoreErrorKind.CoreServerFailure, "REVA Core reported an internal error.");
        }

        if (!response.IsSuccessStatusCode)
        {
            return CoreResult<T>.Failure(
                CoreErrorKind.CoreInvalidResponse, "REVA Core returned an unexpected response.");
        }

        try
        {
            var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
            var value = await JsonSerializer.DeserializeAsync<T>(stream, JsonOptions, cancellationToken)
                .ConfigureAwait(false);
            return value is null
                ? CoreResult<T>.Failure(CoreErrorKind.CoreInvalidResponse, "REVA Core returned an empty response.")
                : CoreResult<T>.Success(value);
        }
        catch (JsonException)
        {
            return CoreResult<T>.Failure(
                CoreErrorKind.CoreInvalidResponse, "REVA Core returned a response REVA could not parse.");
        }
    }
}
