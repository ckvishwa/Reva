namespace Reva.Desktop.Services;

public enum WakePhrase
{
    HeyReva,
    YouUpReva,
    DaddysHome,
    RevaWakeUp,
}

public sealed record WakePhraseSetting(WakePhrase Phrase, bool Enabled, float Sensitivity);

public sealed record WakeWordConfiguration(IReadOnlyList<WakePhraseSetting> Phrases);

public static class WakePhraseDefaults
{
    public static readonly IReadOnlyList<WakePhraseSetting> All = new[]
    {
        new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f),
        new WakePhraseSetting(WakePhrase.YouUpReva, Enabled: false, Sensitivity: 0.45f),
        new WakePhraseSetting(WakePhrase.DaddysHome, Enabled: false, Sensitivity: 0.45f),
        new WakePhraseSetting(WakePhrase.RevaWakeUp, Enabled: false, Sensitivity: 0.40f),
    };

    public static string DisplayName(WakePhrase phrase) => phrase switch
    {
        WakePhrase.HeyReva => "Hey Reva",
        WakePhrase.YouUpReva => "You up Reva",
        WakePhrase.DaddysHome => "Daddy's home",
        WakePhrase.RevaWakeUp => "Reva wake up",
        _ => throw new ArgumentOutOfRangeException(nameof(phrase)),
    };
}
