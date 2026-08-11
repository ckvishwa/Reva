namespace Reva.Desktop.Services;

/// <summary>How to launch REVA Core, or why that isn't currently possible.</summary>
public sealed record CoreExecutableResolution(
    bool IsAvailable, string? FileName, string? Arguments, string? WorkingDirectory, string? FailureReason)
{
    public static CoreExecutableResolution Available(string fileName, string arguments, string workingDirectory) =>
        new(true, fileName, arguments, workingDirectory, null);

    public static CoreExecutableResolution Unavailable(string reason) =>
        new(false, null, null, null, reason);
}
