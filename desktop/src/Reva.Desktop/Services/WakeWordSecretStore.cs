using System.Security.Cryptography;
using System.Text;

namespace Reva.Desktop.Services;

public interface IWakeWordSecretStore
{
    string? GetAccessKey();
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
}
