using Reva.Desktop.Contracts;

namespace Reva.Desktop.Services;

/// <summary>
/// Thin client for REVA Core's localhost API. Owns nothing but transport —
/// no memory semantics, no ranking, no policy. Every failure normalizes to
/// a <see cref="CoreErrorKind"/>; callers never see a raw exception.
///
/// Phase 1B slice 1+2 scope: health/version only. POST /v1/messages,
/// POST /v1/memories, and GET /v1/memories are added in later slices as
/// their respective UI flows are built — see docs/architecture in this
/// repo's desktop/README.md for the slice plan.
/// </summary>
public interface IRevaCoreClient
{
    Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default);

    Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default);
}
