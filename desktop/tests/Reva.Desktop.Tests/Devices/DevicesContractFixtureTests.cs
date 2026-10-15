using System.Net;
using Reva.Desktop.Devices;
using Reva.Desktop.Tests.Finance;

namespace Reva.Desktop.Tests.Devices;

/// <summary>
/// Contract tests: the real REVA Core responses captured by tools/desktop/generate_devices_fixtures.py
/// (kept current by tests/contract/test_devices_ui_fixtures.py) go through the real
/// <see cref="DevicesApiClient"/>. If Core changes a response shape, one side of this pair fails.
/// </summary>
public class DevicesContractFixtureTests
{
    private static string Fixture(string name) =>
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "devices", name + ".json"));

    private static string Body(string name) =>
        System.Text.Json.JsonDocument.Parse(Fixture(name)).RootElement.GetProperty("body").GetRawText();

    private static int Status(string name) =>
        System.Text.Json.JsonDocument.Parse(Fixture(name)).RootElement.GetProperty("status").GetInt32();

    private static DevicesApiClient Serving(HttpStatusCode status, string body)
    {
        var handler = new StubHandler { Responder = (_, _) => Task.FromResult(StubHandler.Json(status, body)) };
        return new DevicesApiClient(
            new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") }, new StubTokens(), TimeSpan.FromSeconds(5));
    }

    private static Task<DevicesResult<DevicesSnapshot>> Snapshot(string fixture) =>
        Serving(HttpStatusCode.OK, Fixture(fixture)).GetAsync();

    [Fact]
    public async Task A_phone_paired_before_actions_existed_has_no_action_access()
    {
        var result = await Snapshot("devices-paired");

        var phone = Assert.Single(result.Value!.Devices);
        Assert.Equal(new PhoneActionAccess(false, false), phone.Actions);
    }

    [Fact]
    public async Task The_owners_choice_of_phone_access_comes_back_in_the_device_list()
    {
        var result = await Snapshot("devices-paired-with-access");

        var phone = Assert.Single(result.Value!.Devices);
        Assert.Equal(new PhoneActionAccess(true, true), phone.Actions);
        Assert.Contains("pc.app.open", phone.Scopes);
        Assert.Contains("finance", phone.Scopes);
    }

    [Fact]
    public async Task Setting_phone_access_sends_a_patch_with_both_choices_and_reads_the_answer()
    {
        string? method = null;
        string? path = null;
        string? body = null;
        var handler = new StubHandler
        {
            Responder = async (request, _) =>
            {
                method = request.Method.Method;
                path = request.RequestUri!.AbsolutePath;
                body = request.Content is null ? null : await request.Content.ReadAsStringAsync();
                return StubHandler.Json(HttpStatusCode.OK, Fixture("pc-access"));
            },
        };
        var client = new DevicesApiClient(
            new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") }, new StubTokens(), TimeSpan.FromSeconds(5));

        var result = await client.SetPhoneAccessAsync("dev-1", true, false);

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        Assert.Equal(("PATCH", "/v1/devices/dev-1/pc-access"), (method, path));
        Assert.Contains("\"open_apps\":true", body);
        Assert.Contains("\"close_apps\":false", body);
        Assert.True(result.Value!.OpenApps && result.Value.CloseApps);
    }

    [Fact]
    public async Task A_gateway_that_was_never_turned_on_is_off_with_no_key_and_no_devices()
    {
        var result = await Snapshot("devices-off");

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        var gateway = result.Value!.Gateway;
        Assert.False(gateway.Enabled);
        Assert.False(gateway.Listening);
        Assert.Null(gateway.Host);
        Assert.Null(gateway.Port);
        Assert.Null(gateway.TlsSha256);
        Assert.Null(gateway.Pairing);
        Assert.Empty(result.Value.Devices);
    }

    [Fact]
    public async Task Turning_the_gateway_on_reports_host_port_and_the_key_hash()
    {
        var result = await Serving(HttpStatusCode.OK, Fixture("gateway-on")).SetGatewayEnabledAsync(true);

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        var gateway = result.Value!;
        Assert.True(gateway.Enabled && gateway.Listening);
        Assert.Equal("192.168.1.20", gateway.Host);
        Assert.Equal(47821, gateway.Port);
        Assert.Equal(64, gateway.TlsSha256!.Length);
        Assert.Null(gateway.Error);
    }

    [Fact]
    public async Task An_open_pairing_carries_the_qr_text_and_a_deadline()
    {
        var result = await Serving(HttpStatusCode.OK, Fixture("pairing-open")).OpenPairingAsync();

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        Assert.StartsWith("REVA-PAIR1:", result.Value!.QrText);
        Assert.Equal(1_800_000_120, result.Value.ExpiresAt);
        Assert.False(string.IsNullOrEmpty(result.Value.SessionId));
        var open = (await Snapshot("devices-pairing-open")).Value!.Gateway.Pairing!;
        Assert.Equal("open", open.State);
        Assert.Null(open.Fingerprint);
    }

    [Fact]
    public async Task A_scanned_pairing_shows_the_phone_name_and_six_digits()
    {
        var pairing = (await Snapshot("devices-pairing-pending")).Value!.Gateway.Pairing!;

        Assert.Equal("pending", pairing.State);
        Assert.Equal("Pixel 8", pairing.DeviceName);
        Assert.Equal("android", pairing.Platform);
        Assert.Matches("^[0-9]{6}$", pairing.Fingerprint);
    }

    [Fact]
    public async Task A_paired_phone_is_listed_with_scope_status_and_last_seen()
    {
        var snapshot = (await Snapshot("devices-paired")).Value!;

        var device = Assert.Single(snapshot.Devices);
        Assert.Equal("Pixel 8", device.Name);
        Assert.Equal("active", device.Status);
        Assert.Equal(new[] { "finance" }, device.Scopes);
        Assert.NotNull(device.LastSeenAt);
        Assert.Null(device.RevokedAt);
        Assert.Equal(64, device.Fingerprint.Length);
        Assert.Equal("approved", snapshot.Gateway.Pairing!.State);
    }

    [Fact]
    public async Task Approving_denying_and_revoking_have_the_shapes_the_client_reads()
    {
        var approved = await Serving(HttpStatusCode.OK, Fixture("pairing-approved")).ApprovePairingAsync("482913");
        var denied = await Serving(HttpStatusCode.OK, Fixture("pairing-denied")).DenyPairingAsync();
        var revoked = await Serving(HttpStatusCode.OK, Fixture("revoked")).RevokeAsync("x");

        Assert.False(string.IsNullOrEmpty(approved.Value!.DeviceId));
        Assert.True(denied.Value!.Denied);
        Assert.True(revoked.Value!.Revoked && revoked.Value.Changed);
        Assert.Equal("denied", (await Snapshot("devices-pairing-denied")).Value!.Gateway.Pairing!.State);
        var after = (await Snapshot("devices-revoked")).Value!.Devices.Single();
        Assert.Equal("revoked", after.Status);
        Assert.NotNull(after.RevokedAt);
    }

    [Fact]
    public async Task Switching_off_keeps_the_key_hash_but_stops_listening()
    {
        var result = await Serving(HttpStatusCode.OK, Fixture("gateway-off")).SetGatewayEnabledAsync(false);

        var gateway = result.Value!;
        Assert.False(gateway.Enabled || gateway.Listening);
        Assert.NotNull(gateway.TlsSha256);
        Assert.Null(gateway.Host);
    }

    [Theory]
    [InlineData("error-gateway-off", DevicesErrorKind.GatewayOff)]
    [InlineData("error-gateway-unavailable", DevicesErrorKind.GatewayOff)]
    [InlineData("error-fingerprint-mismatch", DevicesErrorKind.State)]
    [InlineData("error-unknown-device", DevicesErrorKind.NotFound)]
    [InlineData("error-unauthorized", DevicesErrorKind.Unauthorized)]
    public async Task Cores_error_responses_map_to_the_expected_kinds(string fixture, DevicesErrorKind kind)
    {
        var result = await Serving((HttpStatusCode)Status(fixture), Body(fixture)).OpenPairingAsync();

        Assert.False(result.IsSuccess);
        Assert.Equal(kind, result.Error!.Kind);
    }

    [Fact]
    public async Task A_gateway_that_could_not_start_explains_why_in_cores_words()
    {
        var result = await Serving((HttpStatusCode)Status("error-gateway-unavailable"), Body("error-gateway-unavailable"))
            .SetGatewayEnabledAsync(true);

        Assert.Contains("could not listen", result.Error!.SafeMessage);
    }
}
