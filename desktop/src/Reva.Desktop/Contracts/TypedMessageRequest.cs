using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.api.schemas.TypedRequest's JSON body.
/// schema_version is omitted — Python defaults it to 1 server-side when
/// absent, so there's nothing meaningful for the client to send.</summary>
public sealed record TypedMessageRequest(
    [property: JsonPropertyName("content")] string Content);
