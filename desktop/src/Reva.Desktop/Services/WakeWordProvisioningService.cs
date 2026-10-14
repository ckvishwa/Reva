using System.Runtime.InteropServices;

namespace Reva.Desktop.Services;

public sealed record WakeWordProvisioningResult(string SettingsPath, string KeywordPath, string Sha256);

public sealed class WakeWordProvisioningService
{
    private readonly string _dataDirectory;
    private readonly IWakeWordSettingsStore _settingsStore;
    private readonly IWakeWordSecretStore _secretStore;
    private readonly IFileSystemProbe _fileSystem;

    public WakeWordProvisioningService(
        string dataDirectory,
        IWakeWordSettingsStore settingsStore,
        IWakeWordSecretStore secretStore,
        IFileSystemProbe fileSystem)
    {
        _dataDirectory = dataDirectory;
        _settingsStore = settingsStore;
        _secretStore = secretStore;
        _fileSystem = fileSystem;
    }

    public string SettingsPath => Path.Combine(_dataDirectory, "wake-word-settings.json");

    public string KeywordDirectory => Path.Combine(_dataDirectory, "wake-word", "keywords");

    public string HeyRevaKeywordPath => Path.Combine(KeywordDirectory, "hey-reva.ppn");

    public void SaveAccessKey(string accessKey) => _secretStore.SaveAccessKey(accessKey);

    public void DeleteAccessKey() => _secretStore.DeleteAccessKey();

    public WakeWordProvisioningResult InstallHeyRevaKeyword(
        string sourcePath,
        string keywordSetVersion,
        bool enableWakeDetection)
    {
        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            throw new ArgumentException("Keyword source path is required.", nameof(sourcePath));
        }

        if (string.IsNullOrWhiteSpace(keywordSetVersion))
        {
            throw new ArgumentException("Keyword set version is required.", nameof(keywordSetVersion));
        }

        if (!_fileSystem.FileExists(sourcePath))
        {
            throw new FileNotFoundException("Keyword source file was not found.", sourcePath);
        }

        if (!string.Equals(Path.GetExtension(sourcePath), ".ppn", StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("Keyword source must be a .ppn file.", nameof(sourcePath));
        }

        Directory.CreateDirectory(KeywordDirectory);
        File.Copy(sourcePath, HeyRevaKeywordPath, overwrite: true);
        var sha256 = _fileSystem.ComputeSha256(HeyRevaKeywordPath);
        _settingsStore.Save(new WakeWordLocalSettings(
            enableWakeDetection,
            keywordSetVersion,
            RuntimeInformation.ProcessArchitecture.ToString(),
            new Dictionary<string, string>
            {
                [WakePhraseDefaults.KeywordSlug(WakePhrase.HeyReva)] = sha256,
            }));

        return new WakeWordProvisioningResult(SettingsPath, HeyRevaKeywordPath, sha256);
    }
}
