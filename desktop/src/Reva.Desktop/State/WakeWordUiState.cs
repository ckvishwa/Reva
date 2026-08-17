namespace Reva.Desktop.State;

public enum WakeWordUiState
{
    Off,
    Starting,
    Armed,
    Detected,
    Listening,
    Transcribing,
    Cooldown,
    MicrophoneUnavailable,
    SttUnavailable,
    WakeWordError,
}

public static class WakeWordUiStateText
{
    public static string For(WakeWordUiState state) => state switch
    {
        WakeWordUiState.Off => "Wake Word Off",
        WakeWordUiState.Starting => "Starting",
        WakeWordUiState.Armed => "Wake Word Armed",
        WakeWordUiState.Detected => "Detected",
        WakeWordUiState.Listening => "Listening",
        WakeWordUiState.Transcribing => "Transcribing",
        WakeWordUiState.Cooldown => "Cooldown",
        WakeWordUiState.MicrophoneUnavailable => "Microphone Unavailable",
        WakeWordUiState.SttUnavailable => "STT Unavailable",
        WakeWordUiState.WakeWordError => "Wake Word Error",
        _ => "Wake Word Error",
    };
}
