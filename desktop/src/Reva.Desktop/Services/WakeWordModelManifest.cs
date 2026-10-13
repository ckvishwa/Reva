namespace Reva.Desktop.Services;

public sealed record WakeWordModelManifest(
    string KeywordSetVersion,
    string Architecture,
    IReadOnlyDictionary<WakePhrase, string> ExpectedSha256)
{
    public static WakeWordModelManifest Empty { get; } =
        new(string.Empty, string.Empty, new Dictionary<WakePhrase, string>());
}
