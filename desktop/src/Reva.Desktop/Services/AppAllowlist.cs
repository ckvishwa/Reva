namespace Reva.Desktop.Services;

public static class AppAllowlist
{
    public static readonly IReadOnlyList<AppDescriptor> All = new[]
    {
        new AppDescriptor("chrome", "Google Chrome", new[] { "chrome", "google chrome" }, "chrome.exe", new[] { "chrome" }),
        new AppDescriptor("edge", "Microsoft Edge", new[] { "edge", "microsoft edge" }, "msedge.exe", new[] { "msedge" }),
        new AppDescriptor("notepad", "Notepad", new[] { "notepad" }, "notepad.exe", new[] { "notepad" }),
        // Windows 11 ships Calculator as a packaged app (process "CalculatorApp");
        // older builds use "Calculator". calc.exe is the open target either way.
        new AppDescriptor("calculator", "Calculator", new[] { "calculator", "calc" }, "calc.exe", new[] { "CalculatorApp", "Calculator" }),
        // ShellExecute's App Paths lookup consults HKCU as well as HKLM, so a
        // per-user VS Code install resolves this literal without a hardcoded
        // %LOCALAPPDATA% path. If Task 7 acceptance shows otherwise, add the
        // fallback then — as a recorded finding, not a guess now.
        new AppDescriptor("vscode", "Visual Studio Code", new[] { "vscode", "vs code", "code" }, "Code.exe", new[] { "Code" }),
        new AppDescriptor("explorer", "File Explorer", new[] { "file explorer", "explorer" }, "explorer.exe", null),
        new AppDescriptor("settings", "Windows Settings", new[] { "settings", "windows settings" }, "ms-settings:", null),
    };

    private static readonly IReadOnlyDictionary<string, AppDescriptor> ByAlias = All
        .SelectMany(descriptor => descriptor.Aliases.Select(alias => (alias, descriptor)))
        .ToDictionary(pair => pair.alias, pair => pair.descriptor, StringComparer.Ordinal);

    /// <summary>Exact match only — the argument must already be trimmed and
    /// lowercased by <see cref="CommandRouter"/>. No substring matching: this
    /// is the structural defense against chaining/injection-like input.</summary>
    public static AppDescriptor? FindByAlias(string normalizedArgument) =>
        ByAlias.TryGetValue(normalizedArgument, out var descriptor) ? descriptor : null;
}
