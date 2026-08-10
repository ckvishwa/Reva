namespace Reva.Desktop.Services;

/// <summary>Thrown when desktop configuration violates a safety invariant
/// (e.g. a non-loopback Core URL). Never carries a token or secret.</summary>
public sealed class DesktopConfigurationException : Exception
{
    public DesktopConfigurationException(string message) : base(message)
    {
    }
}
