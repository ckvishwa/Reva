using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Reva.Desktop.Services;

namespace Reva.Desktop.Voice;

/// <summary>
/// Core voice session over HTTP + WebSocket. Loopback only (the base URL is already validated by
/// <see cref="DesktopConfiguration"/>). The Bearer token is read per call from the token provider
/// and sent only in the Authorization header: never in a URL, a log line or an error message.
/// </summary>
public sealed partial class VoiceSessionClient : IVoiceSessionClient
{
    [GeneratedRegex("^/v1/voice/sessions/[A-Za-z0-9_-]+/audio/[A-Za-z0-9_-]+$")]
    private static partial Regex ReplyAudioPath();

    private const int MaxEventBytes = 256 * 1024;
    private const int MaxReplyBytes = 10 * 1024 * 1024;

    private readonly HttpClient _http;
    private readonly ILocalTokenProvider _tokens;
    private readonly Uri _baseUrl;
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private ClientWebSocket? _socket;
    private CancellationTokenSource? _receiveCancel;
    private Task? _receiver;
    private string? _sessionId;
    private int _closing;

    public VoiceSessionClient(HttpClient http, ILocalTokenProvider tokens, Uri baseUrl)
    {
        _http = http;
        _tokens = tokens;
        _baseUrl = baseUrl;
    }

    public event Action<VoiceEvent>? EventReceived;

    public event Action<string>? Disconnected;

    public bool IsConnected => _socket is { State: WebSocketState.Open };

    public async Task<string?> ConnectAsync(CancellationToken cancellationToken = default)
    {
        var token = await _tokens.GetTokenAsync(cancellationToken);
        if (!token.IsAvailable)
        {
            return "REVA Core isn't ready yet.";
        }

        try
        {
            using var create = new HttpRequestMessage(HttpMethod.Post, new Uri(_baseUrl, "v1/voice/sessions"))
            {
                Content = JsonContent.Create(new { }),
            };
            create.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
            using var response = await _http.SendAsync(create, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                return response.StatusCode == System.Net.HttpStatusCode.TooManyRequests
                    ? "Voice is already open somewhere else."
                    : "REVA Core refused to start voice.";
            }

            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
            _sessionId = json.RootElement.GetProperty("session_id").GetString();
            var eventsPath = json.RootElement.GetProperty("events_path").GetString();
            if (_sessionId is null || eventsPath is null)
            {
                return "REVA Core sent an unexpected reply.";
            }

            var socket = new ClientWebSocket();
            socket.Options.SetRequestHeader("Authorization", $"Bearer {token.Token}");
            var builder = new UriBuilder(_baseUrl) { Scheme = _baseUrl.Scheme == "https" ? "wss" : "ws" };
            builder.Path = eventsPath;
            await socket.ConnectAsync(builder.Uri, cancellationToken);
            _socket = socket;
            Interlocked.Exchange(ref _closing, 0);
            _receiveCancel = new CancellationTokenSource();
            _receiver = Task.Run(() => ReceiveLoopAsync(socket, _receiveCancel.Token), CancellationToken.None);
            return null;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex) when (ex is HttpRequestException or WebSocketException or JsonException
            or KeyNotFoundException or InvalidOperationException)
        {
            return "REVA Core isn't reachable.";
        }
    }

    public async Task SendControlAsync(string type, int? turnEpoch = null, CancellationToken cancellationToken = default)
    {
        var message = turnEpoch is null
            ? JsonSerializer.Serialize(new { type })
            : JsonSerializer.Serialize(new { type, turn_epoch = turnEpoch });
        await SendAsync(Encoding.UTF8.GetBytes(message), WebSocketMessageType.Text, cancellationToken);
    }

    public Task SendAudioAsync(byte[] pcm, CancellationToken cancellationToken = default) =>
        SendAsync(pcm, WebSocketMessageType.Binary, cancellationToken);

    public async Task<byte[]?> FetchAudioAsync(string path, CancellationToken cancellationToken = default)
    {
        var token = await _tokens.GetTokenAsync(cancellationToken);
        if (!token.IsAvailable
            || _sessionId is null
            || !ReplyAudioPath().IsMatch(path)
            || !path.StartsWith($"/v1/voice/sessions/{_sessionId}/audio/", StringComparison.Ordinal))
        {
            return null; // only this session's reply audio is ever fetched, nothing else on Core
        }

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(_baseUrl, path.TrimStart('/')));
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
            using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (!response.IsSuccessStatusCode
                || response.Content.Headers.ContentLength is > MaxReplyBytes)
            {
                return null;
            }

