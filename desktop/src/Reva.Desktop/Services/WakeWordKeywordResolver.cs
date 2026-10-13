namespace Reva.Desktop.Services;

public sealed record KeywordResolution(
    bool IsSuccess,
    IReadOnlyList<string>? KeywordPaths,
    IReadOnlyList<float>? Sensitivities,
    IReadOnlyList<WakePhrase>? PhraseOrder,
    WakePhrase? MissingPhrase,
    KeywordResolutionFailure? Failure = null);

public enum KeywordResolutionFailure
{
    MissingFile,
    MissingExpectedHash,
    HashMismatch,
    UnsupportedArchitecture,
    NoEnabledPhrases,
}

public interface IFileSystemProbe
{
    bool FileExists(string path);

    string ComputeSha256(string path);
}

public sealed class RealFileSystemProbe : IFileSystemProbe
{
    public bool FileExists(string path) => File.Exists(path);

    public string ComputeSha256(string path)
    {
        using var stream = File.OpenRead(path);
        var bytes = System.Security.Cryptography.SHA256.HashData(stream);
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

public static class WakeWordKeywordResolver
{
    public static KeywordResolution Resolve(
        IEnumerable<WakePhraseSetting> phrases,
        string keywordDirectory,
        IFileSystemProbe fileSystem) =>
        Resolve(phrases, keywordDirectory, fileSystem, WakeWordModelManifest.Empty);

    public static KeywordResolution Resolve(
        IEnumerable<WakePhraseSetting> phrases,
        string keywordDirectory,
        IFileSystemProbe fileSystem,
        WakeWordModelManifest manifest,
        string? currentArchitecture = null)
    {
        var keywordPaths = new List<string>();
        var sensitivities = new List<float>();
        var phraseOrder = new List<WakePhrase>();
        var architecture = currentArchitecture
            ?? System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture.ToString();
        if (!string.IsNullOrWhiteSpace(manifest.Architecture)
            && !string.Equals(manifest.Architecture, architecture, StringComparison.OrdinalIgnoreCase))
        {
            return new KeywordResolution(false, null, null, null, null, KeywordResolutionFailure.UnsupportedArchitecture);
        }

        foreach (var phrase in phrases.Where(phrase => phrase.Enabled))
        {
            var path = Path.Combine(keywordDirectory, $"{WakePhraseDefaults.KeywordSlug(phrase.Phrase)}.ppn");
            if (!fileSystem.FileExists(path))
            {
                return new KeywordResolution(false, null, null, null, phrase.Phrase, KeywordResolutionFailure.MissingFile);
            }

            if (!manifest.ExpectedSha256.TryGetValue(phrase.Phrase, out var expectedHash)
                || string.IsNullOrWhiteSpace(expectedHash))
            {
                return new KeywordResolution(false, null, null, null, phrase.Phrase, KeywordResolutionFailure.MissingExpectedHash);
            }

            var actualHash = fileSystem.ComputeSha256(path);
            if (!string.Equals(actualHash, expectedHash, StringComparison.OrdinalIgnoreCase))
            {
                return new KeywordResolution(false, null, null, null, phrase.Phrase, KeywordResolutionFailure.HashMismatch);
            }

            keywordPaths.Add(path);
            sensitivities.Add(phrase.Sensitivity);
            phraseOrder.Add(phrase.Phrase);
        }

        return keywordPaths.Count == 0
            ? new KeywordResolution(false, null, null, null, null, KeywordResolutionFailure.NoEnabledPhrases)
            : new KeywordResolution(true, keywordPaths, sensitivities, phraseOrder, null);
    }
}
