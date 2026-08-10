namespace Reva.Desktop.Services;

/// <summary>
/// Reads the Phase 1A local_auth_token file REVA Core generates on first
/// startup. Never throws — any failure (missing file, locked file, no
/// permission) becomes <see cref="TokenLoadResult.Unavailable"/> so the
/// caller can show a safe "authorization unavailable" state instead of
/// crashing or leaking a file-system exception to the UI.
/// </summary>
public sealed class LocalTokenProvider : ILocalTokenProvider
{
    private const string TokenFileName = "local_auth_token";

    private readonly DesktopConfiguration _configuration;

    public LocalTokenProvider(DesktopConfiguration configuration)
    {
        _configuration = configuration;
    }

    public async Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default)
    {
        var path = Path.Combine(_configuration.CoreDataDirectory, TokenFileName);

        try
        {
            if (!File.Exists(path))
            {
                return TokenLoadResult.Unavailable();
            }

            var raw = await File.ReadAllTextAsync(path, cancellationToken).ConfigureAwait(false);
            var trimmed = raw.Trim();
            return trimmed.Length == 0 ? TokenLoadResult.Unavailable() : TokenLoadResult.Available(trimmed);
        }
        catch (IOException)
        {
            return TokenLoadResult.Unavailable();
        }
        catch (UnauthorizedAccessException)
        {
            return TokenLoadResult.Unavailable();
        }
    }
}
