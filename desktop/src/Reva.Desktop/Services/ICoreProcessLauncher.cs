namespace Reva.Desktop.Services;

public interface ICoreProcessLauncher
{
    /// <summary>Starts Core. <paramref name="dataDirectory"/> and
    /// <paramref name="port"/> are passed as REVA_DATA_DIR/REVA_API_PORT
    /// environment variables only — never as command-line arguments, and
    /// never the bearer token (Core generates it itself, after startup;
    /// Desktop never has a token to pass at launch time).</summary>
    ICoreProcessHandle Launch(CoreExecutableResolution resolution, string dataDirectory, int port);
}
