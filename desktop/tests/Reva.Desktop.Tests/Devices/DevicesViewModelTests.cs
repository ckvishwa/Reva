using Reva.Desktop.Devices;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Devices;

internal sealed class FakeQr : IQrEncoder
{
    public List<string> Encoded { get; } = new();

    public bool Fail { get; set; }

    public byte[] EncodePng(string text)
    {
        if (Fail)
        {
            throw new InvalidOperationException("no");
        }

        Encoded.Add(text);
        return new byte[] { 0x89, 0x50, 0x4E, 0x47, (byte)Encoded.Count };
    }
}

public class DevicesViewModelTests
{
    private static readonly DateTimeOffset Start = new(2026, 10, 12, 9, 0, 0, TimeSpan.Zero);

    private sealed class Clock
    {
        public DateTimeOffset Now { get; set; } = Start;
    }

    private static (DevicesViewModel Vm, FakeDevicesApi Api, FakeQr Qr, Clock Clock) Create()
    {
        var api = new FakeDevicesApi();
        var qr = new FakeQr();
        var clock = new Clock();
        api.OpenExpiresAt = Start.ToUnixTimeSeconds() + 120;
        return (new DevicesViewModel(api, qr, () => clock.Now), api, qr, clock);
    }

    private static async Task<(DevicesViewModel Vm, FakeDevicesApi Api, FakeQr Qr, Clock Clock)> Listening()
    {
        var created = Create();
        await created.Vm.SetGatewayEnabledAsync(true);
        return created;
    }

    private static async Task<(DevicesViewModel Vm, FakeDevicesApi Api, FakeQr Qr, Clock Clock)> WithQrOpen()
    {
        var created = await Listening();
        await created.Vm.StartPairingAsync();
        return created;
    }

    private static async Task<(DevicesViewModel Vm, FakeDevicesApi Api, FakeQr Qr, Clock Clock)> WithPhoneWaiting()
    {
        var created = await WithQrOpen();
        created.Api.Gateway = FakeDevicesApi.Listening(new PairingView("pending", 110, "482913", "Pixel 8", "android"));
        await created.Vm.RefreshAsync();
        return created;
    }

    // ------------------------------------------------------------------------------- gateway

    [Fact]
    public void Before_anything_loads_the_gateway_is_unknown_and_nothing_is_offered()
    {
        var (vm, api, _, _) = Create();

        Assert.Equal(GatewayPhase.Unknown, vm.Gateway);
        Assert.False(vm.CanPair);
        Assert.False(vm.GatewayEnabled);
        Assert.Empty(api.Calls);
    }

    [Fact]
    public async Task A_gateway_that_is_off_says_so_and_offers_no_pairing()
    {
        var (vm, _, _, _) = Create();

        await vm.RefreshAsync();

        Assert.Equal(GatewayPhase.Off, vm.Gateway);
        Assert.False(vm.GatewayEnabled);
        Assert.Equal("Off. No phone can reach this PC.", vm.StatusText);
        Assert.False(vm.CanPair);
        Assert.False(vm.HasKey);
        Assert.Equal(TimeSpan.FromSeconds(5), vm.PollDelay);
    }

    [Fact]
    public async Task Turning_it_on_reports_where_it_listens_and_the_short_key_hash()
    {
        var (vm, api, _, _) = await Listening();

        Assert.Equal(GatewayPhase.Listening, vm.Gateway);
        Assert.True(vm.GatewayEnabled);
        Assert.True(vm.IsListening);
        Assert.StartsWith("Listening on 192.168.1.20:47821.", vm.StatusText);
        Assert.Equal("Gateway key aaaa aaaa aaaa aaaa", vm.KeyText);
        Assert.True(vm.CanPair);
        Assert.Contains("SetGateway:True", api.Calls);
    }

    [Fact]
    public async Task A_gateway_that_cannot_start_stays_off_and_shows_why()
    {
        var (vm, api, _, _) = Create();
        api.Failures["SetGateway:True"] = new DevicesError(
            DevicesErrorKind.GatewayOff, "the gateway could not listen on 10.0.0.2:47821: is the port already in use?");

        await vm.SetGatewayEnabledAsync(true);

        Assert.False(vm.GatewayEnabled);
        Assert.Equal(GatewayPhase.Off, vm.Gateway);
        Assert.Contains("could not listen", vm.ErrorMessage);
        Assert.False(vm.CanPair);
    }

