namespace Reva.Desktop.State;

public enum VoiceUiState
{
    CheckingMicrophone,
    ReadyToTalk,
    Listening,
    Transcribing,
    TranscriptionReady,
    PermissionDenied,
    NoMicrophone,
    SttUnavailable,
    TranscriptionFailed,
}

public static class VoiceUiStateText
{
    public static string For(VoiceUiState state) => state switch
    {
        VoiceUiState.CheckingMicrophone => "Checking Microphone",
        VoiceUiState.ReadyToTalk => "Ready to Talk",
        VoiceUiState.Listening => "Listening",
        VoiceUiState.Transcribing => "Transcribing",
        VoiceUiState.TranscriptionReady => "Transcription Ready",
        VoiceUiState.PermissionDenied => "Permission Denied",
        VoiceUiState.NoMicrophone => "No Microphone",
        VoiceUiState.SttUnavailable => "STT Unavailable",
        VoiceUiState.TranscriptionFailed => "Transcription Failed",
        _ => throw new ArgumentOutOfRangeException(nameof(state)),
    };
}
