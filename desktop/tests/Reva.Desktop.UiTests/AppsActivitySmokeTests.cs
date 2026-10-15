using FlaUI.Core.AutomationElements;
using FlaUI.Core.Tools;

namespace Reva.Desktop.UiTests;

/// <summary>Apps &amp; Actions and Activity in the real window. They only look: nothing is approved, so
/// the owner's real app list and Start Menu are not changed.</summary>
[Collection("ui")]
public class AppsActivitySmokeTests : IClassFixture<FinanceFixture>
{
    private readonly FinanceFixture _fixture;

    public AppsActivitySmokeTests(FinanceFixture fixture) => _fixture = fixture;

    private AppHarness App => _fixture.Harness;

    [UiFact]
    public void Apps_and_actions_lists_the_built_in_apps_and_is_not_a_coming_soon_page()
    {
        App.Require("Nav_apps").AsButton().Invoke();

        var loaded = Retry.WhileFalse(
            () => App.Find("AppsTitle") is not null,
            TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(250));
        Assert.True(loaded.Success, "The Apps & Actions page never opened.");
        var notepad = Retry.WhileFalse(
            () => App.Window.FindAllDescendants(cf => cf.ByName("Notepad")).Length > 0,
            TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(250));
        Assert.True(notepad.Success, "Notepad (a built-in app) should be listed.");
        Assert.Null(App.Find("ComingSoon", TimeSpan.FromSeconds(1)));
    }

    [UiFact]
    public void Activity_opens_with_a_refresh_button_and_no_coming_soon_page()
    {
        App.Require("Nav_activity").AsButton().Invoke();

        var loaded = Retry.WhileFalse(
            () => App.Find("ActivityRefresh") is not null,
            TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(250));
        Assert.True(loaded.Success, "The Activity page never opened.");
        Assert.Null(App.Find("ComingSoon", TimeSpan.FromSeconds(1)));
    }
}
