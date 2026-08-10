namespace Reva.Desktop.Services;

/// <summary>Reads the local Core auth token. Only ever called from the
/// service layer — never from a View or ViewModel directly.</summary>
public interface ILocalTokenProvider
{
    Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default);
}
