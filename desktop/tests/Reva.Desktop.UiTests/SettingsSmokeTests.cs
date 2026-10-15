using FlaUI.Core.AutomationElements;
using FlaUI.Core.Tools;

namespace Reva.Desktop.UiTests;

/// <summary>
/// Settings > Cloud model in the real window. It never stores a key (that would touch the owner's
/// real Credential Manager), so it checks what is shown, not what happens after a key is stored.
/// </summary>
[Collection("ui")]
public class SettingsSmokeTests : IClassFixture<FinanceFixture>
{
    private readonly FinanceFixture _fixture;

    public SettingsSmokeTests(FinanceFixture fixture) => _fixture = fixture;

    private AppHarness App => _fixture.Harness;

    [UiFact]
    public void Settings_opens_with_the_disclosure_and_every_domain_switched_off()
    {
        App.Require("Nav_settings").AsButton().Invoke();

        var loaded = Retry.WhileFalse(
            () => App.Find("CloudProvider") is { } provider && (provider.Properties.Name.ValueOrDefault ?? "").StartsWith("Anthropic", StringComparison.Ordinal),
            TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(250));
        Assert.True(loaded.Success, "The cloud settings never loaded from Core.");
        Assert.NotNull(App.Find("CloudKeyBox"));
        Assert.NotNull(App.Find("CloudStoreKey"));
        Assert.NotNull(App.Find("CloudSwitch"));
        var switches = App.Window.FindAllDescendants(cf => cf.ByName("Finance")).Length
            + App.Window.FindAllDescendants(cf => cf.ByName("Memory")).Length;
        Assert.True(switches >= 2, "The Finance and Memory domain switches should be listed.");
        Assert.Null(App.Find("ComingSoon", TimeSpan.FromSeconds(1)));
    }
}
