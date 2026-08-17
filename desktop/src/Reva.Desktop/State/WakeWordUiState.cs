namespace Reva.Desktop.State;

public enum WakeWordUiState
{
    Disabled,
    Initializing,
    Listening,
    Detected,
    Capturing,
    Recovering,
    Unavailable,
}

public static class WakeWordUiStateText
{
    public static string For(WakeWordUiState state) => state switch
    {
        WakeWordUiState.Disabled => "Disabled",
        WakeWordUiState.Initializing => "Initializing",
        WakeWordUiState.Listening => "Listening",
        WakeWordUiState.Detected => "Detected",
        WakeWordUiState.Capturing => "Capturing",
        WakeWordUiState.Recovering => "Recovering",
        WakeWordUiState.Unavailable => "Unavailable",
        _ => "Unavailable",
    };
}
