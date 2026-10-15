using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using Reva.Desktop.Services;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Tests.Voice;

/// <summary>The session client against a small loopback server that speaks Core's protocol.</summary>
public sealed class VoiceSessionClientTests : IAsyncDisposable
{
    private const string Token = "test-token-123";

    private sealed class Tokens : ILocalTokenProvider
    {
        public bool Available = true;

        public Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(Available ? TokenLoadResult.Available(Token) : TokenLoadResult.Unavailable());
    }

    private readonly HttpListener _listener = new();
    private readonly Uri _baseUrl;
    private readonly Tokens _tokens = new();
    private readonly HttpClient _http = new();
    private readonly List<string> _authHeaders = new();
    private readonly List<string> _controls = new();
    private readonly List<int> _audioSizes = new();
    private readonly CancellationTokenSource _stop = new();
    private WebSocket? _serverSocket;
    private readonly TaskCompletionSource _connected = new();
    private int _deleted;
    private HttpStatusCode _createStatus = HttpStatusCode.Created;

    public VoiceSessionClientTests()
    {
        var port = FreePort();
        _baseUrl = new Uri($"http://127.0.0.1:{port}/");
        _listener.Prefixes.Add(_baseUrl.ToString());
        _listener.Start();
        _ = Task.Run(ServeAsync);
    }

    private static int FreePort()
    {
        var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        var port = ((IPEndPoint)probe.LocalEndpoint).Port;
        probe.Stop();
        return port;
    }

    private async Task ServeAsync()
    {
        while (!_stop.IsCancellationRequested)
        {
            HttpListenerContext context;
            try
            {
                context = await _listener.GetContextAsync();
            }
            catch (Exception)
            {
                return;
            }

            _ = Task.Run(() => HandleAsync(context));
        }
    }

