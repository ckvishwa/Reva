using Reva.Desktop.Services;
using System.Text;

var dataDirectory = RuntimePaths.GetDefaultDataDirectory();
var service = new WakeWordProvisioningService(
    dataDirectory,
    new JsonWakeWordSettingsStore(dataDirectory),
    new DpapiWakeWordSecretStore(dataDirectory),
    new RealFileSystemProbe());

try
{
    return await RunAsync(args, service);
}
catch (Exception ex) when (ex is ArgumentException or FileNotFoundException or IOException or UnauthorizedAccessException)
{
    Console.Error.WriteLine(ex.Message);
    return 2;
}

static async Task<int> RunAsync(string[] args, WakeWordProvisioningService service)
{
    if (args.Length == 0)
    {
        PrintUsage();
        return 2;
    }

    switch (args[0])
    {
        case "set-key":
            var accessKey = (await ReadAccessKeyAsync()).Trim();
            service.SaveAccessKey(accessKey);
            Console.WriteLine("Picovoice AccessKey stored with DPAPI for the current Windows user.");
            return 0;

        case "delete-key":
            service.DeleteAccessKey();
            Console.WriteLine("Picovoice AccessKey deleted.");
            return 0;

        case "install-hey-reva":
            var source = RequiredOption(args, "--source");
            var version = RequiredOption(args, "--version");
            var enable = args.Contains("--enable", StringComparer.OrdinalIgnoreCase);
            var result = service.InstallHeyRevaKeyword(source, version, enable);
            Console.WriteLine($"Installed: {result.KeywordPath}");
            Console.WriteLine($"Settings: {result.SettingsPath}");
            Console.WriteLine($"SHA-256: {result.Sha256}");
            Console.WriteLine($"Wake enabled: {enable}");
            return 0;

        default:
            PrintUsage();
            return 2;
    }
}

static string RequiredOption(string[] args, string name)
{
    for (var index = 0; index < args.Length - 1; index++)
    {
        if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase)
            && !string.IsNullOrWhiteSpace(args[index + 1]))
        {
            return args[index + 1];
        }
    }

    throw new ArgumentException($"{name} is required.");
}

static async Task<string> ReadAccessKeyAsync()
{
    if (Console.IsInputRedirected)
    {
        return await Console.In.ReadToEndAsync();
    }

    Console.Error.Write("Picovoice AccessKey: ");
    var builder = new StringBuilder();
    while (true)
    {
        var key = Console.ReadKey(intercept: true);
        if (key.Key == ConsoleKey.Enter)
        {
            Console.Error.WriteLine();
            return builder.ToString();
        }

        if (key.Key == ConsoleKey.Backspace)
        {
            if (builder.Length > 0)
            {
                builder.Length--;
            }

            continue;
        }

        builder.Append(key.KeyChar);
    }
}

static void PrintUsage()
{
    Console.Error.WriteLine("Usage:");
    Console.Error.WriteLine("  Reva.Desktop.WakeProvisioning set-key");
    Console.Error.WriteLine("  Reva.Desktop.WakeProvisioning delete-key");
    Console.Error.WriteLine("  Reva.Desktop.WakeProvisioning install-hey-reva --source <hey-reva.ppn> --version <version> [--enable]");
}
