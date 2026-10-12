using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WakeWordKeywordResolverTests
{
    [Fact]
    public void Resolve_EnabledPhrases_ReturnsPathsSensitivitiesAndOrder()
    {
        var phrases = new[]
        {
            new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f),
            new WakePhraseSetting(WakePhrase.YouUpReva, Enabled: true, Sensitivity: 0.45f),
            new WakePhraseSetting(WakePhrase.DaddysHome, Enabled: false, Sensitivity: 0.45f),
        };
        var probe = new FakeFileSystemProbe(
            @"C:\kw\hey-reva.ppn",
            @"C:\kw\you-up-reva.ppn");

        var result = WakeWordKeywordResolver.Resolve(
            phrases,
            @"C:\kw",
            probe,
            VerifiedManifest(WakePhrase.HeyReva, WakePhrase.YouUpReva));

        Assert.True(result.IsSuccess);
        Assert.Equal(new[] { @"C:\kw\hey-reva.ppn", @"C:\kw\you-up-reva.ppn" }, result.KeywordPaths);
        Assert.Equal(new[] { 0.55f, 0.45f }, result.Sensitivities);
        Assert.Equal(new[] { WakePhrase.HeyReva, WakePhrase.YouUpReva }, result.PhraseOrder);
    }

    [Fact]
    public void Resolve_MissingEnabledPhrase_FailsAndArmsNothing()
    {
        var phrases = new[]
        {
            new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f),
            new WakePhraseSetting(WakePhrase.YouUpReva, Enabled: true, Sensitivity: 0.45f),
        };
        var probe = new FakeFileSystemProbe(@"C:\kw\hey-reva.ppn");

        var result = WakeWordKeywordResolver.Resolve(
            phrases,
            @"C:\kw",
            probe,
            VerifiedManifest(WakePhrase.HeyReva));

        Assert.False(result.IsSuccess);
        Assert.Equal(WakePhrase.YouUpReva, result.MissingPhrase);
        Assert.Null(result.KeywordPaths);
        Assert.Null(result.Sensitivities);
        Assert.Null(result.PhraseOrder);
    }

    [Fact]
    public void Resolve_EmptyManifest_RejectsPresentKeywordFile()
    {
        var phrases = new[]
        {
            new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f),
        };

        var result = WakeWordKeywordResolver.Resolve(
            phrases,
            @"C:\kw",
            new FakeFileSystemProbe(@"C:\kw\hey-reva.ppn"),
            WakeWordModelManifest.Empty);

        Assert.False(result.IsSuccess);
        Assert.Equal(KeywordResolutionFailure.MissingExpectedHash, result.Failure);
        Assert.Equal(WakePhrase.HeyReva, result.MissingPhrase);
        Assert.Null(result.KeywordPaths);
    }

    [Fact]
    public void Resolve_NoEnabledPhrases_FailsWithoutMissingPhrase()
    {
        var result = WakeWordKeywordResolver.Resolve(
            new[] { new WakePhraseSetting(WakePhrase.HeyReva, Enabled: false, Sensitivity: 0.55f) },
            @"C:\kw",
            new FakeFileSystemProbe());

        Assert.False(result.IsSuccess);
        Assert.Null(result.MissingPhrase);
    }

    private static WakeWordModelManifest VerifiedManifest(params WakePhrase[] phrases) =>
        new(
            string.Empty,
            string.Empty,
            phrases.ToDictionary(phrase => phrase, _ => new string('0', 64)));

    private sealed class FakeFileSystemProbe : IFileSystemProbe
    {
        private readonly HashSet<string> _paths;

        public FakeFileSystemProbe(params string[] paths) =>
            _paths = new HashSet<string>(paths, StringComparer.OrdinalIgnoreCase);

        public bool FileExists(string path) => _paths.Contains(path);

        public string ComputeSha256(string path) => new('0', 64);
    }
}
