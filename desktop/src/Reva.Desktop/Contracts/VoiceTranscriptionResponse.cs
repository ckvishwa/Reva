using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

public sealed record VoiceTranscriptionResponse(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("text")] string Text,
    [property: JsonPropertyName("language")] string Language,
    [property: JsonPropertyName("duration_ms")] int DurationMs);
