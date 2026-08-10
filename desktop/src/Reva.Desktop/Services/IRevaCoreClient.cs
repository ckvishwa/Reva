using Reva.Desktop.Contracts;

namespace Reva.Desktop.Services;

/// <summary>
/// Thin client for REVA Core's localhost API. Owns nothing but transport —
/// no memory semantics, no ranking, no policy. Every failure normalizes to
/// a <see cref="CoreErrorKind"/>; callers never see a raw exception.
///
/// Phase 1B slice 4 adds explicit memory create/query. Both are
/// authenticated, both talk to Core's existing Phase 1A contracts
/// unchanged — see desktop/README.md for the slice plan.
/// </summary>
public interface IRevaCoreClient
{
    Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default);

    Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default);

    /// <summary>POST /v1/messages. Authenticated. Does not create durable
    /// memory — that is a separate, explicit action.</summary>
    Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
        string content, CancellationToken cancellationToken = default);

    /// <summary>POST /v1/memories. Authenticated. The only way this client
    /// creates durable memory — always an explicit, user-initiated call,
    /// never inferred from SendMessageAsync (ADR-006).</summary>
    Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
        string content, CancellationToken cancellationToken = default);

    /// <summary>GET /v1/memories?q=&amp;limit=. Authenticated. Exact/keyword
    /// query only — no ranking/semantic logic here or in Core yet.</summary>
    Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
        string query, int limit, CancellationToken cancellationToken = default);
}
