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
    /// <summary>Plain string for display — avoids binding an enum
    /// directly in XAML (x:Bind's implicit enum-to-string conversion is
    /// not something worth relying on after already hitting one WinUI
    /// XAML-compiler surprise this slice).</summary>
    public string RoleLabel => Role == AssistantMessageRole.User ? "You" : "REVA";

    public static AssistantMessage FromUser(string text) => new(AssistantMessageRole.User, text);

    public static AssistantMessage FromAssistant(string text) => new(AssistantMessageRole.Assistant, text);
}
