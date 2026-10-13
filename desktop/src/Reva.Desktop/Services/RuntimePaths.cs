namespace Reva.Desktop.Services;

/// <summary>
/// Deterministic Windows per-user REVA runtime/data location, shared by
/// Desktop and the Python Core it launches. Deliberately reads no
/// environment variables here — <see cref="DesktopConfiguration"/> owns
/// the single REVA_DATA_DIR override read, so tests that manipulate that
/// env var keep working exactly as before.
/// </summary>
public static class RuntimePaths
{
    public static string GetDefaultDataDirectory() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Reva");

    public static string GetDefaultLogDirectory() =>
        Path.Combine(GetDefaultDataDirectory(), "logs");
}
