namespace Reva.Desktop.Services;

/// <summary>The 4 UI-truthful states Desktop can be in with respect to Core.</summary>
public enum CoreLifecycleState
{
    Starting,
    Connected,
    Unavailable,
    AuthorizationUnavailable,
}
