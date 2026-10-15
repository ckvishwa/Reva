using FlaUI.Core.Tools;

namespace Reva.Desktop.UiTests;

/// <summary>
/// The avatar in the real window: the locked-down WebView2 loads the local page and the page reports ready.
/// Needs avatar/dist (npm run build in avatar/); without it the app shows "Avatar files are missing" and
/// this test says so instead of failing.
/// </summary>
[Collection("ui")]
public class AvatarSmokeTests : IClassFixture<FinanceFixture>
{
    private readonly FinanceFixture _fixture;

    public AvatarSmokeTests(FinanceFixture fixture) => _fixture = fixture;

    private AppHarness App => _fixture.Harness;

    [UiFact]
    public void The_avatar_page_loads_in_the_web_view_and_reports_ready()
    {
        var status = Retry.WhileFalse(
            () =>
            {
                var element = App.Find("AvatarStatus", TimeSpan.FromSeconds(1));
                var text = element?.Properties.Name.ValueOrDefault ?? string.Empty;
                return text == "Avatar ready" || text.StartsWith("Avatar files are missing", StringComparison.Ordinal);
            },
            TimeSpan.FromSeconds(60),
            TimeSpan.FromMilliseconds(500));
        Assert.True(status.Success, "The avatar never reported a status. Last seen: " + (App.Find("AvatarStatus", TimeSpan.FromSeconds(1))?.Properties.Name.ValueOrDefault ?? "(element not found)"));
        var name = App.Find("AvatarStatus", TimeSpan.FromSeconds(1))?.Properties.Name.ValueOrDefault ?? string.Empty;
        Assert.True(name == "Avatar ready" || AvatarBuilt() == false, $"Avatar status was: {name}");
        Assert.NotNull(App.Find("AvatarWebView"));
    }

    private static bool AvatarBuilt() =>
        File.Exists(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "..", "avatar", "dist", "index.html"));
}
