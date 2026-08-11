namespace Reva.Desktop.Services;

/// <summary>
/// Resolves how to launch a local REVA Core process. Deliberately a
/// separate seam from <see cref="ICoreProcessLauncher"/>: this slice only
/// ships <see cref="DeveloperModeCoreExecutableLocator"/> (repo .venv);
/// a future packaged-app locator implements this same interface without
/// touching <see cref="RevaCoreLifecycle"/>.
/// </summary>
public interface ICoreExecutableLocator
{
    CoreExecutableResolution Resolve();
}
