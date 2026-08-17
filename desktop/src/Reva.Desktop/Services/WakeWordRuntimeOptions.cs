namespace Reva.Desktop.Services;

public sealed record WakeWordRuntimeOptions(
    bool IsEnabled,
    string AccessKey,
    string KeywordDirectory,
    WakeWordConfiguration Configuration,
    WakeWordModelManifest ModelManifest)
{
    public static WakeWordRuntimeOptions FromEnvironment()
    {
        var dataDirectory = RuntimePaths.GetDefaultDataDirectory();
        return Load(
            new JsonWakeWordSettingsStore(dataDirectory),
            new DpapiWakeWordSecretStore(dataDirectory),
            Environment.GetEnvironmentVariable,
            dataDirectory);
    }

    public static WakeWordRuntimeOptions Load(
        IWakeWordSettingsStore settingsStore,
        IWakeWordSecretStore secretStore,
        Func<string, string?> environment,
        string dataDirectory)
    {
        var settings = settingsStore.Load();
        var enabled = environment("REVA_WAKE_WORD_ENABLED") is { } enabledOverride
            ? IsTruthy(enabledOverride)
            : settings.IsEnabled;
        var accessKey = environment("REVA_PICOVOICE_ACCESS_KEY");
        if (string.IsNullOrWhiteSpace(accessKey))
        {
            accessKey = secretStore.GetAccessKey() ?? string.Empty;
        }

        var modelHashes = settings.ModelHashes
            .Select(pair => (Phrase: PhraseFromSlug(pair.Key), Hash: pair.Value))
            .Where(pair => pair.Phrase is not null && !string.IsNullOrWhiteSpace(pair.Hash))
            .ToDictionary(pair => pair.Phrase!.Value, pair => pair.Hash, EqualityComparer<WakePhrase>.Default);
        if (environment("REVA_WAKE_WORD_HEY_REVA_SHA256") is { } heyRevaHash
            && !string.IsNullOrWhiteSpace(heyRevaHash))
        {
            modelHashes[WakePhrase.HeyReva] = heyRevaHash;
        }

        var keywordSetVersion = environment("REVA_WAKE_WORD_KEYWORD_SET_VERSION");
        if (string.IsNullOrWhiteSpace(keywordSetVersion))
        {
            keywordSetVersion = settings.KeywordSetVersion;
        }

        var architecture = environment("REVA_WAKE_WORD_NATIVE_ARCHITECTURE");
        if (string.IsNullOrWhiteSpace(architecture))
        {
            architecture = System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture.ToString();
        }

        return new WakeWordRuntimeOptions(
            enabled,
            accessKey,
            Path.Combine(dataDirectory, "wake-word", "keywords"),
            new WakeWordConfiguration(WakePhraseDefaults.All),
            new WakeWordModelManifest(keywordSetVersion ?? string.Empty, architecture, modelHashes));
    }

    private static bool IsTruthy(string? value) =>
        string.Equals(value, "1", StringComparison.OrdinalIgnoreCase)
        || string.Equals(value, "true", StringComparison.OrdinalIgnoreCase)
        || string.Equals(value, "yes", StringComparison.OrdinalIgnoreCase);

    private static WakePhrase? PhraseFromSlug(string slug)
    {
        foreach (WakePhrase phrase in Enum.GetValues<WakePhrase>())
        {
            if (string.Equals(WakePhraseDefaults.KeywordSlug(phrase), slug, StringComparison.OrdinalIgnoreCase))
            {
                return phrase;
            }
        }

        return null;
    }
}
