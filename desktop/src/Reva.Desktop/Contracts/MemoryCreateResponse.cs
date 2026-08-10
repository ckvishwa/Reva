using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.api.schemas.ExplicitMemoryCreateResponse.</summary>
public sealed record MemoryCreateResponse(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("category")] string Category,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("correlation_id")] string CorrelationId);