            var bytes = await response.Content.ReadAsByteArrayAsync(cancellationToken);
            return bytes.Length is > 0 and <= MaxReplyBytes ? bytes : null;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            return null;
        }
    }

    public async Task CloseAsync()
    {
        Interlocked.Exchange(ref _closing, 1);
        var socket = _socket;
        _socket = null;
        _receiveCancel?.Cancel();
        if (socket is not null)
        {
            try
            {
                if (socket.State == WebSocketState.Open)
                {
                    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                    await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "bye", timeout.Token);
                }
            }
            catch (Exception)
            {
                // closing a broken socket is not an error
            }

            socket.Dispose();
        }

        if (_receiver is not null)
        {
            try
            {
                await _receiver;
            }
            catch (Exception)
            {
            }

            _receiver = null;
        }

        await DeleteSessionAsync();
    }

    public async ValueTask DisposeAsync()
    {
        await CloseAsync();
        _sendLock.Dispose();
    }

    private async Task DeleteSessionAsync()
    {
        var sessionId = _sessionId;
        _sessionId = null;
        if (sessionId is null)
        {
            return;
        }

        try
        {
            var token = await _tokens.GetTokenAsync();
            if (!token.IsAvailable)
            {
                return;
            }

            using var request = new HttpRequestMessage(HttpMethod.Delete, new Uri(_baseUrl, $"v1/voice/sessions/{sessionId}"));
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            using var _ = await _http.SendAsync(request, timeout.Token);
        }
        catch (Exception)
        {
            // Core also closes the session when the socket drops.
        }
    }

    private async Task SendAsync(byte[] data, WebSocketMessageType type, CancellationToken cancellationToken)
    {
        var socket = _socket;
        if (socket is not { State: WebSocketState.Open })
        {
            return;
        }

        await _sendLock.WaitAsync(cancellationToken);
        try
        {
            await socket.SendAsync(data, type, true, cancellationToken);
        }
        catch (Exception ex) when (ex is WebSocketException or ObjectDisposedException)
        {
            RaiseDisconnected();
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private async Task ReceiveLoopAsync(ClientWebSocket socket, CancellationToken cancellationToken)
    {
        var buffer = new byte[16 * 1024];
        using var message = new MemoryStream();
        try
        {
            while (!cancellationToken.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                message.SetLength(0);
                WebSocketReceiveResult result;
                do
                {
                    result = await socket.ReceiveAsync(buffer, cancellationToken);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        RaiseDisconnected();
                        return;
                    }

                    message.Write(buffer, 0, result.Count);
                    if (message.Length > MaxEventBytes)
                    {
                        RaiseDisconnected();
                        return;
                    }
                }
                while (!result.EndOfMessage);

                if (result.MessageType == WebSocketMessageType.Text)
                {
                    Dispatch(message.ToArray());
                }
            }
        }
        catch (Exception ex) when (ex is OperationCanceledException or WebSocketException or ObjectDisposedException)
        {
            if (!cancellationToken.IsCancellationRequested)
            {
                RaiseDisconnected();
            }
        }
    }

    private void Dispatch(byte[] json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            var kind = root.GetProperty("kind").GetString();
            var epoch = root.TryGetProperty("turn_epoch", out var e) && e.TryGetInt32(out var n) ? n : 0;
            var payload = root.TryGetProperty("payload", out var p) ? p.Clone() : default;
            if (kind is not null)
            {
                EventReceived?.Invoke(new VoiceEvent(kind, epoch, payload));
            }
        }
        catch (Exception ex) when (ex is JsonException or KeyNotFoundException or InvalidOperationException)
        {
            // A malformed event is dropped; it never stops the loop.
        }
    }

    private void RaiseDisconnected()
    {
        if (Interlocked.Exchange(ref _closing, 1) == 0)
        {
            Disconnected?.Invoke("The connection to REVA Core was lost.");
        }
    }
}
