using System.Text.Json.Serialization;

namespace Reva.Desktop.Contracts;

/// <summary>Mirrors reva_core.shared.contracts.memory.MemorySourceReference.</summary>
public sealed record MemorySourceReference(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("conversation_id")] string? ConversationId,
    [property: JsonPropertyName("message_id")] string? MessageId,
    [property: JsonPropertyName("origin_device_id")] string OriginDeviceId,
    [property: JsonPropertyName("note")] string? Note);
