using System.Runtime.InteropServices;

namespace Reva.Desktop.Services;

public sealed record WakeWordProviderDiagnostics(
    string PorcupineVersion,
    string PvRecorderVersion,
    string NativeArchitecture,
    string KeywordSetVersion,
    string HeyRevaSha256)
{
    public const string PinnedPorcupineVersion = "4.0.2";
    public const string PinnedPvRecorderVersion = "1.2.13";

    public static WakeWordProviderDiagnostics Create(
        WakeWordRuntimeOptions options,
        string? architecture = null)
    {
        options.ModelManifest.ExpectedSha256.TryGetValue(WakePhrase.HeyReva, out var heyRevaSha256);
        return new WakeWordProviderDiagnostics(
            PinnedPorcupineVersion,
            PinnedPvRecorderVersion,
            architecture ?? RuntimeInformation.ProcessArchitecture.ToString(),
            options.ModelManifest.KeywordSetVersion,
            heyRevaSha256 ?? string.Empty);
    }

    public string ToLogString() =>
        "wakeword.provider "
        + $"porcupine={PorcupineVersion} "
        + $"pvrecorder={PvRecorderVersion} "
        + $"arch={NativeArchitecture} "
        + $"keyword_version={KeywordSetVersion} "
        + $"hey_reva_sha256={HeyRevaSha256}";

    public void Log() => DesktopLogger.Info(ToLogString());
}
