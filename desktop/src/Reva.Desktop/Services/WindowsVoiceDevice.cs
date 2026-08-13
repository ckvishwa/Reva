using Windows.Devices.Enumeration;
using Windows.Media.Capture;
using Windows.Media.Core;
using Windows.Media.Devices;
using Windows.Media.MediaProperties;
using Windows.Media.Playback;
using Windows.Storage;
using Windows.Storage.Streams;

namespace Reva.Desktop.Services;

public sealed class WindowsVoiceDevice : IVoiceDevice, IDisposable
{
    private MediaCapture? _capture;
    private LowLagMediaRecording? _recording;
    private string? _recordingPath;
    private readonly MediaPlayer _player = new();
    private InMemoryRandomAccessStream? _playbackStream;
    private bool _microphoneReady;

    public bool IsAvailable => _microphoneReady;

    public async Task<VoiceDeviceAvailability> VerifyAvailabilityAsync(
        CancellationToken cancellationToken = default)
    {
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            var settings = await BuildAudioOnlySettingsAsync(cancellationToken);
            using var probe = new MediaCapture();
            await probe.InitializeAsync(settings);
            _microphoneReady = true;
            return VoiceDeviceAvailability.Ready();
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (VoiceCaptureException ex)
        {
            _microphoneReady = false;
            return ex.Availability;
        }
        catch (UnauthorizedAccessException)
        {
            _microphoneReady = false;
            return VoiceDeviceAvailability.PermissionDenied();
        }
        catch (Exception)
        {
            _microphoneReady = false;
            return VoiceDeviceAvailability.RecordingFailed();
        }
    }

    public async Task StartRecordingAsync(CancellationToken cancellationToken = default)
    {
        if (_recording is not null)
        {
            return;
        }

        try
        {
            StopPlayback();
            var availability = _microphoneReady
                ? VoiceDeviceAvailability.Ready()
                : await VerifyAvailabilityAsync(cancellationToken);
            if (!availability.IsReady)
            {
                throw new VoiceCaptureException(availability);
            }

            _recordingPath = Path.Combine(
                Path.GetTempPath(),
                $"reva-desktop-voice-{Guid.NewGuid():N}.wav");
            await File.WriteAllBytesAsync(_recordingPath, Array.Empty<byte>(), cancellationToken);

            _capture = new MediaCapture();
            await _capture.InitializeAsync(await BuildAudioOnlySettingsAsync(cancellationToken));

            var file = await StorageFile.GetFileFromPathAsync(_recordingPath);
            var profile = MediaEncodingProfile.CreateWav(AudioEncodingQuality.High);
            _recording = await _capture.PrepareLowLagRecordToStorageFileAsync(profile, file);
            await _recording.StartAsync();
        }
        catch (OperationCanceledException)
        {
            CancelRecording();
            throw;
        }
        catch (UnauthorizedAccessException ex)
        {
            CancelRecording();
            _microphoneReady = false;
            throw new VoiceCaptureException(VoiceDeviceAvailability.PermissionDenied(), ex);
        }
        catch (VoiceCaptureException)
        {
            CancelRecording();
            throw;
        }
        catch (Exception ex)
        {
            CancelRecording();
            _microphoneReady = false;
            throw new VoiceCaptureException(VoiceDeviceAvailability.RecordingFailed(), ex);
        }
    }

    public async Task<byte[]> StopRecordingAsync(CancellationToken cancellationToken = default)
    {
        var path = _recordingPath;
        try
        {
            if (_recording is null || path is null)
            {
                return Array.Empty<byte>();
            }

            await _recording.StopAsync();
            await _recording.FinishAsync();
            _recording = null;
            _capture?.Dispose();
            _capture = null;
            return await File.ReadAllBytesAsync(path, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _recordingPath = null;
            DeleteIfExists(path);
        }
    }

    public async Task PlayAsync(byte[] wavAudio, CancellationToken cancellationToken = default)
    {
        StopPlayback();

        _playbackStream = new InMemoryRandomAccessStream();
        var writer = new DataWriter(_playbackStream);
        writer.WriteBytes(wavAudio);
        await writer.StoreAsync();
        await writer.FlushAsync();
        writer.DetachStream();
        writer.Dispose();
        _playbackStream.Seek(0);

        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void OnEnded(MediaPlayer sender, object args) => completion.TrySetResult();

        _player.MediaEnded += OnEnded;
        using var registration = cancellationToken.Register(() =>
        {
            StopPlayback();
            completion.TrySetCanceled(cancellationToken);
        });

        _player.Source = MediaSource.CreateFromStream(_playbackStream, "audio/wav");
        _player.Play();
        try
        {
            await completion.Task.ConfigureAwait(false);
        }
        finally
        {
            _player.MediaEnded -= OnEnded;
        }
    }

    public void StopPlayback()
    {
        _player.Pause();
        _player.Source = null;
        _playbackStream?.Dispose();
        _playbackStream = null;
    }

    public void CancelRecording()
    {
        _recording = null;
        _capture?.Dispose();
        _capture = null;
        DeleteIfExists(_recordingPath);
        _recordingPath = null;
    }

    public void Dispose()
    {
        CancelRecording();
        StopPlayback();
        _player.Dispose();
    }

    private static void DeleteIfExists(string? path)
    {
        if (path is null)
        {
            return;
        }

        try
        {
            File.Delete(path);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private static async Task<MediaCaptureInitializationSettings> BuildAudioOnlySettingsAsync(
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var devices = await DeviceInformation.FindAllAsync(DeviceClass.AudioCapture);
        if (devices.Count == 0)
        {
            throw new VoiceCaptureException(VoiceDeviceAvailability.NoMicrophoneFound());
        }

        var defaultId = MediaDevice.GetDefaultAudioCaptureId(AudioDeviceRole.Communications);
        var selectedDeviceId = string.IsNullOrWhiteSpace(defaultId) ? devices[0].Id : defaultId;
        return new MediaCaptureInitializationSettings
        {
            StreamingCaptureMode = StreamingCaptureMode.Audio,
            AudioDeviceId = selectedDeviceId,
        };
    }
}
