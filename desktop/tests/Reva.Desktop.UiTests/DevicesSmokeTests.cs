using FlaUI.Core.AutomationElements;
using FlaUI.Core.Tools;

namespace Reva.Desktop.UiTests;

public sealed class DevicesFixture : IDisposable
{
    public DevicesFixture()
    {
        Harness = new AppHarness();
        if (Environment.GetEnvironmentVariable("REVA_RUN_UI_TESTS") == "1")
        {
            Harness.WaitForCore();
        }
    }

    public AppHarness Harness { get; }

    public void Dispose() => Harness.Dispose();
}

/// <summary>
/// The Devices page against the real Core and the real pairing gateway (loopback, in-memory vault, temp
/// data directory). The "phone" is <see cref="GatewayPhone"/>, a second implementation of the wire format.
/// Opt-in: REVA_RUN_UI_TESTS=1 on an interactive desktop.
/// </summary>
[Collection("ui")]
public class DevicesSmokeTests : IClassFixture<DevicesFixture>
{
    private readonly DevicesFixture _fixture;

    public DevicesSmokeTests(DevicesFixture fixture) => _fixture = fixture;

    private AppHarness App => _fixture.Harness;

    private static bool Wait(Func<bool> condition, int seconds = 25) =>
        Retry.WhileFalse(condition, TimeSpan.FromSeconds(seconds), TimeSpan.FromMilliseconds(250)).Success;

    /// <summary>Asserts, and takes a failure screenshot only when the assertion fails.</summary>
    private void Expect(bool ok, string what, string shot)
    {
        if (!ok)
        {
            throw new Xunit.Sdk.XunitException($"{what} Focus: {App.FocusedDescription()}. Screenshot: {App.Screenshot(shot)}");
        }
    }

    private string StatusText() => App.Find("GatewayStatus", TimeSpan.FromSeconds(1))?.Name ?? string.Empty;

    private bool Present(string id) => App.Window.FindFirstDescendant(cf => cf.ByAutomationId(id)) is not null;

    private void SetGateway(bool on)
    {
        var toggle = App.Require("GatewayToggle");
        var pattern = toggle.Patterns.Toggle.Pattern;
        var isOn = pattern.ToggleState.Value == FlaUI.Core.Definitions.ToggleState.On;
        if (isOn != on)
        {
            pattern.Toggle();
        }
    }

