using System.Text.Json.Serialization;

namespace Reva.Desktop.Devices;

// Mirrors the JSON of REVA Core's /v1/devices/* (reva_core/gateway/routes.py, manager.py).
// Field names are Core's snake_case.

/// <summary>One pairing session as the Devices page sees it. <see cref="Fingerprint"/>, <see cref="DeviceName"/>
/// and <see cref="Platform"/> are present only while a phone is waiting for approval.</summary>
public sealed record PairingView(
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("expires_in")] int ExpiresIn,
    [property: JsonPropertyName("fingerprint")] string? Fingerprint = null,
    [property: JsonPropertyName("device_name")] string? DeviceName = null,
    [property: JsonPropertyName("platform")] string? Platform = null);

public sealed record GatewayStatus(
    [property: JsonPropertyName("enabled")] bool Enabled,
    [property: JsonPropertyName("listening")] bool Listening,
    [property: JsonPropertyName("host")] string? Host,
    [property: JsonPropertyName("port")] int? Port,
    [property: JsonPropertyName("tls_sha256")] string? TlsSha256,
    [property: JsonPropertyName("error")] string? Error,
    [property: JsonPropertyName("pairing")] PairingView? Pairing);

public sealed record PairedDevice(
    [property: JsonPropertyName("device_id")] string DeviceId,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("platform")] string Platform,
    [property: JsonPropertyName("scopes")] IReadOnlyList<string> Scopes,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("fingerprint")] string Fingerprint,
    [property: JsonPropertyName("approved_at")] string ApprovedAt,
    [property: JsonPropertyName("revoked_at")] string? RevokedAt,
    [property: JsonPropertyName("last_seen_at")] string? LastSeenAt,
    [property: JsonPropertyName("actions")] PhoneActionAccess? Actions = null);

/// <summary>What the owner has let a paired phone ask this PC to do. Set only here, on this PC.</summary>
public sealed record PhoneActionAccess(
    [property: JsonPropertyName("open_apps")] bool OpenApps,
    [property: JsonPropertyName("close_apps")] bool CloseApps);

public sealed record PhoneAccessOutcome(
    [property: JsonPropertyName("device_id")] string DeviceId,
    [property: JsonPropertyName("open_apps")] bool OpenApps,
    [property: JsonPropertyName("close_apps")] bool CloseApps);

public sealed record DevicesSnapshot(
    [property: JsonPropertyName("gateway")] GatewayStatus Gateway,
    [property: JsonPropertyName("devices")] IReadOnlyList<PairedDevice> Devices);

public sealed record GatewayEnvelope([property: JsonPropertyName("gateway")] GatewayStatus Gateway);

/// <summary>The one-time pairing code, ready to draw as a QR. It is a secret for its short life:
/// never log it, never store it.</summary>
public sealed record OpenedPairing(
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("qr_text")] string QrText,
    [property: JsonPropertyName("expires_at")] long ExpiresAt);

public sealed record ApprovedPairing([property: JsonPropertyName("device_id")] string DeviceId);

public sealed record RevokeOutcome(
    [property: JsonPropertyName("device_id")] string DeviceId,
    [property: JsonPropertyName("revoked")] bool Revoked,
    [property: JsonPropertyName("changed")] bool Changed);

public sealed record DeniedPairing([property: JsonPropertyName("denied")] bool Denied);
