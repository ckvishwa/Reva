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
    private const string RequestTimeoutSecondsEnvironmentVariable = "REVA_DESKTOP_REQUEST_TIMEOUT_SECONDS";
    private const string SttRequestTimeoutSecondsEnvironmentVariable = "REVA_DESKTOP_STT_TIMEOUT_SECONDS";

    // Single source of truth — RevaCoreClient's constructor defaults reference
    // these rather than redeclaring their own literals (v1 had 10s/30s written
    // in two files, free to drift).
    public static readonly TimeSpan DefaultRequestTimeout = TimeSpan.FromSeconds(10);
    public static readonly TimeSpan DefaultSttRequestTimeout = TimeSpan.FromSeconds(30);

    public Uri CoreBaseUrl { get; }

    /// <summary>
    /// Directory REVA Core's local_auth_token file and SQLite database
    /// live in. Defaults to the stable per-user location
    /// <see cref="RuntimePaths.GetDefaultDataDirectory"/> (same directory
    /// <see cref="RevaCoreLifecycle"/> passes to a Core process it
    /// launches via REVA_DATA_DIR), overridable via REVA_DATA_DIR for
    /// tests/development — see docs/architecture/runtime-model.md.
    /// </summary>
    public string CoreDataDirectory { get; }

    public TimeSpan RequestTimeout { get; }

    public TimeSpan SttRequestTimeout { get; }

    public DesktopConfiguration(Uri coreBaseUrl, string coreDataDirectory, TimeSpan requestTimeout, TimeSpan sttRequestTimeout)
    {
        if (!IsLoopback(coreBaseUrl))
        {
            throw new DesktopConfigurationException(
                $"REVA Core URL must be loopback-only (localhost/127.0.0.1/::1), got '{coreBaseUrl.Host}'.");
        }

        CoreBaseUrl = coreBaseUrl;
        CoreDataDirectory = coreDataDirectory;
        RequestTimeout = requestTimeout;
        SttRequestTimeout = sttRequestTimeout;
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
            ? RuntimePaths.GetDefaultDataDirectory()
            : dataDirOverride;

        // Overridable because Slice 5's AdkAssistantOrchestrator (real model
        // inference + tool calling, opt-in via REVA_ASSISTANT_ORCHESTRATOR=adk)
        // can genuinely take longer than the 10s default sized for Phase 1A/1B's
        // deterministic instant echo. The default itself is unchanged.
        var timeoutOverride = Environment.GetEnvironmentVariable(RequestTimeoutSecondsEnvironmentVariable);
        var requestTimeout =
            double.TryParse(
                timeoutOverride,
                System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture,
                out var timeoutSeconds) && timeoutSeconds > 0
                ? TimeSpan.FromSeconds(timeoutSeconds)
                : DefaultRequestTimeout;

        var sttTimeoutOverride = Environment.GetEnvironmentVariable(SttRequestTimeoutSecondsEnvironmentVariable);
        var sttRequestTimeout =
            double.TryParse(
                sttTimeoutOverride,
                System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture,
                out var sttTimeoutSeconds) && sttTimeoutSeconds > 0
                ? TimeSpan.FromSeconds(sttTimeoutSeconds)
                : DefaultSttRequestTimeout;

        return new DesktopConfiguration(baseUrl, dataDirectory, requestTimeout, sttRequestTimeout);
    }
}
