namespace Reva.Desktop.State;

public enum AssistantMessageRole
{
    User,
    Assistant,
}

/// <summary>One entry in the current-session assistant conversation.
/// Session-only — no persistence/history in this slice (Slice 3 scope).</summary>
public sealed record AssistantMessage(AssistantMessageRole Role, string Text)
{
    public static AssistantMessage FromUser(string text) => new(AssistantMessageRole.User, text);

    public static AssistantMessage FromAssistant(string text) => new(AssistantMessageRole.Assistant, text);
}
