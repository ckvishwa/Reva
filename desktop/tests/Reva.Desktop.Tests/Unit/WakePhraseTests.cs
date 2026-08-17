using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WakePhraseTests
{
    [Fact]
    public void Defaults_OnlyHeyRevaIsEnabled()
    {
        var enabled = WakePhraseDefaults.All.Where(phrase => phrase.Enabled).Select(phrase => phrase.Phrase);

        Assert.Equal(new[] { WakePhrase.HeyReva }, enabled);
    }

    [Theory]
    [InlineData(WakePhrase.HeyReva, "Hey Reva", "hey-reva")]
    [InlineData(WakePhrase.YouUpReva, "You up Reva", "you-up-reva")]
    [InlineData(WakePhrase.DaddysHome, "Daddy's home", "daddys-home")]
    [InlineData(WakePhrase.RevaWakeUp, "Reva wake up", "reva-wake-up")]
    public void Defaults_ExposeDisplayAndKeywordSlugs(
        WakePhrase phrase,
        string displayName,
        string keywordSlug)
    {
        Assert.Equal(displayName, WakePhraseDefaults.DisplayName(phrase));
        Assert.Equal(keywordSlug, WakePhraseDefaults.KeywordSlug(phrase));
    }
}
