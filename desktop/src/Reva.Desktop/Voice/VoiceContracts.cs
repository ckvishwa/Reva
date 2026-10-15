using System.Text.Json;

namespace Reva.Desktop.Voice;

public sealed record AudioDeviceInfo(string Id, string Name, bool IsDefault);

public enum CaptureFailure
{
    NoDevice,
    PermissionDenied,
    Failed,
}

public sealed class CaptureStartException : Exception
{
    public CaptureStartException(CaptureFailure failure, Exception? inner = null)
        : base(failure.ToString(), inner)
    {
        Failure = failure;
    }

    public CaptureFailure Failure { get; }
}

/// <summary>Microphone capture. Frames are 16 kHz mono 16-bit little-endian PCM.</summary>
public interface IAudioCapture : IDisposable
{
    /// <summary>True only while the device is really delivering audio.</summary>
    bool IsOpen { get; }

    IReadOnlyList<AudioDeviceInfo> ListDevices();

    /// <summary>Raised on a capture thread with each converted chunk.</summary>
    event Action<byte[]>? Frame;

    /// <summary>The device stopped by itself: unplugged, disabled, or revoked.</summary>
    event Action? Lost;

    /// <summary>Starts the device; null picks the default. Throws <see cref="CaptureStartException"/>.</summary>
    void Start(string? deviceId);

    void Stop();
}

/// <summary>Loudness of the audio being played, one window (~16 ms) at a time, stamped with the epoch of the reply.</summary>
public readonly record struct PlaybackLevel(int Epoch, int PositionMs, double Rms);

/// <summary>Plays one reply at a time and can cut it off at once.</summary>
public interface IAudioPlayback : IDisposable
{
    /// <summary>Raised on the audio thread as the device pulls audio. Subscribers must return quickly.</summary>
    event Action<PlaybackLevel>? Level;

    bool IsPlaying { get; }

    /// <summary>Raised with the <c>turnEpoch</c> given to <see cref="Play"/> when it played to the end.</summary>
    event Action<int>? Finished;

    void Play(byte[] wav, int turnEpoch);

    /// <summary>Stops immediately and discards what is queued. Does not raise <see cref="Finished"/>.</summary>
    void Flush();
}

/// <summary>One event from the session socket.</summary>
public sealed record VoiceEvent(string Kind, int TurnEpoch, JsonElement Payload)
{
    public string? Text(string name) =>
        Payload.ValueKind == JsonValueKind.Object
        && Payload.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
}

public interface IVoiceSessionClient : IAsyncDisposable
{
    bool IsConnected { get; }

    event Action<VoiceEvent>? EventReceived;

    /// <summary>The socket closed or failed; the argument is a safe, fixed reason.</summary>
    event Action<string>? Disconnected;

    /// <summary>Creates a session on Core and opens its event socket.</summary>
    Task<string?> ConnectAsync(CancellationToken cancellationToken = default);

    Task SendControlAsync(string type, int? turnEpoch = null, CancellationToken cancellationToken = default);

    Task SendAudioAsync(byte[] pcm, CancellationToken cancellationToken = default);

    /// <summary>Downloads a reply (a WAV) from the path in a <c>tts.started</c> event.</summary>
    Task<byte[]?> FetchAudioAsync(string path, CancellationToken cancellationToken = default);

    Task CloseAsync();
}

/// <summary>Source of the push-to-talk gesture (a button or the global hotkey).</summary>
public interface IPushToTalkSource : IDisposable
{
    event Action? Pressed;

    event Action? Released;

    /// <summary>Starts listening for the gesture. Safe to call twice.</summary>
    void Enable();

    void Disable();
}

public static class VoiceControl
{
    public const string CaptureRequested = "capture.requested";
    public const string CaptureOpen = "capture.open";
    public const string CaptureDenied = "capture.denied";
    public const string CaptureLost = "capture.lost";
    public const string PttDown = "ptt.down";
    public const string PttUp = "ptt.up";
    public const string PttCancel = "ptt.cancel";
    public const string MicMute = "mic.mute";
    public const string MicUnmute = "mic.unmute";
    public const string PlaybackFinished = "playback.finished";
    public const string Interrupt = "interrupt";
    public const string Cancel = "cancel";
}
