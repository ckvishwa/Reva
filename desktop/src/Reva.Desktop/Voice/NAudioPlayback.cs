using NAudio.CoreAudioApi;
using NAudio.Wave;
using NAudio.Wave.SampleProviders;

namespace Reva.Desktop.Voice;

/// <summary>
/// Plays one reply WAV at a time on the default output (WASAPI shared). <see cref="Flush"/> cuts
/// the sound at once and guarantees <see cref="Finished"/> is not raised for the cut-off reply.
/// </summary>
public sealed class NAudioPlayback : IAudioPlayback
{
    private readonly object _lock = new();
    private Instance? _current;

    public event Action<int>? Finished;

    public event Action<PlaybackLevel>? Level;

    public bool IsPlaying
    {
        get
        {
            lock (_lock)
            {
                return _current is { Cancelled: false };
            }
        }
    }

    public void Play(byte[] wav, int turnEpoch)
    {
        Flush();
        var reader = new WaveFileReader(new MemoryStream(wav, writable: false));
        var output = new WasapiOut(AudioClientShareMode.Shared, 50);
        var instance = new Instance(output, reader, turnEpoch);
        try
        {
            var metered = new MeteringSampleProvider(
                reader.ToSampleProvider(),
                (positionMs, rms) =>
                {
                    if (!instance.Cancelled)
                    {
                        Level?.Invoke(new PlaybackLevel(turnEpoch, positionMs, rms));
                    }
                });
            output.Init(new SampleToWaveProvider(metered));
            output.PlaybackStopped += (_, _) => OnStopped(instance);
            lock (_lock)
            {
                _current = instance;
            }

            output.Play();
        }
        catch
        {
            instance.Cancelled = true;
            instance.Dispose();
            throw;
        }
    }

    public void Flush()
    {
        Instance? instance;
        lock (_lock)
        {
            instance = _current;
            _current = null;
        }

        if (instance is null)
        {
            return;
        }

        instance.Cancelled = true; // set before Stop so its PlaybackStopped stays silent
        try
        {
            instance.Output.Stop();
        }
        catch (Exception)
        {
            // already stopped
        }

        instance.Dispose();
    }

    private void OnStopped(Instance instance)
    {
        var finished = false;
        lock (_lock)
        {
            if (!instance.Cancelled && ReferenceEquals(_current, instance))
            {
                _current = null;
                finished = true;
            }
        }

        var epoch = instance.Epoch;
        instance.Dispose();
        if (finished)
        {
            Finished?.Invoke(epoch);
        }
    }

    public void Dispose() => Flush();

    private sealed class Instance : IDisposable
    {
        private int _disposed;

        public Instance(WasapiOut output, WaveStream reader, int epoch)
        {
            Output = output;
            Reader = reader;
            Epoch = epoch;
        }

        public WasapiOut Output { get; }

        public WaveStream Reader { get; }

        public int Epoch { get; }

        public volatile bool Cancelled;

        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed, 1) == 0)
            {
                Output.Dispose();
                Reader.Dispose();
            }
        }
    }
}
