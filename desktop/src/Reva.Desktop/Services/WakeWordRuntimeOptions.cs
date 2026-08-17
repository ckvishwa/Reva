namespace Reva.Desktop.Services;

public sealed record WakeWordRuntimeOptions(
    bool IsEnabled,
    string AccessKey,
    string KeywordDirectory,
    WakeWordConfiguration Configuration)
{
    public static WakeWordRuntimeOptions FromEnvironment()
    {
        var enabled = IsTruthy(Environment.GetEnvironmentVariable("REVA_WAKE_WORD_ENABLED"));
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var keywordDirectory = Path.Combine(localAppData, "REVA", "wake-word", "keywords");

        return new WakeWordRuntimeOptions(
            enabled,
            Environment.GetEnvironmentVariable("REVA_PICOVOICE_ACCESS_KEY") ?? string.Empty,
            keywordDirectory,
            new WakeWordConfiguration(WakePhraseDefaults.All));
    }

    private static bool IsTruthy(string? value) =>
        string.Equals(value, "1", StringComparison.OrdinalIgnoreCase)
        || string.Equals(value, "true", StringComparison.OrdinalIgnoreCase)
        || string.Equals(value, "yes", StringComparison.OrdinalIgnoreCase);
}
