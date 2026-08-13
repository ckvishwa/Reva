namespace Reva.Desktop.Services;

public enum VoiceDeviceAvailabilityKind
{
    Ready,
    PermissionDenied,
    NoMicrophoneFound,
    RecordingFailed,
}

public sealed record VoiceDeviceAvailability(
    VoiceDeviceAvailabilityKind Kind,
    string SafeMessage)
{
    public bool IsReady => Kind == VoiceDeviceAvailabilityKind.Ready;

    public static VoiceDeviceAvailability Ready() =>
        new(VoiceDeviceAvailabilityKind.Ready, "Voice Ready");

    public static VoiceDeviceAvailability PermissionDenied() =>
        new(VoiceDeviceAvailabilityKind.PermissionDenied, "Microphone permission denied.");

    public static VoiceDeviceAvailability NoMicrophoneFound() =>
        new(VoiceDeviceAvailabilityKind.NoMicrophoneFound, "No microphone found.");

    public static VoiceDeviceAvailability RecordingFailed() =>
        new(VoiceDeviceAvailabilityKind.RecordingFailed, "Recording failed.");
}

public sealed class VoiceCaptureException : Exception
{
    public VoiceCaptureException(VoiceDeviceAvailability availability, Exception? innerException = null)
        : base(availability.SafeMessage, innerException)
    {
        Availability = availability;
    }

    public VoiceDeviceAvailability Availability { get; }
}
