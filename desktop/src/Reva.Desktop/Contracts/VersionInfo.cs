using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors the JSON body of GET /version.</summary>
public sealed record VersionInfo(
    [property: JsonPropertyName("version")] string Version);
