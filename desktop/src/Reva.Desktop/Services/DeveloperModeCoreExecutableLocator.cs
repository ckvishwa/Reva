namespace Reva.Desktop.Services;

/// <summary>
/// Developer-mode resolution only: finds a REVA repository checkout's
/// `.venv\Scripts\python.exe`. Never assume the current working
/// directory or hardcode a machine-specific path — search up from a
/// start directory for the repo markers (`pyproject.toml` + `reva_core\`),
/// bounded so a misconfigured environment fails fast instead of walking
/// to the filesystem root.
/// </summary>
public sealed class DeveloperModeCoreExecutableLocator : ICoreExecutableLocator
{
    public const string PythonExeEnvironmentVariable = "REVA_CORE_PYTHON_EXE";
    public const string RepoRootEnvironmentVariable = "REVA_CORE_REPO_ROOT";
    private const int MaxSearchDepth = 8;

    public CoreExecutableResolution Resolve()
    {
        var explicitPython = Environment.GetEnvironmentVariable(PythonExeEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(explicitPython))
        {
            if (!File.Exists(explicitPython))
            {
                return CoreExecutableResolution.Unavailable(
                    $"REVA_CORE_PYTHON_EXE points to a missing file: {explicitPython}");
            }

            var workingDirectory = Path.GetDirectoryName(explicitPython) ?? Directory.GetCurrentDirectory();
            return CoreExecutableResolution.Available(explicitPython, "-m reva_core --serve", workingDirectory);
        }

        var repoRootOverride = Environment.GetEnvironmentVariable(RepoRootEnvironmentVariable);
        var searchStart = string.IsNullOrWhiteSpace(repoRootOverride) ? AppContext.BaseDirectory : repoRootOverride;

        var repoRoot = FindRepoRoot(searchStart);
        if (repoRoot is null)
        {
            return CoreExecutableResolution.Unavailable(
                "Could not locate a REVA repository checkout with a .venv Python environment. " +
                "Set REVA_CORE_PYTHON_EXE or REVA_CORE_REPO_ROOT to point at one.");
        }

        var pythonExe = Path.Combine(repoRoot, ".venv", "Scripts", "python.exe");
        if (!File.Exists(pythonExe))
        {
            return CoreExecutableResolution.Unavailable(
                $"Found a REVA repository at '{repoRoot}' but .venv\\Scripts\\python.exe is missing. " +
                "Create the virtual environment first.");
        }

        return CoreExecutableResolution.Available(pythonExe, "-m reva_core --serve", repoRoot);
    }

    private static string? FindRepoRoot(string startDirectory)
    {
        var current = Directory.Exists(startDirectory) ? new DirectoryInfo(startDirectory) : null;
        for (var depth = 0; depth < MaxSearchDepth && current is not null; depth++)
        {
            var marker = Path.Combine(current.FullName, "pyproject.toml");
            var coreDir = Path.Combine(current.FullName, "reva_core");
            if (File.Exists(marker) && Directory.Exists(coreDir))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        return null;
    }
}