    [Fact]
    public async Task Switched_on_but_not_listening_is_a_failure_with_cores_reason()
    {
        var (vm, api, _, _) = Create();
        api.Gateway = new GatewayStatus(true, false, null, null, null, "no local network address was found", null);

        await vm.RefreshAsync();

        Assert.Equal(GatewayPhase.Failed, vm.Gateway);
        Assert.True(vm.GatewayEnabled);
        Assert.Equal("Switched on, but not listening: no local network address was found", vm.StatusText);
        Assert.False(vm.CanPair);
    }

    [Fact]
    public async Task A_core_that_cannot_be_reached_shows_an_error_and_keeps_what_was_on_screen()
    {
        var (vm, api, _, _) = await Listening();
        api.Failures["Get"] = new DevicesError(DevicesErrorKind.Unavailable, "REVA Core is not reachable.");

        await vm.RefreshAsync();

        Assert.Equal("REVA Core is not reachable.", vm.ErrorMessage);
        Assert.Equal(GatewayPhase.Listening, vm.Gateway);
        api.Failures.Clear();
        await vm.RefreshAsync();
        Assert.Null(vm.ErrorMessage);
    }

    [Fact]
    public async Task Turning_it_off_while_a_qr_is_showing_removes_the_qr()
    {
        var (vm, _, _, _) = await WithQrOpen();
        Assert.True(vm.ShowsQr);

        await vm.SetGatewayEnabledAsync(false);

        Assert.False(vm.ShowsQr);
        Assert.Null(vm.QrPng);
        Assert.Equal(PairingPhase.None, vm.Pairing);
        Assert.Equal(GatewayPhase.Off, vm.Gateway);
    }

    // ------------------------------------------------------------------------------- QR open

    [Fact]
    public async Task Pair_a_phone_draws_the_qr_and_starts_a_two_minute_countdown()
    {
        var (vm, api, qr, _) = await Listening();

        await vm.StartPairingAsync();

        Assert.Equal(PairingPhase.QrOpen, vm.Pairing);
        Assert.True(vm.ShowsQr);
        Assert.NotNull(vm.QrPng);
        Assert.Equal(new[] { "REVA-PAIR1:fake-qr-payload" }, qr.Encoded);
        Assert.Equal("Code expires in 2:00", vm.CountdownText);
        Assert.False(vm.CanPair, "one pairing at a time");
        Assert.Equal(TimeSpan.FromSeconds(1), vm.PollDelay);
        Assert.Contains("OpenPairing", api.Calls);
    }

    [Fact]
    public async Task The_qr_text_is_not_kept_anywhere_on_the_view_model()
    {
        var (vm, _, _, _) = await WithQrOpen();

        foreach (var property in typeof(DevicesViewModel).GetProperties())
        {
            var value = property.GetValue(vm);
            Assert.False(value is string text && text.Contains("fake-qr-payload"), property.Name);
        }
    }

    [Fact]
    public async Task The_countdown_ticks_down_and_an_expired_qr_is_removed_without_waiting_for_core()
    {
        var (vm, api, _, clock) = await WithQrOpen();

        clock.Now = Start.AddSeconds(61);
        vm.Tick();
        Assert.Equal("Code expires in 0:59", vm.CountdownText);
        Assert.True(vm.ShowsQr);

        clock.Now = Start.AddSeconds(121);
        vm.Tick();
        Assert.Equal(PairingPhase.Expired, vm.Pairing);
        Assert.False(vm.ShowsQr);
        Assert.Null(vm.QrPng);
        Assert.Equal("The pairing code expired. Start again for a new one.", vm.PairingMessage);
        Assert.Equal(string.Empty, vm.CountdownText);
        Assert.DoesNotContain("Get", api.Calls.Skip(2));
    }

    [Fact]
    public async Task After_it_expires_the_user_can_start_again_for_a_new_code()
    {
        var (vm, api, qr, clock) = await WithQrOpen();
        clock.Now = Start.AddSeconds(125);
        vm.Tick();

        Assert.True(vm.CanPair);
        api.OpenExpiresAt = clock.Now.ToUnixTimeSeconds() + 120;
        await vm.StartPairingAsync();

        Assert.Equal(PairingPhase.QrOpen, vm.Pairing);
        Assert.Null(vm.PairingMessage);
        Assert.Equal(2, qr.Encoded.Count);
    }