    private async Task HandleAsync(HttpListenerContext context)
    {
        var request = context.Request;
        var auth = request.Headers["Authorization"] ?? string.Empty;
        lock (_authHeaders)
        {
            _authHeaders.Add(auth);
        }

        var path = request.Url!.AbsolutePath;
        if (auth != $"Bearer {Token}")
        {
            context.Response.StatusCode = 401;
            context.Response.Close();
            return;
        }

        if (request.HttpMethod == "POST" && path == "/v1/voice/sessions")
        {
            context.Response.StatusCode = (int)_createStatus;
            var body = Encoding.UTF8.GetBytes(
                "{\"session_id\":\"sess-0001\",\"events_path\":\"/v1/voice/sessions/sess-0001/events\"}");
            await context.Response.OutputStream.WriteAsync(body);
            context.Response.Close();
        }
        else if (request.HttpMethod == "DELETE")
        {
            Interlocked.Increment(ref _deleted);
            context.Response.StatusCode = 204;
            context.Response.Close();
        }
        else if (request.HttpMethod == "GET" && path.EndsWith("/audio/a1", StringComparison.Ordinal))
        {
            context.Response.ContentType = "audio/wav";
            await context.Response.OutputStream.WriteAsync(new byte[] { 9, 8, 7 });
            context.Response.Close();
        }
        else if (request.IsWebSocketRequest && path == "/v1/voice/sessions/sess-0001/events")
        {
            var ws = (await context.AcceptWebSocketAsync(null)).WebSocket;
            _serverSocket = ws;
            _connected.TrySetResult();
            var buffer = new byte[8192];
            try
            {
                while (ws.State == WebSocketState.Open)
                {
                    var result = await ws.ReceiveAsync(buffer, _stop.Token);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        break;
                    }

                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        lock (_controls)
                        {
                            _controls.Add(Encoding.UTF8.GetString(buffer, 0, result.Count));
                        }
                    }
                    else
                    {
                        lock (_audioSizes)
                        {
                            _audioSizes.Add(result.Count);
                        }
                    }
                }
            }
            catch (Exception)
            {
            }
        }
        else
        {
            context.Response.StatusCode = 404;
            context.Response.Close();
        }
    }

    private async Task PushAsync(string json)
    {
        await _connected.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await _serverSocket!.SendAsync(Encoding.UTF8.GetBytes(json), WebSocketMessageType.Text, true, CancellationToken.None);
    }

    private static async Task<T> Eventually<T>(Func<T?> read) where T : class
    {
        for (var i = 0; i < 300; i++)
        {
            var value = read();
            if (value is not null)
            {
                return value;
            }

            await Task.Delay(10);
        }

        throw new Xunit.Sdk.XunitException("timed out");
    }

    [Fact]
    public async Task Connect_sends_the_bearer_on_the_session_call_and_on_the_socket_handshake()
    {
        await using var client = new VoiceSessionClient(_http, _tokens, _baseUrl);

        var failure = await client.ConnectAsync();
        await _connected.Task.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.Null(failure);
        Assert.True(client.IsConnected);
        lock (_authHeaders)
        {
            Assert.Equal(2, _authHeaders.Count);
            Assert.All(_authHeaders, h => Assert.Equal($"Bearer {Token}", h));
        }
    }

    [Fact]
    public async Task No_token_means_no_connection_and_no_request()
    {
        _tokens.Available = false;
        await using var client = new VoiceSessionClient(_http, _tokens, _baseUrl);

        var failure = await client.ConnectAsync();

        Assert.Equal("REVA Core isn't ready yet.", failure);
        lock (_authHeaders)
        {
            Assert.Empty(_authHeaders);
        }
    }

    [Fact]
    public async Task A_refused_session_is_reported_with_a_fixed_sentence()
    {
        _createStatus = HttpStatusCode.TooManyRequests;
        await using var client = new VoiceSessionClient(_http, _tokens, _baseUrl);

        var failure = await client.ConnectAsync();

        Assert.Equal("Voice is already open somewhere else.", failure);
        Assert.False(client.IsConnected);
    }

    [Fact]
    public async Task An_unreachable_core_is_reported_not_thrown()
    {
        var dead = new Uri($"http://127.0.0.1:{FreePort()}/");
        await using var client = new VoiceSessionClient(_http, _tokens, dead);

        Assert.Equal("REVA Core isn't reachable.", await client.ConnectAsync());
    }

    [Fact]
    public async Task Controls_are_json_text_and_audio_is_binary()
    {
        await using var client = new VoiceSessionClient(_http, _tokens, _baseUrl);
        await client.ConnectAsync();

        await client.SendControlAsync("ptt.down");
        await client.SendControlAsync("playback.finished", 4);
        await client.SendAudioAsync(new byte[640]);

        var controls = await Eventually(() =>
        {
            lock (_controls)
            {
                return _controls.Count >= 2 ? _controls.ToArray() : null;
            }
        });
        Assert.Equal("{\"type\":\"ptt.down\"}", controls[0]);
        Assert.Equal("{\"type\":\"playback.finished\",\"turn_epoch\":4}", controls[1]);
        await Eventually(() =>
        {
            lock (_audioSizes)
            {
                return _audioSizes.Count > 0 ? _audioSizes.ToArray() : null;
            }
        });
        lock (_audioSizes)
        {
            Assert.Equal(640, _audioSizes[0]);
        }
    }

    [Fact]
    public async Task Events_are_parsed_and_a_malformed_one_is_dropped_without_stopping_the_loop()
    {
        await using var client = new VoiceSessionClient(_http, _tokens, _baseUrl);
        var received = new List<VoiceEvent>();
        client.EventReceived += e =>
        {
            lock (received)
            {
                received.Add(e);
            }
        };
        await client.ConnectAsync();

        await PushAsync("not json");
        await PushAsync("{\"nokind\":true}");
        await PushAsync("{\"kind\":\"speech.transcript.final\",\"turn_epoch\":2,\"payload\":{\"text\":\"hello\"}}");

        var events = await Eventually(() =>
        {
            lock (received)
            {
                return received.Count >= 1 ? received.ToArray() : null;
            }
        });
        Assert.Single(events);
        Assert.Equal("speech.transcript.final", events[0].Kind);
        Assert.Equal(2, events[0].TurnEpoch);
        Assert.Equal("hello", events[0].Text("text"));
    }

    [Fact]
    public async Task Reply_audio_is_fetched_with_the_bearer_and_foreign_paths_are_refused()
    {
        await using var client = new VoiceSessionClient(_http, _tokens, _baseUrl);
        await client.ConnectAsync();

        var wav = await client.FetchAudioAsync("/v1/voice/sessions/sess-0001/audio/a1");
        var other = await client.FetchAudioAsync("/v1/memories");
        var traversal = await client.FetchAudioAsync("/v1/voice/sessions/sess-0001/audio/../../../memories");
        var otherSession = await client.FetchAudioAsync("/v1/voice/sessions/sess-9999/audio/a1");
        var escape = await client.FetchAudioAsync("http://evil.example/v1/voice/sessions/x");

        Assert.Equal(new byte[] { 9, 8, 7 }, wav);
        Assert.Null(other);
        Assert.Null(traversal);
        Assert.Null(otherSession);
        Assert.Null(escape);
    }

    [Fact]
    public async Task A_dropped_socket_raises_disconnected_once()
    {
        await using var client = new VoiceSessionClient(_http, _tokens, _baseUrl);
        var reasons = new List<string>();
        client.Disconnected += reasons.Add;
        await client.ConnectAsync();
        await _connected.Task.WaitAsync(TimeSpan.FromSeconds(5));

        _serverSocket!.Abort();

        await Eventually(() =>
        {
            lock (reasons)
            {
                return reasons.Count > 0 ? reasons.ToArray() : null;
            }
        });
        await Task.Delay(50);
        Assert.Single(reasons);
        Assert.Equal("The connection to REVA Core was lost.", reasons[0]);
    }

    [Fact]
    public async Task Closing_deletes_the_session_and_does_not_report_a_disconnect()
    {
        var client = new VoiceSessionClient(_http, _tokens, _baseUrl);
        var raised = 0;
        client.Disconnected += _ => Interlocked.Increment(ref raised);
        await client.ConnectAsync();
        await _connected.Task.WaitAsync(TimeSpan.FromSeconds(5));

        await client.CloseAsync();

        Assert.Equal(1, _deleted);
        Assert.Equal(0, raised);
        Assert.False(client.IsConnected);
    }

    public async ValueTask DisposeAsync()
    {
        _stop.Cancel();
        _listener.Close();
        _http.Dispose();
        await Task.CompletedTask;
    }
}
