using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.shared.contracts.health.HealthStatus.
/// Field names match REVA Core's JSON exactly (snake_case) — no
/// reinterpretation of what these fields mean.</summary>
public sealed record HealthStatus(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("db_schema_version")] int DbSchemaVersion,
    [property: JsonPropertyName("started_at")] DateTimeOffset? StartedAt);
