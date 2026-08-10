namespace Reva.Desktop.Services;

/// <summary>Every Core failure normalizes to exactly one of these kinds —
/// nothing else ever reaches the UI layer.</summary>
public enum CoreErrorKind
{
    CoreUnavailable,
    CoreUnauthorized,
    CoreTimeout,
    CoreInvalidResponse,
    CoreServerFailure,
}

/// <summary>A safe, display-ready error. <see cref="SafeMessage"/> is a
/// fixed string per <see cref="CoreErrorKind"/> — never interpolated
/// exception text, never a file path, never a token.</summary>
public sealed record CoreError(CoreErrorKind Kind, string SafeMessage);

/// <summary>Result of a REVA Core call: either a parsed value or a safe
/// <see cref="CoreError"/>. Never both, never neither.</summary>
public sealed class CoreResult<T>
{
    private CoreResult(T? value, CoreError? error)
    {
        Value = value;
        Error = error;
    }

    public bool IsSuccess => Error is null;

    public T? Value { get; }

    public CoreError? Error { get; }

    public static CoreResult<T> Success(T value) => new(value, null);

    public static CoreResult<T> Failure(CoreErrorKind kind, string safeMessage) =>
        new(default, new CoreError(kind, safeMessage));

    public static CoreResult<T> Failure(CoreError error) => new(default, error);
}
