namespace Reva.Desktop.Services;

public sealed class Endpointer
{
    private readonly int _sampleRate;
    private readonly TimeSpan _trailingSilence;
    private readonly TimeSpan _maxCapture;
    private readonly double _speechThreshold;
    private int _totalSamples;
    private int _silenceSamplesAfterSpeech;
    private bool _heardSpeech;

    public Endpointer(
        int sampleRate,
        TimeSpan? trailingSilence = null,
        TimeSpan? maxCapture = null,
        double speechThreshold = 900)
    {
        _sampleRate = sampleRate;
        _trailingSilence = trailingSilence ?? TimeSpan.FromMilliseconds(700);
        _maxCapture = maxCapture ?? TimeSpan.FromSeconds(8);
        _speechThreshold = speechThreshold;
    }

    public bool ShouldStop(IReadOnlyList<short> frame)
    {
        _totalSamples += frame.Count;
        var rms = RootMeanSquare(frame);
        if (rms >= _speechThreshold)
        {
            _heardSpeech = true;
            _silenceSamplesAfterSpeech = 0;
        }
        else if (_heardSpeech)
        {
            _silenceSamplesAfterSpeech += frame.Count;
        }

        return Elapsed(_totalSamples) >= _maxCapture
            || (_heardSpeech && Elapsed(_silenceSamplesAfterSpeech) >= _trailingSilence);
    }

    private TimeSpan Elapsed(int samples) => TimeSpan.FromSeconds(samples / (double)_sampleRate);

    private static double RootMeanSquare(IReadOnlyList<short> frame)
    {
        if (frame.Count == 0)
        {
            return 0;
        }

        double sum = 0;
        foreach (var sample in frame)
        {
            sum += sample * sample;
        }

        return Math.Sqrt(sum / frame.Count);
    }
}
