namespace Reva.Desktop.Devices;

public enum DevicesErrorKind
{
    /// <summary>Core could not be reached.</summary>
    Unavailable,
    Unauthorized,
    Timeout,
    ServerFailure,
    InvalidResponse,
    /// <summary>The gateway is off, or could not start (<see cref="DevicesError.Detail"/> says why).</summary>
    GatewayOff,
    /// <summary>The request does not fit the current pairing (nothing to approve, digits do not match...).</summary>
    State,
    NotFound,
    Validation,
}

/// <summary>A display-ready failure. <see cref="SafeMessage"/> never carries a token, key, code or path.</summary>
public sealed record DevicesError(DevicesErrorKind Kind, string SafeMessage, string? Code = null, string? Detail = null);

public sealed class DevicesResult<T>
{
    private DevicesResult(T? value, DevicesError? error)
    {
        Value = value;
        Error = error;
    }

    public bool IsSuccess => Error is null;

    public T? Value { get; }

    public DevicesError? Error { get; }

    public static DevicesResult<T> Success(T value) => new(value, null);

    public static DevicesResult<T> Failure(DevicesError error) => new(default, error);
}