    [Fact]
    public async Task Cancelling_the_qr_tells_core_and_clears_it()
    {
        var (vm, api, _, _) = await WithQrOpen();

        await vm.DenyAsync();

        Assert.Equal(PairingPhase.None, vm.Pairing);
        Assert.Null(vm.QrPng);
        Assert.Equal("Pairing cancelled.", vm.PairingMessage);
        Assert.Contains("Deny", api.Calls);
    }

    [Fact]
    public async Task A_qr_that_cannot_be_drawn_closes_the_pairing_instead_of_leaving_a_live_code()
    {
        var (vm, api, qr, _) = await Listening();
        qr.Fail = true;

        await vm.StartPairingAsync();

        Assert.Equal(PairingPhase.None, vm.Pairing);
        Assert.Equal("REVA could not draw the pairing code.", vm.ErrorMessage);
        Assert.Contains("Deny", api.Calls);
    }

    [Fact]
    public async Task Pairing_cannot_start_while_the_gateway_is_off_or_while_one_is_open()
    {
        var (vm, api, _, _) = Create();
        await vm.RefreshAsync();
        await vm.StartPairingAsync();
        Assert.DoesNotContain("OpenPairing", api.Calls);

        var (open, openApi, _, _) = await WithQrOpen();
        await open.StartPairingAsync();
        Assert.Single(openApi.Calls, c => c == "OpenPairing");
    }

    [Fact]
    public async Task A_failure_opening_a_pairing_shows_the_error_and_no_qr()
    {
        var (vm, api, _, _) = await Listening();
        api.Failures["OpenPairing"] = new DevicesError(DevicesErrorKind.GatewayOff, "Turn the pairing gateway on first.");

        await vm.StartPairingAsync();

        Assert.Equal("Turn the pairing gateway on first.", vm.ErrorMessage);
        Assert.False(vm.ShowsQr);
    }

    // ------------------------------------------------------------------------------- pending

    [Fact]
    public async Task When_a_phone_scans_the_digits_and_name_appear_and_the_qr_goes_away()
    {
        var (vm, _, _, _) = await WithPhoneWaiting();

        Assert.Equal(PairingPhase.Pending, vm.Pairing);
        Assert.True(vm.ShowsPending);
        Assert.Equal("482 913", vm.PendingFingerprintText);
        Assert.Equal("Pixel 8", vm.PendingDeviceName);
        Assert.False(vm.ShowsQr);
        Assert.Null(vm.QrPng);
        Assert.Equal("Approve within 1:50", vm.CountdownText);
    }

    [Fact]
    public async Task Approve_sends_the_six_digits_back_and_pairs_the_phone()
    {
        var (vm, api, _, _) = await WithPhoneWaiting();

        await vm.ApproveAsync();

        Assert.Equal("482913", api.ApprovedWith);
        Assert.Equal(PairingPhase.Approved, vm.Pairing);
        Assert.Equal("Pixel 8 is paired. It can sync Finance with this PC.", vm.PairingMessage);
        var row = Assert.Single(vm.Devices);
        Assert.Equal("Finance only", row.ScopesText);
        Assert.Null(vm.PendingFingerprintText);
        Assert.True(vm.CanPair);
    }

    [Fact]
    public async Task A_refused_approval_shows_the_reason_and_pairs_nothing()
    {
        var (vm, api, _, _) = await WithPhoneWaiting();
        api.Failures["Approve"] = new DevicesError(
            DevicesErrorKind.State, "Those digits do not match the pairing in progress. Nothing was approved.");

        await vm.ApproveAsync();

        Assert.Equal("Those digits do not match the pairing in progress. Nothing was approved.", vm.ErrorMessage);
        Assert.Empty(vm.Devices);
        Assert.Equal(PairingPhase.Pending, vm.Pairing);
    }

