namespace Reva.Desktop.Avatar;

/// <summary>
/// What the avatar web view may load. The page is served from one virtual host that maps to the
/// local <c>avatar</c> folder; everything else (any other host, any other scheme, a different
/// port, <c>file:</c>, <c>data:</c> pages, redirects out) is refused, and so is any attempt to open
/// a new window. The page's own CSP says the same thing; this is the host's half (AR-WIN-006).
/// </summary>
public static class AvatarNavigationPolicy
{
    public const string VirtualHost = "reva-avatar.local";
    public const string StartUrl = "https://reva-avatar.local/index.html";

    private static readonly string[] AllowedFiles = { "/index.html", "/avatar.js", "/placeholder.vrm", "/reva-1.0.vrm" };

    /// <summary>True for a request to the avatar's own virtual host and one of its files.</summary>
    public static bool IsAllowed(string? uri)
    {
        if (!Uri.TryCreate(uri, UriKind.Absolute, out var parsed))
        {
            return false;
        }

        return parsed.Scheme == Uri.UriSchemeHttps
            && string.Equals(parsed.Host, VirtualHost, StringComparison.OrdinalIgnoreCase)
            && parsed.IsDefaultPort
            && string.IsNullOrEmpty(parsed.UserInfo)
            && Array.IndexOf(AllowedFiles, parsed.AbsolutePath) >= 0;
    }

    /// <summary>The page may not navigate: only the first load of the start page is allowed.</summary>
    public static bool IsAllowedNavigation(string? uri, bool alreadyLoaded) =>
        !alreadyLoaded && string.Equals(uri, StartUrl, StringComparison.OrdinalIgnoreCase);
}
