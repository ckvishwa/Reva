using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class DeveloperModeCoreExecutableLocatorTests
{
    private static string CreateFakeRepo(string tempRoot)
    {
        var repoRoot = Path.Combine(tempRoot, "fake-repo-" + Guid.NewGuid());
        Directory.CreateDirectory(Path.Combine(repoRoot, "reva_core"));
        Directory.CreateDirectory(Path.Combine(repoRoot, ".venv", "Scripts"));
        File.WriteAllText(Path.Combine(repoRoot, "pyproject.toml"), "[project]\nname = \"reva-core\"\n");
        File.WriteAllText(Path.Combine(repoRoot, ".venv", "Scripts", "python.exe"), "fake");
        return repoRoot;
    }

    [Fact]
    public void Resolve_FindsRepoViaRepoRootOverride_WhenVenvPresent()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-test-" + Guid.NewGuid());
        Directory.CreateDirectory(tempRoot);
        var repoRoot = CreateFakeRepo(tempRoot);
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", repoRoot);
        Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", null);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.True(result.IsAvailable);
            Assert.Equal(Path.Combine(repoRoot, ".venv", "Scripts", "python.exe"), result.FileName);
            Assert.Equal("-m reva_core --serve", result.Arguments);
            Assert.Equal(repoRoot, result.WorkingDirectory);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_FindsRepoBySearchingParentDirectories_FromOverriddenStartDirectory()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-test-" + Guid.NewGuid());
        Directory.CreateDirectory(tempRoot);
        var repoRoot = CreateFakeRepo(tempRoot);
        var nestedStart = Path.Combine(repoRoot, "desktop", "src", "Reva.Desktop", "bin");
        Directory.CreateDirectory(nestedStart);
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", nestedStart);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.True(result.IsAvailable);
            Assert.Equal(repoRoot, result.WorkingDirectory);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_ReturnsUnavailable_WhenNoRepoCheckoutFound()
    {
        var emptyDir = Path.Combine(Path.GetTempPath(), "reva-locator-empty-" + Guid.NewGuid());
        Directory.CreateDirectory(emptyDir);
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", emptyDir);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.False(result.IsAvailable);
            Assert.NotNull(result.FailureReason);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(emptyDir, recursive: true);
        }
    }

    [Fact]
    public void Resolve_ReturnsUnavailable_WhenRepoFoundButVenvMissing()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-test-" + Guid.NewGuid());
        var repoRoot = Path.Combine(tempRoot, "repo-no-venv");
        Directory.CreateDirectory(Path.Combine(repoRoot, "reva_core"));
        File.WriteAllText(Path.Combine(repoRoot, "pyproject.toml"), "[project]\n");
        Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", repoRoot);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.False(result.IsAvailable);
            Assert.Contains(".venv", result.FailureReason);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_REPO_ROOT", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_PrefersExplicitPythonExeOverride()
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "reva-locator-explicit-" + Guid.NewGuid());
        Directory.CreateDirectory(tempRoot);
        var pythonExe = Path.Combine(tempRoot, "python.exe");
        File.WriteAllText(pythonExe, "fake");
        Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", pythonExe);
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.True(result.IsAvailable);
            Assert.Equal(pythonExe, result.FileName);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", null);
            Directory.Delete(tempRoot, recursive: true);
        }
    }

    [Fact]
    public void Resolve_ReturnsUnavailable_WhenExplicitPythonExeOverrideMissingFile()
    {
        Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", @"C:\does\not\exist\python.exe");
        try
        {
            var locator = new DeveloperModeCoreExecutableLocator();

            var result = locator.Resolve();

            Assert.False(result.IsAvailable);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_CORE_PYTHON_EXE", null);
        }
    }
}
