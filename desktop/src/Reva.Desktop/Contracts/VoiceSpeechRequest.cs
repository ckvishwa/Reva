using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

public sealed record VoiceSpeechRequest(
    [property: JsonPropertyName("text")] string Text,
    [property: JsonPropertyName("language")] string Language);