    [UiFact]
    public async Task The_gateway_pairing_approval_sync_and_revoke_work_end_to_end_in_the_real_window()
    {
        // Another window (an IDE, a chat) on top of the app stops it rendering new rows, so take the foreground
        // first and again before each step that waits on what the page draws.
        App.BringToFront();
        App.Require("Nav_devices").AsButton().Invoke();
        Assert.True(Wait(() => Present("GatewayToggle")), "The Devices page never appeared.");

        // 1. Off by default: nothing to pair with, no phones.
        Assert.True(Wait(() => StatusText().StartsWith("Off", StringComparison.Ordinal)), "Status: " + StatusText());
        Assert.False(App.Require("PairButton").IsEnabled);
        Assert.True(Present("DevicesEmpty"));
        Assert.False(Present("PairingQr"));

        // 2. Turn it on: honest state with the loopback address the test configured, and the key hash.
        SetGateway(true);
        Expect(
            Wait(() => StatusText().StartsWith("Listening on 127.0.0.1:", StringComparison.Ordinal)),
            "Status after switching on: " + StatusText(), "devices-on-failed");
        Assert.True(Present("GatewayKey"));
        Assert.StartsWith("Gateway key ", App.Require("GatewayKey").Name);
        Assert.True(Wait(() => App.Require("PairButton").IsEnabled));

        // 3. Pair a phone: the QR code and its countdown appear; Cancel removes the code.
        App.Require("PairButton").AsButton().Invoke();
        Expect(Wait(() => Present("PairingQr")), "No QR code appeared.", "devices-no-qr");
        // A control below the fold (or half under the window edge) reports only its visible part, so bring the
        // whole code on screen through the page's scroll pattern before measuring it. Never by coordinates.
        var qr = App.ScrollIntoView("PairingQr", 200);
        Assert.True(qr.BoundingRectangle.Width > 150 && qr.BoundingRectangle.Height > 150, $"The QR code is too small to scan: {qr.BoundingRectangle}.");
        Assert.StartsWith("Code expires in ", App.Require("PairingCountdown").Name);
        Thread.Sleep(600);
        App.ScreenshotWindowContent("devices-qr");
        App.Require("PairCancelButton").AsButton().Invoke();
        Assert.True(App.GoneWithin("PairingQr", TimeSpan.FromSeconds(10)), "The QR code stayed on screen after Cancel.");
        Assert.Equal("Pairing cancelled.", App.Require("PairingMessage").Name);
        Assert.True(Wait(() => App.Require("PairButton").IsEnabled), "Pair should be available again.");

        // 4. A phone scans a fresh code. (The test opens the pairing itself and starts it straight away, so the
        //    page sees a phone waiting.) Both screens must show the same six digits.
        using var core = new CoreProbe(App.CoreUrl, App.DataDirectory);
        using var phone = new GatewayPhone();
        var qrText = await core.OpenPairingQrAsync();
        Assert.Equal(200, await phone.StartPairingAsync(qrText));
        Expect(Wait(() => Present("PairingFingerprint")), "No fingerprint appeared.", "devices-no-fingerprint");
        var shown = new string(App.Require("PairingFingerprint").Name.Where(char.IsDigit).ToArray());
        Assert.Equal(phone.ExpectedFingerprint(), shown);
        Assert.True(Present("PairApproveButton") && Present("PairDenyButton"));
        Assert.False(Present("PairingQr"), "The QR code must be gone once a phone has scanned it.");
        App.ScrollIntoView("PairApproveButton", 20);
        Thread.Sleep(600);
        App.ScreenshotWindowContent("devices-pending");
        Assert.Equal(202, await phone.PollAsync());

        // 5. Approve on the PC: the phone gets its grant and appears in the list with a finance-only scope.
        App.BringToFront();
        App.Require("PairApproveButton").AsButton().Invoke();
        Expect(Wait(() => Present("DeviceRow")), "The paired phone never appeared.", "devices-no-row");
        var row = App.Require("DeviceRow").Name;
        Assert.Contains("Smoke phone", row);
        Assert.Contains("Finance only", row);
        Assert.Contains("Active", row);
        Assert.Equal(200, await phone.PollAsync());
        Assert.NotNull(phone.DeviceId);
        App.ScrollIntoView("DeviceRow", 60);
        Thread.Sleep(600);
        App.ScreenshotWindowContent("devices-paired");

        // 6. The paired phone can sync; the page shows it was seen.
        Assert.Equal(200, await phone.PullAsync());

        // 7. Revoke with confirmation: the row says Revoked and the next sync request fails.
        App.BringToFront();
        App.Require("RevokeButton").AsButton().Invoke();
        var dialog = Retry.WhileNull(
            () => App.Window.FindFirstDescendant(cf => cf.ByName("Keep")) ?? App.Window.Automation.GetDesktop().FindFirstDescendant(cf => cf.ByName("Keep")),
            TimeSpan.FromSeconds(10), TimeSpan.FromMilliseconds(250)).Result;
        Assert.NotNull(dialog);
        var confirm = App.Window.Automation.GetDesktop().FindFirstDescendant(cf => cf.ByAutomationId("PrimaryButton"))
            ?? App.Window.Automation.GetDesktop().FindFirstDescendant(cf => cf.ByName("Revoke").And(cf.ByControlType(FlaUI.Core.Definitions.ControlType.Button)));
        Assert.NotNull(confirm);
        confirm!.AsButton().Invoke();
        Expect(
            Wait(() => App.Window.FindAllDescendants(cf => cf.ByAutomationId("DeviceRow")).Any(r => r.Name.Contains("Revoked", StringComparison.Ordinal))),
            "The row never showed Revoked.", "devices-no-revoked");
        Assert.Equal(401, await phone.PullAsync());
        Assert.False(Present("RevokeButton"), "A revoked phone must not offer Revoke again.");
        App.ScrollIntoView("DeviceRow", 60);
        Thread.Sleep(600);
        App.ScreenshotWindowContent("devices-revoked");

        // 8. Switch the gateway off: nothing listens, nothing can pair.
        SetGateway(false);
        Assert.True(Wait(() => StatusText().StartsWith("Off", StringComparison.Ordinal)), "Status: " + StatusText());
        Assert.False(App.Require("PairButton").IsEnabled);
    }
}