    [Fact]
    public async Task Deny_turns_the_phone_away()
    {
        var (vm, api, _, _) = await WithPhoneWaiting();

        await vm.DenyAsync();

        Assert.Equal(PairingPhase.Denied, vm.Pairing);
        Assert.Equal("Pairing was denied. Nothing was shared.", vm.PairingMessage);
        Assert.Empty(vm.Devices);
        Assert.Contains("Deny", api.Calls);
        Assert.Null(api.ApprovedWith);
    }

    [Fact]
    public async Task Approve_does_nothing_unless_a_phone_is_waiting()
    {
        var (vm, api, _, _) = await WithQrOpen();

        await vm.ApproveAsync();

        Assert.DoesNotContain("Approve", api.Calls);
    }

    [Fact]
    public async Task Two_quick_approvals_make_one_call()
    {
        var (vm, api, _, _) = await WithPhoneWaiting();
        api.Gate = new TaskCompletionSource();

        var first = vm.ApproveAsync();
        var second = vm.ApproveAsync();
        api.Gate.SetResult();
        await Task.WhenAll(first, second);

        Assert.Single(api.Calls, c => c == "Approve");
    }

    // ------------------------------------------------------------------------ what Core reports

    [Theory]
    [InlineData("expired", PairingPhase.Expired, "The pairing code expired. Start again for a new one.")]
    [InlineData("denied", PairingPhase.Denied, "Pairing was denied. Nothing was shared.")]
    [InlineData("locked", PairingPhase.Locked, "Too many wrong codes were tried, so this pairing was closed. Start again.")]
    [InlineData("cancelled", PairingPhase.None, "Pairing was cancelled.")]
    public async Task A_pairing_that_core_ended_is_shown_as_ended(string state, PairingPhase phase, string message)
    {
        var (vm, api, _, _) = await WithQrOpen();
        api.Gateway = FakeDevicesApi.Listening(new PairingView(state, 0));

        await vm.RefreshAsync();

        Assert.Equal(phase, vm.Pairing);
        Assert.Equal(message, vm.PairingMessage);
        Assert.Null(vm.QrPng);
        Assert.True(vm.CanPair);
    }

    [Fact]
    public async Task A_phone_approved_elsewhere_shows_as_paired_with_its_name()
    {
        var (vm, api, _, _) = await WithPhoneWaiting();
        api.Gateway = FakeDevicesApi.Listening(new PairingView("approved", 100));

        await vm.RefreshAsync();

        Assert.Equal(PairingPhase.Approved, vm.Pairing);
        Assert.Equal("Pixel 8 is paired. It can sync Finance with this PC.", vm.PairingMessage);
    }

    [Fact]
    public async Task A_finished_pairing_message_stays_until_dismissed_and_is_not_repeated_by_polling()
    {
        var (vm, api, _, _) = await WithPhoneWaiting();
        await vm.ApproveAsync();
        var message = vm.PairingMessage;

        await vm.RefreshAsync();
        await vm.RefreshAsync();

        Assert.Equal(message, vm.PairingMessage);
        vm.DismissMessage();
        Assert.Null(vm.PairingMessage);
        Assert.Equal(PairingPhase.None, vm.Pairing);
        Assert.Equal(1, api.Calls.Count(c => c == "OpenPairing")); // only the one that began it
    }

    [Fact]
    public async Task If_core_loses_the_session_the_qr_and_the_waiting_phone_are_dropped()
    {
        var (open, openApi, _, _) = await WithQrOpen();
        openApi.Gateway = FakeDevicesApi.Listening(null);
        await open.RefreshAsync();
        Assert.Equal(PairingPhase.None, open.Pairing);
        Assert.Equal("Pairing ended.", open.PairingMessage);
        Assert.Null(open.QrPng);

        var (waiting, waitingApi, _, _) = await WithPhoneWaiting();
        waitingApi.Gateway = FakeDevicesApi.Listening(null);
        await waiting.RefreshAsync();
        Assert.Equal(PairingPhase.None, waiting.Pairing);
        Assert.Null(waiting.PendingFingerprintText);
    }

    [Fact]
    public async Task An_open_pairing_whose_qr_this_page_never_drew_is_closed_not_shown_blank()
    {
        var (vm, api, _, _) = await Listening();
        api.Gateway = FakeDevicesApi.Listening(new PairingView("open", 90));

        await vm.RefreshAsync();

        Assert.Equal(PairingPhase.None, vm.Pairing);
        Assert.False(vm.ShowsQr);
        Assert.Equal("A pairing was already open. Start a new one to see its QR code.", vm.PairingMessage);
        Assert.Contains("Deny", api.Calls);
    }

