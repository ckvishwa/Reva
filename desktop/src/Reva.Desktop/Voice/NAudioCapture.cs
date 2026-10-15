using System.Runtime.InteropServices;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace Reva.Desktop.Voice;

/// <summary>
/// Microphone capture on WASAPI shared mode (NAudio, MIT; see docs/licenses/THIRD_PARTY.md).
/// <see cref="IsOpen"/> is true only between a successful start and the moment the device stops,
/// so "listening" in the UI cannot outlive the real microphone.
/// </summary>
public sealed class NAudioCapture : IAudioCapture
{
    private const int AccessDenied = unchecked((int)0x80070005);
    private const int NotFound = unchecked((int)0x80070490);

    private readonly object _lock = new();
    private readonly MMDeviceEnumerator _enumerator = new();
    private WasapiCapture? _capture;
    private PcmConverter? _converter;
    private volatile bool _open;
    private bool _stopping;

    public event Action<byte[]>? Frame;

    public event Action? Lost;

    public bool IsOpen => _open;

    public IReadOnlyList<AudioDeviceInfo> ListDevices()
    {
        try
        {
            string? defaultId = null;
            try
            {
                defaultId = _enumerator.GetDefaultAudioEndpoint(DataFlow.Capture, Role.Console).ID;
            }
            catch (COMException)
            {
                // no default capture device
            }

            return _enumerator
                .EnumerateAudioEndPoints(DataFlow.Capture, DeviceState.Active)
                .Select(d => new AudioDeviceInfo(d.ID, d.FriendlyName, d.ID == defaultId))
                .ToList();
        }
        catch (COMException)
        {
            return Array.Empty<AudioDeviceInfo>();
        }
    }

    public void Start(string? deviceId)
    {
        lock (_lock)
        {
            if (_open)
            {
                return;
            }

            WasapiCapture? capture = null;
            try
            {
                var device = deviceId is null
                    ? _enumerator.GetDefaultAudioEndpoint(DataFlow.Capture, Role.Console)
                    : _enumerator.GetDevice(deviceId);
                capture = new WasapiCapture(device, true, 40);
                _converter = new PcmConverter(capture.WaveFormat);
                _stopping = false;
                capture.DataAvailable += OnData;
                capture.RecordingStopped += OnStopped;
                capture.StartRecording();
                _capture = capture;
                _open = true;
            }
            catch (COMException ex) when (ex.HResult == NotFound)
            {
                Discard(capture);
                throw new CaptureStartException(CaptureFailure.NoDevice, ex);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException
                || (ex is COMException com && com.HResult == AccessDenied))
            {
                Discard(capture);
                throw new CaptureStartException(CaptureFailure.PermissionDenied, ex);
            }
            catch (Exception ex) when (ex is COMException or ArgumentException or InvalidOperationException)
            {
                Discard(capture);
                throw new CaptureStartException(
                    ex.Message.Contains("No such device", StringComparison.OrdinalIgnoreCase)
                        || ex.Message.Contains("Element not found", StringComparison.OrdinalIgnoreCase)
                        ? CaptureFailure.NoDevice
                        : CaptureFailure.Failed,
                    ex);
            }
        }
    }

    public void Stop()
    {
        WasapiCapture? capture;
        lock (_lock)
        {
            capture = _capture;
            _capture = null;
            _stopping = true;
            _open = false;
        }

        Discard(capture);
    }

    private void OnData(object? sender, WaveInEventArgs e)
    {
        var converter = _converter;
        if (converter is null || e.BytesRecorded == 0)
        {
            return;
        }

        var pcm = converter.Convert(e.Buffer, e.BytesRecorded);
        if (pcm.Length > 0)
        {
            Frame?.Invoke(pcm);
        }
    }

    private void OnStopped(object? sender, StoppedEventArgs e)
    {
        bool unexpected;
        lock (_lock)
        {
            unexpected = !_stopping && ReferenceEquals(sender, _capture);
            if (unexpected)
            {
                _open = false;
                _capture = null;
            }
        }

        if (unexpected)
        {
            (sender as IDisposable)?.Dispose();
            Lost?.Invoke(); // unplugged, disabled, or access revoked while recording
        }
    }

    private void Discard(WasapiCapture? capture)
    {
        if (capture is null)
        {
            return;
        }

        try
        {
            capture.DataAvailable -= OnData;
            capture.RecordingStopped -= OnStopped;
            capture.StopRecording();
        }
        catch (Exception)
        {
            // already stopped or the device is gone
        }
        finally
        {
            capture.Dispose();
        }
    }

    public void Dispose()
    {
        Stop();
        _enumerator.Dispose();
    }
}
