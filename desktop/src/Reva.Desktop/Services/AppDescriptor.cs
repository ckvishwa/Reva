namespace Reva.Desktop.Services;

/// <summary>One entry in the fixed app-command allowlist. Every field is a
/// literal constant supplied by <see cref="AppAllowlist"/> — never
/// constructed from user input.</summary>
public sealed record AppDescriptor(
    string Key,
    string DisplayName,
    IReadOnlyList<string> Aliases,
    string OpenTarget,
    string[]? CloseProcessNames);
