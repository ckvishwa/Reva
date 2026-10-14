using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class VoiceDeviceAvailabilityTests
{
    [Fact]
    public void PermissionDenied_HasRequiredSafeMessage()
    {
        var availability = VoiceDeviceAvailability.PermissionDenied();

        Assert.Equal(
            "Microphone permission is disabled. Enable it in Windows Settings.",
            availability.SafeMessage);
        Assert.Equal(VoiceDeviceAvailabilityKind.PermissionDenied, availability.Kind);
        Assert.False(availability.IsReady);
    }
}
