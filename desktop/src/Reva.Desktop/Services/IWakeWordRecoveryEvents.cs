using Microsoft.Win32;
using Windows.Devices.Enumeration;

namespace Reva.Desktop.Services;

public enum WakeWordRecoveryReason
{
    AudioDeviceChanged,
    PowerResume,
    DetectorException,
}

public interface IWakeWordRecoveryEvents : IDisposable
{
    event EventHandler<WakeWordRecoveryReason>? RecoveryRequested;

    void Start();

    void Stop();
}

public sealed class WindowsWakeWordRecoveryEvents : IWakeWordRecoveryEvents
{
    private DeviceWatcher? _watcher;
    private bool _isStarted;

    public event EventHandler<WakeWordRecoveryReason>? RecoveryRequested;

    public void Start()
    {
        if (_isStarted)
        {
            return;
        }

        _isStarted = true;
        SystemEvents.PowerModeChanged += OnPowerModeChanged;
        _watcher = DeviceInformation.CreateWatcher(DeviceClass.AudioCapture);
        _watcher.Added += OnAudioDeviceChanged;
        _watcher.Removed += OnAudioDeviceChanged;
        _watcher.Updated += OnAudioDeviceUpdated;
        _watcher.Start();
    }

    public void Stop()
    {
        if (!_isStarted)
        {
            return;
        }

        _isStarted = false;
        SystemEvents.PowerModeChanged -= OnPowerModeChanged;
        if (_watcher is not null)
        {
            _watcher.Added -= OnAudioDeviceChanged;
            _watcher.Removed -= OnAudioDeviceChanged;
            _watcher.Updated -= OnAudioDeviceUpdated;
            if (_watcher.Status is DeviceWatcherStatus.Started or DeviceWatcherStatus.EnumerationCompleted)
            {
                _watcher.Stop();
            }

            _watcher = null;
        }
    }

    public void Dispose() => Stop();

    private void OnPowerModeChanged(object sender, PowerModeChangedEventArgs e)
    {
        if (e.Mode == PowerModes.Resume)
        {
            RecoveryRequested?.Invoke(this, WakeWordRecoveryReason.PowerResume);
        }
    }

    private void OnAudioDeviceChanged(DeviceWatcher sender, DeviceInformation args) =>
        RecoveryRequested?.Invoke(this, WakeWordRecoveryReason.AudioDeviceChanged);

    private void OnAudioDeviceChanged(DeviceWatcher sender, DeviceInformationUpdate args) =>
        RecoveryRequested?.Invoke(this, WakeWordRecoveryReason.AudioDeviceChanged);

    private void OnAudioDeviceUpdated(DeviceWatcher sender, DeviceInformationUpdate args) =>
        RecoveryRequested?.Invoke(this, WakeWordRecoveryReason.AudioDeviceChanged);
}
