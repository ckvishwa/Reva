using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Reva.Desktop.UiTests;

/// <summary>
/// A phone written independently of the Python one: its own P-256 key, TLS pinned to the key hash in the QR,
/// and the wire format of ARD-500 / reva_core/gateway/protocol.py re-implemented in C#. If the two ever
/// disagree about a signed string or the fingerprint, the smoke test fails. It talks to a real gateway on
/// loopback in a throw-away data directory; nothing here is a real device.
/// </summary>
internal sealed class GatewayPhone : IDisposable
{
    private readonly ECDsa _key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
    private HttpClient? _http;
    private string _gatewayHash = string.Empty;
    private Uri _base = null!;
    private DateTime _lastResponseAt = DateTime.MinValue;

    public GatewayPhone(string kernelDeviceId = "ui-smoke-phone-0001", string name = "Smoke phone")
    {
        KernelDeviceId = kernelDeviceId;
        Name = name;
    }

    public string KernelDeviceId { get; }

    public string Name { get; }

    public string? DeviceId { get; private set; }

    public string? SessionId { get; private set; }

    private byte[] PublicKey => _key.ExportSubjectPublicKeyInfo();

    public static string B64u(byte[] data) => Convert.ToBase64String(data).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    public static byte[] B64uDecode(string text)
    {
        var s = text.Replace('-', '+').Replace('_', '/');
        return Convert.FromBase64String(s + new string('=', (4 - s.Length % 4) % 4));
    }

    private static string Sha256Hex(byte[] data) => Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();

    private string Sign(string message) =>
        B64u(_key.SignData(Encoding.UTF8.GetBytes(message), HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence));

    /// <summary>The six digits both screens show; must equal the PC's.</summary>
    public string ExpectedFingerprint()
    {
        var input = Encoding.UTF8.GetBytes("REVA-GW1\nsas\n")
            .Concat(Convert.FromHexString(_gatewayHash))
            .Concat(Encoding.UTF8.GetBytes("\n"))
            .Concat(PublicKey)
            .Concat(Encoding.UTF8.GetBytes("\n" + SessionId))
            .ToArray();
        var digest = SHA256.HashData(input);
        var value = System.Buffers.Binary.BinaryPrimitives.ReadUInt64BigEndian(digest.AsSpan(0, 8));
        return (value % 1_000_000).ToString("D6");
    }

    /// <summary>Scan the QR text and start pairing. Returns the HTTP status.</summary>
    public async Task<int> StartPairingAsync(string qrText)
    {
        const string prefix = "REVA-PAIR1:";
        Assert.StartsWith(prefix, qrText);
        var payload = JsonNode.Parse(B64uDecode(qrText[prefix.Length..]))!.AsObject();
        _gatewayHash = payload["gw"]!.GetValue<string>();
        _base = new Uri($"https://{payload["host"]!.GetValue<string>()}:{payload["port"]!.GetValue<int>()}/");
        var code = payload["code"]!.GetValue<string>();

        var handler = new HttpClientHandler
        {
            // Pinning replaces CA validation: the key must be the one named in the QR code.
            ServerCertificateCustomValidationCallback = (_, cert, _, _) =>
                cert is not null && Sha256Hex(cert.PublicKey.ExportSubjectPublicKeyInfo()) == _gatewayHash,
        };
        _http = new HttpClient(handler) { BaseAddress = _base, Timeout = TimeSpan.FromSeconds(20) };

        var body = new JsonObject
        {
            ["code"] = code,
            ["name"] = Name,
            ["platform"] = "android",
            ["public_key"] = B64u(PublicKey),
            ["kernel_devices"] = new JsonObject { ["finance"] = KernelDeviceId },
            ["proof"] = Sign($"REVA-GW1\npair-start\n{code}\n{_gatewayHash}"),
        };
        using var response = await SendAsync(new HttpRequestMessage(HttpMethod.Post, "pair/start") { Content = Json(body) });
        if (response.IsSuccessStatusCode)
        {
            SessionId = JsonNode.Parse(await response.Content.ReadAsStringAsync())!["session_id"]!.GetValue<string>();
        }

        return (int)response.StatusCode;
    }

    /// <summary>Poll for the approval result; on approval remember our device id.</summary>
    public async Task<int> PollAsync()
    {
        var nonce = B64u(RandomNumberGenerator.GetBytes(16));
        var body = new JsonObject
        {
            ["session_id"] = SessionId,
            ["nonce"] = nonce,
            ["proof"] = Sign($"REVA-GW1\npair-complete\n{SessionId}\n{nonce}\n{_gatewayHash}"),
        };
        using var response = await SendAsync(new HttpRequestMessage(HttpMethod.Post, "pair/complete") { Content = Json(body) });
        if (response.StatusCode == System.Net.HttpStatusCode.OK)
        {
            DeviceId = JsonNode.Parse(await response.Content.ReadAsStringAsync())!["device_id"]!.GetValue<string>();
        }

        return (int)response.StatusCode;
    }

    /// <summary>A signed sync pull, exactly as the real phone sends it. Returns the HTTP status.</summary>
    public async Task<int> PullAsync()
    {
        const string path = "/sync/pull";
        var body = Encoding.UTF8.GetBytes("{\"domain\":\"finance\",\"limit\":5}");
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var nonce = B64u(RandomNumberGenerator.GetBytes(16));
        var message = $"REVA-GW1\nrequest\nPOST\n{path}\n{timestamp}\n{nonce}\n{Sha256Hex(body)}\n{_gatewayHash}";
        using var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new ByteArrayContent(body) };
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        request.Headers.Add("X-Reva-Device", DeviceId);
        request.Headers.Add("X-Reva-Ts", timestamp.ToString());
        request.Headers.Add("X-Reva-Nonce", nonce);
        request.Headers.Add("X-Reva-Sig", Sign(message));
        using var response = await SendAsync(request);
        return (int)response.StatusCode;
    }

    /// <summary>
    /// Sends on the pooled connection and, when that fails, says how long the connection had been idle. A server that
    /// closes idle connections early shows up as a failure right after a gap of about its keep-alive timeout.
    /// </summary>
    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request)
    {
        var idle = _lastResponseAt == DateTime.MinValue ? TimeSpan.Zero : DateTime.UtcNow - _lastResponseAt;
        try
        {
            var response = await _http!.SendAsync(request);
            _lastResponseAt = DateTime.UtcNow;
            return response;
        }
        catch (HttpRequestException ex)
        {
            throw new HttpRequestException(
                $"{request.Method} {request.RequestUri} failed {(int)idle.TotalMilliseconds} ms after this phone's previous response at {DateTime.UtcNow:HH:mm:ss.fff}Z: {ex.Message}", ex);
        }
    }

    private static StringContent Json(JsonObject body) => new(body.ToJsonString(), Encoding.UTF8, "application/json");

    public void Dispose()
    {
        _http?.Dispose();
        _key.Dispose();
    }
}

/// <summary>The loopback Core API as the test itself needs it (the app's own client is not reused on purpose).</summary>
internal sealed class CoreProbe : IDisposable
{
    private readonly HttpClient _http;

    public CoreProbe(string coreUrl, string dataDirectory)
    {
        _http = new HttpClient { BaseAddress = new Uri(coreUrl) };
        var token = File.ReadAllText(Path.Combine(dataDirectory, "local_auth_token")).Trim();
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
    }

    public async Task<string> OpenPairingQrAsync()
    {
        using var response = await _http.PostAsync("v1/devices/pairing", null);
        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement.GetProperty("qr_text").GetString()!;
    }

    public void Dispose() => _http.Dispose();
}
