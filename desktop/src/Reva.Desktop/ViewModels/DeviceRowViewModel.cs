using System.Globalization;
using Reva.Desktop.Devices;

namespace Reva.Desktop.ViewModels;

/// <summary>One paired phone in the Devices list.</summary>
public sealed class DeviceRowViewModel
{
    public DeviceRowViewModel(PairedDevice device, DateTimeOffset now)
    {
        DeviceId = device.DeviceId;
        Name = device.Name;
        IsActive = device.Status == "active";
        StatusText = IsActive ? "Active" : "Revoked";
        ScopesText = ScopesFor(device.Scopes);
        LastSeenText = IsActive ? LastSeen(device.LastSeenAt, now) : $"Revoked {RelativeTime(device.RevokedAt, now)}";
        FingerprintText = ShortFingerprint(device.Fingerprint);
        PairedText = $"Paired {RelativeTime(device.ApprovedAt, now)}";
        AccessibleName = $"{Name}, {StatusText}, {ScopesText}, {LastSeenText}";
    }

    public string DeviceId { get; }

    public string Name { get; }

    public bool IsActive { get; }

    public string StatusText { get; }

    public string ScopesText { get; }

    public string LastSeenText { get; }

    public string PairedText { get; }

    /// <summary>The first 16 hex digits of the phone key hash, in groups of four, for comparing by eye.</summary>
    public string FingerprintText { get; }

    public string AccessibleName { get; }

    public static string ScopesFor(IReadOnlyList<string> scopes) =>
        scopes.Count == 1 && scopes[0] == "finance"
            ? "Finance only"
            : string.Join(", ", scopes.Select(s => char.ToUpperInvariant(s[0]) + s[1..]));

    public static string ShortFingerprint(string hex)
    {
        var head = hex.Length > 16 ? hex[..16] : hex;
        return string.Join(' ', Enumerable.Range(0, (head.Length + 3) / 4).Select(i => head.Substring(i * 4, Math.Min(4, head.Length - i * 4))));
    }

    private static string LastSeen(string? iso, DateTimeOffset now) =>
        iso is null ? "Never synced" : $"Last seen {RelativeTime(iso, now)}";

    public static string RelativeTime(string? iso, DateTimeOffset now)
    {
        if (iso is null || !DateTimeOffset.TryParse(iso, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var when))
        {
            return "at an unknown time";
        }

        var age = now - when;
        if (age < TimeSpan.Zero || age < TimeSpan.FromMinutes(1))
        {
            return "just now";
        }

        if (age < TimeSpan.FromHours(1))
        {
            return $"{(int)age.TotalMinutes} min ago";
        }

        if (age < TimeSpan.FromDays(1))
        {
            return $"{(int)age.TotalHours} h ago";
        }

        return when.ToLocalTime().ToString("d MMM yyyy", CultureInfo.InvariantCulture);
    }
}
