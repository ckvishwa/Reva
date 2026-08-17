using System.Security.Cryptography;
using System.Text;

namespace Reva.Desktop.Services;

public interface IWakeWordSecretStore
{
    string? GetAccessKey();

    void SaveAccessKey(string accessKey);

    void DeleteAccessKey();
}

public sealed class DpapiWakeWordSecretStore : IWakeWordSecretStore
{
    private readonly string _path;

    public DpapiWakeWordSecretStore(string dataDirectory) =>
        _path = Path.Combine(dataDirectory, "wake-word-access-key.dpapi");

    public string? GetAccessKey()
    {
        try
        {
            if (!File.Exists(_path))
            {
                return null;
            }

            var protectedBytes = File.ReadAllBytes(_path);
            var bytes = ProtectedData.Unprotect(protectedBytes, optionalEntropy: null, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(bytes);
        }
        catch (CryptographicException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    public void SaveAccessKey(string accessKey)
    {
        if (string.IsNullOrWhiteSpace(accessKey))
        {
            throw new ArgumentException("AccessKey is required.", nameof(accessKey));
        }

        var directory = Path.GetDirectoryName(_path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var bytes = Encoding.UTF8.GetBytes(accessKey.Trim());
        var protectedBytes = ProtectedData.Protect(bytes, optionalEntropy: null, DataProtectionScope.CurrentUser);
        File.WriteAllBytes(_path, protectedBytes);
    }

    public void DeleteAccessKey()
    {
        try
        {
            File.Delete(_path);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
