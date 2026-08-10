using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.api.schemas.TypedResponse's JSON body.</summary>
public sealed record TypedMessageResponse(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("correlation_id")] string CorrelationId,
    [property: JsonPropertyName("reply")] string Reply,
    [property: JsonPropertyName("memory_created")] string? MemoryCreated);
