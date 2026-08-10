using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.api.schemas.ExplicitMemoryCreateRequest's
/// JSON body. Category/tags omitted — Python defaults category to "note"
/// and tags to empty when absent; the desktop doesn't need to choose a
/// category for this slice.</summary>
public sealed record MemoryCreateRequest(
    [property: JsonPropertyName("content")] string Content);
