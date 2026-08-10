using System.Net;

namespace Reva.Desktop.Services;

/// <summary>
/// Desktop-side configuration. The Core URL is validated loopback-only at
/// construction — there is no code path that lets a remote URL through.
/// </summary>
public sealed class DesktopConfiguration
{
    private const string DefaultCoreUrl = "http://127.0.0.1:8756/";
    private const string CoreUrlEnvironmentVariable = "REVA_DESKTOP_CORE_URL";
    private const string DataDirectoryEnvironmentVariable = "REVA_DATA_DIR";

    public Uri CoreBaseUrl { get; }

    /// <summary>
    /// Directory REVA Core's local_auth_token file lives in. Phase 1A's
    /// Python Core has no fixed per-user app-data location yet (documented
    /// gap — see docs/architecture/runtime-model.md), so Desktop and Core
    /// must currently agree on this directory explicitly (same default,
    /// ./data, or the same REVA_DATA_DIR override) rather than the
    /// desktop guessing a Windows-standard path Core doesn't use.
    /// </summary>
    public string CoreDataDirectory { get; }

    public TimeSpan RequestTimeout { get; }

    public DesktopConfiguration(Uri coreBaseUrl, string coreDataDirectory, TimeSpan requestTimeout)
    {
        if (!IsLoopback(coreBaseUrl))
        {
            throw new DesktopConfigurationException(
                $"REVA Core URL must be loopback-only (localhost/127.0.0.1/::1), got '{coreBaseUrl.Host}'.");
        }

        CoreBaseUrl = coreBaseUrl;
        CoreDataDirectory = coreDataDirectory;
        RequestTimeout = requestTimeout;
    }

    public static bool IsLoopback(Uri uri)
    {
        var host = uri.Host;
        if (IPAddress.TryParse(host, out var address))
        {
            return IPAddress.IsLoopback(address);
        }

        return string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase);
    }

    public static DesktopConfiguration CreateDefault()
    {
        var urlOverride = Environment.GetEnvironmentVariable(CoreUrlEnvironmentVariable);
        var baseUrl = string.IsNullOrWhiteSpace(urlOverride)
            ? new Uri(DefaultCoreUrl)
            : new Uri(urlOverride);

        var dataDirOverride = Environment.GetEnvironmentVariable(DataDirectoryEnvironmentVariable);
        var dataDirectory = string.IsNullOrWhiteSpace(dataDirOverride)
            ? Path.Combine(Directory.GetCurrentDirectory(), "data")
            : dataDirOverride;

        return new DesktopConfiguration(baseUrl, dataDirectory, TimeSpan.FromSeconds(10));
    }
}
