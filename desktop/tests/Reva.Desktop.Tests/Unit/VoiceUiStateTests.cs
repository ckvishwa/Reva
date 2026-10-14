using Reva.Desktop.State;

namespace Reva.Desktop.Tests.Unit;

public class VoiceUiStateTests
{
    [Theory]
    [InlineData(VoiceUiState.CheckingMicrophone, "Checking Microphone")]
    [InlineData(VoiceUiState.ReadyToTalk, "Ready to Talk")]
    [InlineData(VoiceUiState.Listening, "Listening")]
    [InlineData(VoiceUiState.Transcribing, "Transcribing")]
    [InlineData(VoiceUiState.TranscriptionReady, "Transcription Ready")]
    [InlineData(VoiceUiState.PermissionDenied, "Permission Denied")]
    [InlineData(VoiceUiState.NoMicrophone, "No Microphone")]
    [InlineData(VoiceUiState.SttUnavailable, "STT Unavailable")]
    [InlineData(VoiceUiState.TranscriptionFailed, "Transcription Failed")]
    public void For_ReturnsExactRequiredText(VoiceUiState state, string expected)
    {
        Assert.Equal(expected, VoiceUiStateText.For(state));
    }

    [Fact]
    public void For_CoversEveryEnumMember()
    {
        // Guards against a future state being added without its required string.
        foreach (VoiceUiState state in Enum.GetValues<VoiceUiState>())
        {
            Assert.False(string.IsNullOrWhiteSpace(VoiceUiStateText.For(state)));
        }
    }
}
