using System.Text;
using System.Text.Json;
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WakeWordProvisioningTests
{
    [Fact]
    public void DpapiSecretStore_SaveReadDelete_DoesNotStorePlaintext()
    {
        var dataDirectory = CreateTempDirectory();
        var store = new DpapiWakeWordSecretStore(dataDirectory);
        const string accessKey = "picovoice-access-key-value";

        try
        {
            store.SaveAccessKey(accessKey);
            var path = Path.Combine(dataDirectory, "wake-word-access-key.dpapi");
            var fileText = Encoding.UTF8.GetString(File.ReadAllBytes(path));

            Assert.DoesNotContain(accessKey, fileText);
            Assert.Equal(accessKey, store.GetAccessKey());

            store.DeleteAccessKey();

            Assert.Null(store.GetAccessKey());
        }
        finally
        {
            Directory.Delete(dataDirectory, recursive: true);
        }
    }

    [Fact]
    public void InstallHeyRevaKeyword_CopiesModelAndWritesSettingsManifest()
    {
        var dataDirectory = CreateTempDirectory();
        var source = Path.Combine(dataDirectory, "source-hey-reva.ppn");
        File.WriteAllBytes(source, new byte[] { 1, 2, 3, 4, 5 });
        var service = new WakeWordProvisioningService(
            dataDirectory,
            new JsonWakeWordSettingsStore(dataDirectory),
            new DpapiWakeWordSecretStore(dataDirectory),
            new RealFileSystemProbe());

        try
        {
            var result = service.InstallHeyRevaKeyword(source, "2026.08.17", enableWakeDetection: true);

            Assert.True(File.Exists(result.KeywordPath));
            Assert.Equal(Path.Combine(dataDirectory, "wake-word", "keywords", "hey-reva.ppn"), result.KeywordPath);
            Assert.Equal(result.Sha256, new RealFileSystemProbe().ComputeSha256(result.KeywordPath));

            var settings = JsonSerializer.Deserialize<WakeWordLocalSettings>(
                File.ReadAllText(result.SettingsPath),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            Assert.NotNull(settings);
            Assert.True(settings!.IsEnabled);
            Assert.Equal("2026.08.17", settings.KeywordSetVersion);
            Assert.Equal(System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture.ToString(), settings.NativeArchitecture);
            Assert.Equal(result.Sha256, settings.ModelHashes["hey-reva"]);
        }
        finally
        {
            Directory.Delete(dataDirectory, recursive: true);
        }
    }

    [Fact]
    public void InstallHeyRevaKeyword_RejectsNonPpnSource()
    {
        var dataDirectory = CreateTempDirectory();
        var source = Path.Combine(dataDirectory, "hey-reva.txt");
        File.WriteAllText(source, "not a model");
        var service = new WakeWordProvisioningService(
            dataDirectory,
            new JsonWakeWordSettingsStore(dataDirectory),
            new DpapiWakeWordSecretStore(dataDirectory),
            new RealFileSystemProbe());

        try
        {
            Assert.Throws<ArgumentException>(() =>
                service.InstallHeyRevaKeyword(source, "2026.08.17", enableWakeDetection: true));
        }
        finally
        {
            Directory.Delete(dataDirectory, recursive: true);
        }
    }

    private static string CreateTempDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), "reva-wake-provisioning-" + Guid.NewGuid());
        Directory.CreateDirectory(path);
        return path;
    }
}
