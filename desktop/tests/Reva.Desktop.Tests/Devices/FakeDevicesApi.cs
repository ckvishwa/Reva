using Reva.Desktop.Devices;

namespace Reva.Desktop.Tests.Devices;

/// <summary>An in-memory <see cref="IDevicesApi"/> that behaves like Core's gateway state machine just enough
/// for view-model tests. Every call is recorded; <see cref="Failures"/>[name] makes a call fail.</summary>
internal sealed class FakeDevicesApi : IDevicesApi
{
    public GatewayStatus Gateway { get; set; } = new(false, false, null, null, null, null, null);

    public List<PairedDevice> Devices { get; } = new();

    public List<string> Calls { get; } = new();

    public Dictionary<string, DevicesError> Failures { get; } = new();

    public string OpenQrText { get; set; } = "REVA-PAIR1:fake-qr-payload";

    public long OpenExpiresAt { get; set; }

    public string? ApprovedWith { get; private set; }

    public TaskCompletionSource? Gate { get; set; }

    public static GatewayStatus Listening(PairingView? pairing = null) =>
        new(true, true, "192.168.1.20", 47821, new string('a', 64), null, pairing);

    private async Task<DevicesResult<T>> Run<T>(string name, Func<T> value, CancellationToken ct)
    {
        Calls.Add(name);
        if (Gate is not null)
        {
            await Gate.Task.WaitAsync(ct);
        }

        return Failures.TryGetValue(name, out var error) ? DevicesResult<T>.Failure(error) : DevicesResult<T>.Success(value());
    }

    public Task<DevicesResult<DevicesSnapshot>> GetAsync(CancellationToken ct = default) =>
        Run("Get", () => new DevicesSnapshot(Gateway, Devices.ToList()), ct);

    public Task<DevicesResult<GatewayStatus>> SetGatewayEnabledAsync(bool enabled, CancellationToken ct = default) =>
        Run($"SetGateway:{enabled}", () =>
        {
            Gateway = enabled ? Listening() : new GatewayStatus(false, false, null, null, Gateway.TlsSha256, null, null);
            return Gateway;
        }, ct);

    public Task<DevicesResult<OpenedPairing>> OpenPairingAsync(CancellationToken ct = default) =>
        Run("OpenPairing", () =>
        {
            Gateway = Listening(new PairingView("open", 120));
            return new OpenedPairing("SESSION", OpenQrText, OpenExpiresAt);
        }, ct);

    public Task<DevicesResult<ApprovedPairing>> ApprovePairingAsync(string fingerprint, CancellationToken ct = default) =>
        Run("Approve", () =>
        {
            ApprovedWith = fingerprint;
            Devices.Add(new PairedDevice("dev-1", Gateway.Pairing?.DeviceName ?? "Phone", "android", new[] { "finance" },
                "active", new string('b', 64), "2026-10-12T09:00:00+00:00", null, null));
            Gateway = Listening(new PairingView("approved", 100));
            return new ApprovedPairing("dev-1");
        }, ct);

    public Task<DevicesResult<DeniedPairing>> DenyPairingAsync(CancellationToken ct = default) =>
        Run("Deny", () =>
        {
            Gateway = Listening(new PairingView("denied", 100));
            return new DeniedPairing(true);
        }, ct);

    public Task<DevicesResult<RevokeOutcome>> RevokeAsync(string deviceId, CancellationToken ct = default) =>
        Run($"Revoke:{deviceId}", () =>
        {
            var index = Devices.FindIndex(d => d.DeviceId == deviceId);
            Devices[index] = Devices[index] with { Status = "revoked", RevokedAt = "2026-10-12T10:00:00+00:00" };
            return new RevokeOutcome(deviceId, true, true);
        }, ct);
}
