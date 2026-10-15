using Reva.Desktop.Services;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Reva.Desktop.Actions;

/// <summary>Where each allowed app actually lives on this PC. The Core knows only app keys and names;
/// launch targets stay here, in a local file, so a request can never name a program or a path.
///
/// Built-in apps use fixed literals. Apps the owner approved on the Apps &amp; Actions page use the
/// Start Menu shortcut found by the scan, and learn their process name the first time REVA sees
/// their window (needed to close them later).</summary>
public sealed class AppTargetStore : IAppTargets
{
    private static readonly LaunchTarget[] BuiltIn =
    {
        new("notepad", "Notepad", "notepad.exe", new[] { "notepad" }),
        new("calculator", "Calculator", "calc.exe", new[] { "CalculatorApp", "Calculator" }),
        new("chrome", "Google Chrome", "chrome.exe", new[] { "chrome" }),
        new("vscode", "Visual Studio Code", "Code.exe", new[] { "Code" }),
        // The protocol handler works for both the desktop and the Store build of Spotify.
        new("spotify", "Spotify", "spotify:", new[] { "Spotify" }),
    };

    private readonly string? _path;
    private readonly object _lock = new();
    private readonly Dictionary<string, StoredApp> _stored = new(StringComparer.Ordinal);

    public AppTargetStore(string? path)
    {
        _path = path;
        Load();
    }

    public LaunchTarget? Find(string key)
    {
        var builtIn = BuiltIn.FirstOrDefault(t => t.Key == key);
        if (builtIn is not null)
        {
            return builtIn;
        }

        lock (_lock)
        {
            return _stored.TryGetValue(key, out var app)
                ? new LaunchTarget(key, app.DisplayName, app.Launch, app.ProcessNames)
                : null;
        }
    }

    /// <summary>Remembers a Start Menu shortcut the owner has approved (or is considering).</summary>
    public void Remember(string key, string displayName, string launch)
    {
        lock (_lock)
        {
            if (BuiltIn.Any(t => t.Key == key))
            {
                return;
            }

            _stored[key] = new StoredApp(displayName, launch, _stored.TryGetValue(key, out var old) ? old.ProcessNames : Array.Empty<string>());
            Save();
        }
    }

    public void Forget(string key)
    {
        lock (_lock)
        {
            if (_stored.Remove(key))
            {
                Save();
            }
        }
    }

    public void Learn(string key, string processName)
    {
        lock (_lock)
        {
            if (!_stored.TryGetValue(key, out var app) || processName.Length == 0
                || app.ProcessNames.Contains(processName, StringComparer.OrdinalIgnoreCase))
            {
                return;
            }

            _stored[key] = app with { ProcessNames = app.ProcessNames.Append(processName).ToArray() };
            Save();
        }
    }

    private void Load()
    {
        if (_path is null || !File.Exists(_path))
        {
            return;
        }

        try
        {
            var apps = JsonSerializer.Deserialize<Dictionary<string, StoredApp>>(File.ReadAllText(_path));
            foreach (var (key, app) in apps ?? new Dictionary<string, StoredApp>())
            {
                _stored[key] = app;
            }
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            DesktopLogger.Info("app_targets.load_failed");
        }
    }

    private void Save()
    {
        if (_path is null)
        {
            return;
        }

        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
            var temporary = _path + ".tmp";
            File.WriteAllText(temporary, JsonSerializer.Serialize(_stored));
            File.Move(temporary, _path, overwrite: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            DesktopLogger.Info("app_targets.save_failed");
        }
    }

    private sealed record StoredApp(
        [property: JsonPropertyName("display_name")] string DisplayName,
        [property: JsonPropertyName("launch")] string Launch,
        [property: JsonPropertyName("process_names")] string[] ProcessNames);
}
