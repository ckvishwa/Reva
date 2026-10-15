using FlaUI.Core.AutomationElements;
using FlaUI.Core.Tools;

namespace Reva.Desktop.UiTests;

/// <summary>
/// Live voice panel in the real window against the real Core. No microphone is touched: the
/// session is opened and closed, and the mute toggles are flipped. Talking itself is hardware.
/// </summary>
[Collection("ui")]
public class LiveVoiceSmokeTests : IClassFixture<FinanceFixture>
{
    private readonly FinanceFixture _fixture;

    public LiveVoiceSmokeTests(FinanceFixture fixture) => _fixture = fixture;

    private AppHarness App => _fixture.Harness;

    private string StateText() => App.Require("LiveVoiceStateText").Name;

    [UiFact]
    public void The_panel_has_named_controls_and_starts_off_with_the_mic_dot_closed()
    {
        Assert.NotNull(App.Find("LiveVoiceToggle"));
        Assert.NotNull(App.Find("LiveVoiceTalkButton"));
        Assert.NotNull(App.Find("LiveVoiceMicMute"));
        Assert.NotNull(App.Find("LiveVoiceSpeakerMute"));
        Assert.NotNull(App.Find("LiveVoiceMicrophone"));
        Assert.NotNull(App.Find("LiveVoiceMicOpenDot"));
        Assert.Equal("Voice is off.", StateText());
        Assert.False(App.Require("LiveVoiceTalkButton").IsEnabled);
    }

    [UiFact]
    public void Turning_voice_on_opens_a_core_session_without_opening_the_microphone_then_off_closes_it()
    {
        var toggle = App.Require("LiveVoiceToggle").AsToggleButton();

        toggle.Toggle();
        var ready = Retry.WhileFalse(
            () => StateText().StartsWith("Hold Ctrl+Space", StringComparison.Ordinal),
            TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(200));
        Assert.True(ready.Success, "Voice never became ready; state: " + StateText());
        Assert.True(App.Require("LiveVoiceTalkButton").IsEnabled);

        toggle.Toggle();
        var off = Retry.WhileFalse(
            () => StateText() == "Voice is off.",
            TimeSpan.FromSeconds(10),
            TimeSpan.FromMilliseconds(200));
        Assert.True(off.Success, "Voice never turned off; state: " + StateText());
    }

    [UiFact]
    public void The_mute_toggles_work_and_can_be_flipped_back()
    {
        var toggle = App.Require("LiveVoiceToggle").AsToggleButton();
        toggle.Toggle();
        Assert.True(Retry.WhileFalse(() => App.Require("LiveVoiceTalkButton").IsEnabled, TimeSpan.FromSeconds(20)).Success);

        var mic = App.Require("LiveVoiceMicMute").AsToggleButton();
        mic.Toggle();
        Assert.True(Retry.WhileFalse(() => StateText() == "Microphone muted.", TimeSpan.FromSeconds(5)).Success);
        mic.Toggle();
        Assert.True(Retry.WhileFalse(() => StateText().StartsWith("Hold Ctrl+Space", StringComparison.Ordinal), TimeSpan.FromSeconds(5)).Success);

        App.Require("LiveVoiceSpeakerMute").AsToggleButton().Toggle();
        App.Require("LiveVoiceSpeakerMute").AsToggleButton().Toggle();

        toggle.Toggle();
    }
}