    [Fact]
    public async Task A_gateway_switched_off_elsewhere_ends_the_pairing_on_screen()
    {
        var (vm, api, _, _) = await WithQrOpen();
        api.Gateway = new GatewayStatus(false, false, null, null, null, null, null);

        await vm.RefreshAsync();

        Assert.Equal(GatewayPhase.Off, vm.Gateway);
        Assert.Equal(PairingPhase.None, vm.Pairing);
        Assert.Null(vm.QrPng);
    }

    // ------------------------------------------------------------------------------- devices

    private static PairedDevice Phone(string id, string status = "active", string? seen = null) =>
        new(id, "Pixel 8", "android", new[] { "finance" }, status, new string('c', 64),
            "2026-10-12T08:00:00+00:00", status == "revoked" ? "2026-10-12T08:30:00+00:00" : null, seen);

    [Fact]
    public async Task The_device_list_shows_name_status_scope_last_seen_and_a_short_key()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1", seen: "2026-10-12T08:55:00+00:00"));
        api.Devices.Add(Phone("d2"));
        api.Devices.Add(Phone("d3", "revoked"));

        await vm.RefreshAsync();

        Assert.Equal(3, vm.Devices.Count);
        var first = vm.Devices[0];
        Assert.Equal("Active", first.StatusText);
        Assert.Equal("Finance only", first.ScopesText);
        Assert.Equal("Synced 5 min ago", first.LastSeenText);
        Assert.Equal("cccc cccc cccc cccc", first.FingerprintText);
        Assert.Equal("Paired 1 h ago", first.PairedText);
        Assert.Equal("Never synced", vm.Devices[1].LastSeenText);
        Assert.Equal("Revoked", vm.Devices[2].StatusText);
        Assert.StartsWith("Revoked 30 min ago", vm.Devices[2].LastSeenText);
        Assert.Equal("Pixel 8, Active, Finance only, Synced 5 min ago", first.AccessibleName);
    }

    [Fact]
    public async Task Revoking_a_phone_marks_it_revoked_and_says_it_can_no_longer_sync()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1"));
        await vm.RefreshAsync();

        await vm.RevokeAsync(vm.Devices[0]);

        Assert.Contains("Revoke:d1", api.Calls);
        Assert.Equal("Revoked", vm.Devices[0].StatusText);
        Assert.False(vm.Devices[0].IsActive);
        Assert.Equal("Pixel 8 was revoked. It can no longer sync.", vm.PairingMessage);
    }

    [Fact]
    public async Task The_owner_lets_a_phone_open_apps_here_and_can_take_it_back()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1"));
        await vm.RefreshAsync();
        Assert.False(vm.Devices[0].OpenAppsAllowed);
        Assert.False(vm.Devices[0].CloseAppsAllowed);

        await vm.SetPhoneAccessAsync(vm.Devices[0], openApps: true, closeApps: false);

        Assert.Equal(("d1", true, false), Assert.Single(api.AccessChanges));
        Assert.True(vm.Devices[0].OpenAppsAllowed);
        Assert.False(vm.Devices[0].CloseAppsAllowed);
        await vm.SetPhoneAccessAsync(vm.Devices[0], openApps: false, closeApps: false);
        Assert.False(vm.Devices[0].OpenAppsAllowed);
    }

    [Fact]
    public async Task Closing_is_described_as_needing_the_owners_approval_here()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1"));
        await vm.RefreshAsync();

        await vm.SetPhoneAccessAsync(vm.Devices[0], openApps: true, closeApps: true);

        Assert.Contains("can open apps here", vm.Devices[0].ScopesText);
        Assert.Contains("can ask to close apps (you approve here)", vm.Devices[0].ScopesText);
        Assert.StartsWith("Finance sync", vm.Devices[0].ScopesText);
    }

    [Fact]
    public async Task A_failed_access_change_shows_the_error_and_changes_nothing_on_screen()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1"));
        await vm.RefreshAsync();
        api.Failures["SetPhoneAccess:d1:True:True"] = new DevicesError(DevicesErrorKind.ServerFailure, "REVA Core reported an internal error.");

        await vm.SetPhoneAccessAsync(vm.Devices[0], openApps: true, closeApps: true);

        Assert.Equal("REVA Core reported an internal error.", vm.ErrorMessage);
        Assert.False(vm.Devices[0].OpenAppsAllowed);
    }

    [Fact]
    public async Task A_revoked_phone_cannot_be_given_access()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1", "revoked"));
        await vm.RefreshAsync();

        await vm.SetPhoneAccessAsync(vm.Devices[0], openApps: true, closeApps: true);

        Assert.Empty(api.AccessChanges);
    }

    [Fact]
    public async Task A_failed_revoke_shows_the_error_and_leaves_the_phone_active()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1"));
        await vm.RefreshAsync();
        api.Failures["Revoke:d1"] = new DevicesError(DevicesErrorKind.ServerFailure, "REVA Core reported an internal error.");

        await vm.RevokeAsync(vm.Devices[0]);

        Assert.Equal("REVA Core reported an internal error.", vm.ErrorMessage);
        Assert.True(vm.Devices[0].IsActive);
    }

    [Fact]
    public async Task A_revoked_phone_cannot_be_revoked_again()
    {
        var (vm, api, _, _) = Create();
        api.Devices.Add(Phone("d1", "revoked"));
        await vm.RefreshAsync();

        await vm.RevokeAsync(vm.Devices[0]);

        Assert.DoesNotContain("Revoke:d1", api.Calls);
    }

    [Fact]
    public async Task The_scope_text_never_hides_a_wider_grant()
    {
        Assert.Equal("Finance only", DeviceRowViewModel.ScopesFor(new[] { "finance" }));
        Assert.Equal("Finance, Memory", DeviceRowViewModel.ScopesFor(new[] { "finance", "memory" }));
        await Task.CompletedTask;
    }

    // ----------------------------------------------------------------------------- ordering

    private sealed class SequencedApi : IDevicesApi
    {
        public Queue<TaskCompletionSource<DevicesResult<DevicesSnapshot>>> Gets { get; } = new();

        public Task<DevicesResult<DevicesSnapshot>> GetAsync(CancellationToken cancellationToken = default) => Gets.Dequeue().Task;

        public Task<DevicesResult<GatewayStatus>> SetGatewayEnabledAsync(bool enabled, CancellationToken c = default) => throw new NotSupportedException();

        public Task<DevicesResult<OpenedPairing>> OpenPairingAsync(CancellationToken c = default) => throw new NotSupportedException();

        public Task<DevicesResult<ApprovedPairing>> ApprovePairingAsync(string fingerprint, CancellationToken c = default) => throw new NotSupportedException();

        public Task<DevicesResult<DeniedPairing>> DenyPairingAsync(CancellationToken c = default) => throw new NotSupportedException();

        public Task<DevicesResult<RevokeOutcome>> RevokeAsync(string deviceId, CancellationToken c = default) => throw new NotSupportedException();

        public Task<DevicesResult<PhoneAccessOutcome>> SetPhoneAccessAsync(string deviceId, bool openApps, bool closeApps, CancellationToken c = default) => throw new NotSupportedException();
    }

    [Fact]
    public async Task A_slow_older_refresh_cannot_overwrite_a_newer_one()
    {
        var api = new SequencedApi();
        var older = new TaskCompletionSource<DevicesResult<DevicesSnapshot>>();
        var newer = new TaskCompletionSource<DevicesResult<DevicesSnapshot>>();
        api.Gets.Enqueue(older);
        api.Gets.Enqueue(newer);
        var vm = new DevicesViewModel(api, new FakeQr(), () => Start);

        var first = vm.RefreshAsync();
        var second = vm.RefreshAsync();
        newer.SetResult(DevicesResult<DevicesSnapshot>.Success(new DevicesSnapshot(FakeDevicesApi.Listening(), new List<PairedDevice>())));
        await second;
        older.SetResult(DevicesResult<DevicesSnapshot>.Success(
            new DevicesSnapshot(new GatewayStatus(false, false, null, null, null, null, null), new List<PairedDevice>())));
        await first;

        Assert.Equal(GatewayPhase.Listening, vm.Gateway);
    }
}
