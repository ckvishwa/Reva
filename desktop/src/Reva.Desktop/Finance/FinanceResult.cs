namespace Reva.Desktop.Finance;

public enum FinanceErrorKind
{
    /// <summary>Core could not be reached, or Finance is not available (kernel not built).</summary>
    Unavailable,
    Unauthorized,
    Timeout,
    ServerFailure,
    InvalidResponse,
    /// <summary>The Finance data file is locked (no key) or the key does not open it.</summary>
    Locked,
    /// <summary>The input was rejected; <see cref="FinanceError.Field"/> says which field.</summary>
    Validation,
    /// <summary>The change conflicts with existing data (duplicate, archived account, in use...).</summary>
    Conflict,
    NotFound,
    Deleted,
}

/// <summary>A safe, display-ready failure. <see cref="SafeMessage"/> never carries a stack trace,
/// path, token or key; <see cref="Detail"/> is Core's short validation or conflict text.</summary>
public sealed record FinanceError(FinanceErrorKind Kind, string SafeMessage, string? Field = null, string? Detail = null);

public sealed class FinanceResult<T>
{
    private FinanceResult(T? value, FinanceError? error)
    {
        Value = value;
        Error = error;
    }

    public bool IsSuccess => Error is null;

    public T? Value { get; }

    public FinanceError? Error { get; }

    public static FinanceResult<T> Success(T value) => new(value, null);

    public static FinanceResult<T> Failure(FinanceError error) => new(default, error);

    public static FinanceResult<T> Failure(FinanceErrorKind kind, string safeMessage) =>
        new(default, new FinanceError(kind, safeMessage));
}
