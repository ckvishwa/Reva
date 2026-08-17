using Pv;

namespace Reva.Desktop.Services;

public sealed class PorcupineWakeWordDetector : IWakeWordDetector
{
    private readonly string _accessKey;
    private readonly string _keywordDirectory;
    private readonly IFileSystemProbe _fileSystem;
    private readonly object _gate = new();
    private Porcupine? _porcupine;
    private PvRecorder? _recorder;
    private CancellationTokenSource? _loopCancellation;
    private Task? _loopTask;
    private IReadOnlyList<WakePhrase> _phraseOrder = Array.Empty<WakePhrase>();

    public PorcupineWakeWordDetector(
        string accessKey,
        string keywordDirectory,
        IFileSystemProbe fileSystem)
    {
        _accessKey = accessKey;
        _keywordDirectory = keywordDirectory;
        _fileSystem = fileSystem;
    }

    public bool IsRunning { get; private set; }

    public event EventHandler<WakeWordDetection>? Detected;

    public Task StartAsync(
        WakeWordConfiguration configuration,
        IMicrophoneLease lease,
        CancellationToken cancellationToken = default)
    {
        if (IsRunning)
        {
            return Task.CompletedTask;
        }

        if (string.IsNullOrWhiteSpace(_accessKey))
        {
            throw new WakeWordConfigurationException("Wake word requires a configured access key.");
        }

        var resolution = WakeWordKeywordResolver.Resolve(configuration.Phrases, _keywordDirectory, _fileSystem);
        if (!resolution.IsSuccess)
        {
            var message = resolution.MissingPhrase is { } missing
                ? $"Missing keyword file for {WakePhraseDefaults.DisplayName(missing)}."
                : "No wake phrases are enabled.";
            throw new WakeWordConfigurationException(message);
        }

        Porcupine? porcupine = null;
        PvRecorder? recorder = null;
        try
        {
            porcupine = Porcupine.FromKeywordPaths(
                _accessKey,
                resolution.KeywordPaths!,
                sensitivities: resolution.Sensitivities!);
            if (porcupine.SampleRate != 16000)
            {
                throw new WakeWordConfigurationException("Wake word provider reported an unsupported sample rate.");
            }

            recorder = PvRecorder.Create(frameLength: porcupine.FrameLength);
            recorder.Start();
        }
        catch
        {
            recorder?.Dispose();
            porcupine?.Dispose();
            throw;
        }

        var loopCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

        lock (_gate)
        {
            _porcupine = porcupine;
            _recorder = recorder;
            _loopCancellation = loopCancellation;
            _phraseOrder = resolution.PhraseOrder!;
            IsRunning = true;
            _loopTask = Task.Run(() => ListenLoopAsync(porcupine, recorder, _phraseOrder, loopCancellation.Token));
        }

        return Task.CompletedTask;
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        Task? loopTask;
        CancellationTokenSource? loopCancellation;
        PvRecorder? recorder;
        Porcupine? porcupine;

        lock (_gate)
        {
            loopTask = _loopTask;
            loopCancellation = _loopCancellation;
            recorder = _recorder;
            porcupine = _porcupine;
            _loopTask = null;
            _loopCancellation = null;
            _recorder = null;
            _porcupine = null;
            _phraseOrder = Array.Empty<WakePhrase>();
            IsRunning = false;
        }

        loopCancellation?.Cancel();
        if (recorder is not null && recorder.IsRecording)
        {
            try
            {
                recorder.Stop();
            }
            catch
            {
            }
        }

        if (loopTask is not null)
        {
            try
            {
                await loopTask.WaitAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }

        recorder?.Dispose();
        porcupine?.Dispose();
        loopCancellation?.Dispose();
    }

    private async Task ListenLoopAsync(
        Porcupine porcupine,
        PvRecorder recorder,
        IReadOnlyList<WakePhrase> phraseOrder,
        CancellationToken cancellationToken)
    {
        try
        {
            await Task.Yield();
            while (!cancellationToken.IsCancellationRequested)
            {
                var keywordIndex = porcupine.Process(recorder.Read());
                if (keywordIndex >= 0 && keywordIndex < phraseOrder.Count)
                {
                    Detected?.Invoke(
                        this,
                        new WakeWordDetection(phraseOrder[keywordIndex], DateTimeOffset.UtcNow));
                }
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception)
        {
            DesktopLogger.Info("wakeword.detector.stopped reason=provider_error");
            IsRunning = false;
        }
    }

    public async ValueTask DisposeAsync() => await StopAsync().ConfigureAwait(false);
}

public sealed class WakeWordConfigurationException : Exception
{
    public WakeWordConfigurationException(string message)
        : base(message)
    {
    }
}
