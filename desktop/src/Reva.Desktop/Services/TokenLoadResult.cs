namespace Reva.Desktop.Services;

/// <summary>
/// Result of attempting to load the local Core auth token. Deliberately
/// does not expose the token via <see cref="ToString"/> — logging or
/// interpolating this object can never leak the value.
/// </summary>
public sealed class TokenLoadResult
{
    private readonly string? _token;

    private TokenLoadResult(bool isAvailable, string? token)
    {
        IsAvailable = isAvailable;
        _token = token;
    }

    public bool IsAvailable { get; }

    public string Token => IsAvailable
        ? _token!
        : throw new InvalidOperationException("Token is not available; check IsAvailable first.");

    public static TokenLoadResult Available(string token) => new(true, token);

    public static TokenLoadResult Unavailable() => new(false, null);

    public override string ToString() => IsAvailable ? "TokenLoadResult(Available)" : "TokenLoadResult(Unavailable)";
}
