using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

public sealed record ReasoningSettings(
    [property: JsonPropertyName("cloud_reasoning")] bool CloudReasoning,
    [property: JsonPropertyName("leaves_device")] IReadOnlyDictionary<string, string> LeavesDevice);

public sealed record KeySavedResponse(
    [property: JsonPropertyName("saved")] bool Saved);
