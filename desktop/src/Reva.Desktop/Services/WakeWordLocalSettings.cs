using System.Text.Json;

namespace Reva.Desktop.Services;

public sealed record WakeWordLocalSettings(
    bool IsEnabled,
    string KeywordSetVersion,
    IReadOnlyDictionary<string, string> ModelHashes)
{
    public static WakeWordLocalSettings Disabled { get; } =
        new(false, string.Empty, new Dictionary<string, string>());
}

public interface IWakeWordSettingsStore
{
    WakeWordLocalSettings Load();
}

public sealed class JsonWakeWordSettingsStore : IWakeWordSettingsStore
{
    private readonly string _path;

    public JsonWakeWordSettingsStore(string dataDirectory) =>
        _path = Path.Combine(dataDirectory, "wake-word-settings.json");

    public WakeWordLocalSettings Load()
    {
        try
        {
            if (!File.Exists(_path))
            {
                return WakeWordLocalSettings.Disabled;
            }

            var settings = JsonSerializer.Deserialize<WakeWordLocalSettings>(
                File.ReadAllText(_path),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            return settings ?? WakeWordLocalSettings.Disabled;
        }
        catch (JsonException)
        {
            return WakeWordLocalSettings.Disabled;
        }
        catch (IOException)
        {
            return WakeWordLocalSettings.Disabled;
        }
        catch (UnauthorizedAccessException)
        {
            return WakeWordLocalSettings.Disabled;
        }
    }
}
