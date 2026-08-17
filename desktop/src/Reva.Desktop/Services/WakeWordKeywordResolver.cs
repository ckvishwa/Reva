namespace Reva.Desktop.Services;

public sealed record KeywordResolution(
    bool IsSuccess,
    IReadOnlyList<string>? KeywordPaths,
    IReadOnlyList<float>? Sensitivities,
    IReadOnlyList<WakePhrase>? PhraseOrder,
    WakePhrase? MissingPhrase);

public interface IFileSystemProbe
{
    bool FileExists(string path);
}

public sealed class RealFileSystemProbe : IFileSystemProbe
{
    public bool FileExists(string path) => File.Exists(path);
}

public static class WakeWordKeywordResolver
{
    public static KeywordResolution Resolve(
        IEnumerable<WakePhraseSetting> phrases,
        string keywordDirectory,
        IFileSystemProbe fileSystem)
    {
        var keywordPaths = new List<string>();
        var sensitivities = new List<float>();
        var phraseOrder = new List<WakePhrase>();

        foreach (var phrase in phrases.Where(phrase => phrase.Enabled))
        {
            var path = Path.Combine(keywordDirectory, $"{WakePhraseDefaults.KeywordSlug(phrase.Phrase)}.ppn");
            if (!fileSystem.FileExists(path))
            {
                return new KeywordResolution(false, null, null, null, phrase.Phrase);
            }

            keywordPaths.Add(path);
            sensitivities.Add(phrase.Sensitivity);
            phraseOrder.Add(phrase.Phrase);
        }

        return keywordPaths.Count == 0
            ? new KeywordResolution(false, null, null, null, null)
            : new KeywordResolution(true, keywordPaths, sensitivities, phraseOrder, null);
    }
}
