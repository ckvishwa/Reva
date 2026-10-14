namespace Reva.Desktop.Tests.Unit;

/// <summary>Test double standing in for the real transport — lets client
/// error-normalization be tested without a real network call.</summary>
internal sealed class FakeHttpMessageHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> _responder;

    public HttpRequestMessage? LastRequest { get; private set; }

    /// <summary>Request body captured while the request is still alive —
    /// the real client disposes its HttpRequestMessage (and Content) right
    /// after SendAsync returns, so reading LastRequest.Content afterward
    /// throws ObjectDisposedException.</summary>
    public string? LastRequestBody { get; private set; }

    public FakeHttpMessageHandler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> responder)
    {
        _responder = responder;
    }

    public static FakeHttpMessageHandler ReturningStatus(System.Net.HttpStatusCode statusCode, string? jsonBody = null) =>
        new((_, _) => Task.FromResult(new HttpResponseMessage(statusCode)
        {
            Content = jsonBody is null ? null : new StringContent(jsonBody, System.Text.Encoding.UTF8, "application/json"),
        }));

    public static FakeHttpMessageHandler ThrowingConnectionRefused() =>
        new((_, _) => throw new HttpRequestException("Connection refused"));

    public static FakeHttpMessageHandler ThrowingTimeout() =>
        new((_, ct) => throw new TaskCanceledException("The request timed out", new TimeoutException()));

    /// <summary>Simulates a slow server response. Must honor the
    /// cancellation token via Task.Delay(delay, cancellationToken) — an
    /// unhonored token would make timeout tests hang instead of failing
    /// fast when the per-call CTS fires.</summary>
    public static FakeHttpMessageHandler Delayed(TimeSpan delay, System.Net.HttpStatusCode status, string json) =>
        new(async (_, cancellationToken) =>
        {
            await Task.Delay(delay, cancellationToken).ConfigureAwait(false);
            return new HttpResponseMessage(status)
            {
                Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json"),
            };
        });

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        LastRequest = request;
        if (request.Content is not null)
        {
            LastRequestBody = await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        }

        return await _responder(request, cancellationToken).ConfigureAwait(false);
    }
}
