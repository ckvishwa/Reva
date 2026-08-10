using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.api.schemas.MemoryQueryResponseItem.</summary>
public sealed record MemoryQueryResponseItem(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("content")] string Content,
    [property: JsonPropertyName("category")] string Category,
    [property: JsonPropertyName("source")] MemorySourceReference Source,
    [property: JsonPropertyName("tags")] IReadOnlyList<string> Tags,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);
