namespace Reva.Desktop.Tests.Unit;

/// <summary>Test double standing in for the real transport — lets client
/// error-normalization be tested without a real network call.</summary>
internal sealed class FakeHttpMessageHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> _responder;

    public HttpRequestMessage? LastRequest { get; private set; }

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

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        LastRequest = request;
        return await _responder(request, cancellationToken).ConfigureAwait(false);
    }
}
