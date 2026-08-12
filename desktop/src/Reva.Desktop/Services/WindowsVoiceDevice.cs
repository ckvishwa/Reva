using Windows.Media.Capture;
using Windows.Media.Core;
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

    public bool IsAvailable => true;

    public async Task StartRecordingAsync(CancellationToken cancellationToken = default)
    {
        if (_recording is not null)
        {
            return;
        }

        StopPlayback();
        _recordingPath = Path.Combine(Path.GetTempPath(), $"reva-desktop-voice-{Guid.NewGuid():N}.wav");
        await File.WriteAllBytesAsync(_recordingPath, Array.Empty<byte>(), cancellationToken)
            .ConfigureAwait(false);

        _capture = new MediaCapture();
        await _capture.InitializeAsync(new MediaCaptureInitializationSettings
        {
            StreamingCaptureMode = StreamingCaptureMode.Audio,
        });

        var file = await StorageFile.GetFileFromPathAsync(_recordingPath);
        var profile = MediaEncodingProfile.CreateWav(AudioEncodingQuality.High);
        _recording = await _capture.PrepareLowLagRecordToStorageFileAsync(profile, file);
        await _recording.StartAsync();
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
}
