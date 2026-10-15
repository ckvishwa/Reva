using Reva.Desktop.Services;

namespace Reva.Desktop.Voice;

/// <summary>
/// Makes sure only one producer holds the microphone at a time (AR-VA-003): the wake word, the
/// older hold-to-talk button and this live voice path share one arbiter. The lease is taken before
/// the device starts and released when it stops or is lost. Optional hooks let the wake-word
/// detector step aside while the user is talking and resume afterwards.
/// </summary>
public sealed class ArbitratedAudioCapture : IAudioCapture
{
    private readonly IAudioCapture _inner;
    private readonly IMicrophoneArbiter _arbiter;
    private readonly Func<Task>? _before;
    private readonly Func<Task>? _after;
    private IMicrophoneLease? _lease;

    public ArbitratedAudioCapture(
        IAudioCapture inner,
        IMicrophoneArbiter arbiter,
        Func<Task>? beforeStart = null,
        Func<Task>? afterStop = null)
    {
        _inner = inner;
        _arbiter = arbiter;
        _before = beforeStart;
        _after = afterStop;
        _inner.Frame += pcm => Frame?.Invoke(pcm);
        _inner.Lost += () =>
        {
            Release();
            Lost?.Invoke();
        };
    }

    public event Action<byte[]>? Frame;

    public event Action? Lost;

    public bool IsOpen => _inner.IsOpen;

    public IReadOnlyList<AudioDeviceInfo> ListDevices() => _inner.ListDevices();

    public void Start(string? deviceId)
    {
        if (_lease is not null)
        {
            return;
        }

        _before?.Invoke().GetAwaiter().GetResult();
        _lease = _arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk).GetAwaiter().GetResult();
        if (_lease is null)
        {
            ResumeOthers();
            throw new CaptureStartException(CaptureFailure.Failed); // another feature holds the mic
        }

        try
        {
            _inner.Start(deviceId);
        }
        catch
        {
            Release();
            throw;
        }
    }

    public void Stop()
    {
        _inner.Stop();
        Release();
    }

    public void Dispose()
    {
        Stop();
        _inner.Dispose();
    }

    private void Release()
    {
        var lease = Interlocked.Exchange(ref _lease, null);
        if (lease is null)
        {
            return;
        }

        lease.DisposeAsync().AsTask().GetAwaiter().GetResult();
        ResumeOthers();
    }

    private void ResumeOthers()
    {
        if (_after is not null)
        {
            _ = Task.Run(_after);
        }
    }
}
