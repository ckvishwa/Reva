using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
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

    public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
        string content, CancellationToken cancellationToken = default)
    {
        var body = JsonContent.Create(new TypedMessageRequest(content), options: JsonOptions);
        return SendAsync<TypedMessageResponse>(HttpMethod.Post, "v1/messages", requiresAuth: true, cancellationToken, body);
    }

    public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
        string content, CancellationToken cancellationToken = default)
    {
        var body = JsonContent.Create(new MemoryCreateRequest(content), options: JsonOptions);
        return SendAsync<MemoryCreateResponse>(HttpMethod.Post, "v1/memories", requiresAuth: true, cancellationToken, body);
    }

    public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
        string query, int limit, CancellationToken cancellationToken = default)
    {
        var relativePath = $"v1/memories?q={Uri.EscapeDataString(query)}&limit={limit}";
        return SendAsync<MemoryQueryResponse>(HttpMethod.Get, relativePath, requiresAuth: true, cancellationToken);
    }

    public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
        byte[] wavAudio, CancellationToken cancellationToken = default)
    {
        var body = new ByteArrayContent(wavAudio);
        body.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
        return SendAsync<VoiceTranscriptionResponse>(
            HttpMethod.Post,
            "v1/voice/transcriptions",
            requiresAuth: true,
            cancellationToken,
            body,
            voiceRequest: true);
    }

    public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(
        string text, string language, CancellationToken cancellationToken = default)
    {
        var body = JsonContent.Create(new VoiceSpeechRequest(text, language), options: JsonOptions);
        return SendBytesAsync(
            HttpMethod.Post,
            "v1/voice/speech",
            requiresAuth: true,
            cancellationToken,
            body);
    }

    private async Task<CoreResult<T>> SendAsync<T>(
        HttpMethod method,
        string relativePath,
        bool requiresAuth,
        CancellationToken cancellationToken,
        HttpContent? content = null,
        bool voiceRequest = false)
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
            return await InterpretResponseAsync<T>(response, cancellationToken, voiceRequest)
                .ConfigureAwait(false);
        }
    }

    private async Task<CoreResult<byte[]>> SendBytesAsync(
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
                return CoreResult<byte[]>.Failure(
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
            return CoreResult<byte[]>.Failure(CoreErrorKind.CoreTimeout, "REVA voice did not respond in time.");
        }
        catch (HttpRequestException)
        {
            return CoreResult<byte[]>.Failure(CoreErrorKind.CoreUnavailable, "REVA Core is not reachable.");
        }

        using (response)
        {
            if (response.StatusCode == HttpStatusCode.Unauthorized)
            {
                return CoreResult<byte[]>.Failure(
                    CoreErrorKind.CoreUnauthorized, "REVA Core rejected local authentication.");
            }

            if (response.StatusCode == HttpStatusCode.ServiceUnavailable)
            {
                return CoreResult<byte[]>.Failure(
                    CoreErrorKind.CoreUnavailable, "REVA voice is unavailable.");
            }

            if (response.StatusCode == HttpStatusCode.GatewayTimeout)
            {
                return CoreResult<byte[]>.Failure(
                    CoreErrorKind.CoreTimeout, "REVA voice did not respond in time.");
            }

            if (!response.IsSuccessStatusCode)
            {
                return CoreResult<byte[]>.Failure(
                    CoreErrorKind.CoreInvalidResponse, "REVA Core returned an unexpected response.");
            }

            var bytes = await response.Content.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
            return bytes.Length == 0
                ? CoreResult<byte[]>.Failure(CoreErrorKind.CoreInvalidResponse, "REVA Core returned an empty response.")
                : CoreResult<byte[]>.Success(bytes);
        }
    }

    private static async Task<CoreResult<T>> InterpretResponseAsync<T>(
        HttpResponseMessage response, CancellationToken cancellationToken, bool voiceRequest = false)
    {
        if (response.StatusCode == HttpStatusCode.Unauthorized)
        {
            return CoreResult<T>.Failure(
                CoreErrorKind.CoreUnauthorized, "REVA Core rejected local authentication.");
        }

        if (voiceRequest && response.StatusCode == HttpStatusCode.ServiceUnavailable)
        {
            return CoreResult<T>.Failure(CoreErrorKind.CoreUnavailable, "REVA voice is unavailable.");
        }

        if (voiceRequest && response.StatusCode == HttpStatusCode.GatewayTimeout)
        {
            return CoreResult<T>.Failure(CoreErrorKind.CoreTimeout, "REVA voice did not respond in time.");
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
