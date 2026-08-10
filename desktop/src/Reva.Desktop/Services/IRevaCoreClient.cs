using Reva.Desktop.Contracts;

namespace Reva.Desktop.Services;

/// <summary>
/// Thin client for REVA Core's localhost API. Owns nothing but transport —
/// no memory semantics, no ranking, no policy. Every failure normalizes to
/// a <see cref="CoreErrorKind"/>; callers never see a raw exception.
///
/// Phase 1B slice 3 scope adds typed messages. POST /v1/memories and
/// GET /v1/memories are added in their own later slices as the UI flows
/// that use them are built — see desktop/README.md for the slice plan.
/// </summary>
public interface IRevaCoreClient
{
    Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default);

    Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default);

    /// <summary>POST /v1/messages. Authenticated. Does not create durable
    /// memory — that is a separate, explicit action (Slice 4).</summary>
    Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
        string content, CancellationToken cancellationToken = default);
}
