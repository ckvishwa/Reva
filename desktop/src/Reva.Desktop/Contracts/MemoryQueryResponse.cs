using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.api.schemas.MemoryQueryResponse.</summary>
public sealed record MemoryQueryResponse(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("results")] IReadOnlyList<MemoryQueryResponseItem> Results,
    [property: JsonPropertyName("correlation_id")] string CorrelationId);
