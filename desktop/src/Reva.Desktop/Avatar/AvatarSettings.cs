using System.Text.Json;

namespace Reva.Desktop.Avatar;

/// <summary>The owner's avatar choices: off, reduced motion, quality (FR-AV-006, AR-VA-012).</summary>
public sealed record AvatarSettings(bool Enabled, bool? ReducedMotion, string Quality)
{
    public static readonly AvatarSettings Default = new(true, null, "medium");

    /// <summary>Reduced motion: the explicit choice, otherwise whatever Windows is set to.</summary>
    public bool EffectiveReducedMotion(bool systemAnimationsEnabled) => ReducedMotion ?? !systemAnimationsEnabled;
}

/// <summary>A small JSON file in the data directory. A missing or damaged file means the defaults.</summary>
public sealed class AvatarSettingsStore
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web) { WriteIndented = true };
    private readonly string _path;

    public AvatarSettingsStore(string directory)
    {
        _path = Path.Combine(directory, "desktop-avatar.json");
    }

    public AvatarSettings Load()
    {
        try
        {
            var raw = JsonSerializer.Deserialize<AvatarSettings>(File.ReadAllText(_path), Options);
            if (raw is null || Array.IndexOf(AvatarProtocol.Qualities, raw.Quality) < 0)
            {
                return AvatarSettings.Default;
            }

            return raw;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            return AvatarSettings.Default;
        }
    }

    public void Save(AvatarSettings settings)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
            var temporary = _path + ".tmp";
            File.WriteAllText(temporary, JsonSerializer.Serialize(settings, Options));
            File.Move(temporary, _path, overwrite: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Settings that cannot be saved are used for this run only.
        }
    }
}
