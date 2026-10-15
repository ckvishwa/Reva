namespace Reva.Desktop.Devices;

/// <summary>Everything the Devices page needs from REVA Core (<c>/v1/devices/*</c>). The page never
/// talks to the pairing gateway or to phones: Core owns that, and the phone never sees the Core token.</summary>
public interface IDevicesApi
{
    Task<DevicesResult<DevicesSnapshot>> GetAsync(CancellationToken cancellationToken = default);

    Task<DevicesResult<GatewayStatus>> SetGatewayEnabledAsync(bool enabled, CancellationToken cancellationToken = default);

    Task<DevicesResult<OpenedPairing>> OpenPairingAsync(CancellationToken cancellationToken = default);

    /// <summary>Approve the waiting phone. <paramref name="fingerprint"/> must be the six digits the user compared.</summary>
    Task<DevicesResult<ApprovedPairing>> ApprovePairingAsync(string fingerprint, CancellationToken cancellationToken = default);

    Task<DevicesResult<DeniedPairing>> DenyPairingAsync(CancellationToken cancellationToken = default);

    Task<DevicesResult<RevokeOutcome>> RevokeAsync(string deviceId, CancellationToken cancellationToken = default);

    /// <summary>Choose which PC actions this phone may ask for (open apps, close apps). Closing still
    /// needs a click on this PC every time.</summary>
    Task<DevicesResult<PhoneAccessOutcome>> SetPhoneAccessAsync(
        string deviceId, bool openApps, bool closeApps, CancellationToken cancellationToken = default);
}
