namespace Reva.Desktop.Services;

public sealed class PorcupineWakeWordDetector : IWakeWordDetector
{
    private readonly string _accessKey;
    private readonly string _keywordDirectory;
    private readonly IFileSystemProbe _fileSystem;
    private readonly WakeWordModelManifest _modelManifest;
    private readonly IWakeWordEngineFactory _engineFactory;
    private readonly IWakeFrameRecorderFactory _recorderFactory;
    private readonly object _gate = new();
    private IWakeWordEngine? _porcupine;
    private IWakeFrameRecorder? _recorder;
    private CancellationTokenSource? _loopCancellation;
    private Task? _loopTask;
    private IReadOnlyList<WakePhrase> _phraseOrder = Array.Empty<WakePhrase>();

    public PorcupineWakeWordDetector(
        string accessKey,
        string keywordDirectory,
        IFileSystemProbe fileSystem,
        WakeWordModelManifest? modelManifest = null)
        : this(
            accessKey,
            keywordDirectory,
            fileSystem,
            modelManifest,
            new PorcupineEngineFactory(),
            new PvRecorderFrameRecorderFactory())
    {
    }

    internal PorcupineWakeWordDetector(
        string accessKey,
        string keywordDirectory,
        IFileSystemProbe fileSystem,
        WakeWordModelManifest? modelManifest,
        IWakeWordEngineFactory engineFactory,
        IWakeFrameRecorderFactory recorderFactory)
    {
        _accessKey = accessKey;
        _keywordDirectory = keywordDirectory;
        _fileSystem = fileSystem;
        _modelManifest = modelManifest ?? WakeWordModelManifest.Empty;
        _engineFactory = engineFactory;
        _recorderFactory = recorderFactory;
    }

    public bool IsRunning { get; private set; }

    public event EventHandler<WakeWordDetection>? Detected;

    public event EventHandler<WakeWordFailure>? Faulted;

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

        var resolution = WakeWordKeywordResolver.Resolve(
            configuration.Phrases,
            _keywordDirectory,
            _fileSystem,
            _modelManifest);
        if (!resolution.IsSuccess)
        {
            var message = resolution.Failure switch
            {
                KeywordResolutionFailure.HashMismatch => "Wake word keyword file failed integrity verification.",
                KeywordResolutionFailure.UnsupportedArchitecture => "Wake word keyword files do not match this Windows architecture.",
                KeywordResolutionFailure.MissingExpectedHash => "Wake word keyword file is not registered in local settings.",
                KeywordResolutionFailure.MissingFile when resolution.MissingPhrase is { } missing =>
                    $"Missing keyword file for {WakePhraseDefaults.DisplayName(missing)}.",
                _ => "No wake phrases are enabled.",
            };
            throw new WakeWordConfigurationException(message);
        }

        IWakeWordEngine? porcupine = null;
        IWakeFrameRecorder? recorder = null;
        try
        {
            porcupine = _engineFactory.Create(
                _accessKey,
                resolution.KeywordPaths!,
                resolution.Sensitivities!);
            if (porcupine.SampleRate != 16000)
            {
                throw new WakeWordConfigurationException("Wake word provider reported an unsupported sample rate.");
            }

            recorder = _recorderFactory.Create(porcupine.FrameLength);
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
        IWakeFrameRecorder? recorder;
        IWakeWordEngine? porcupine;

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
        IWakeWordEngine porcupine,
        IWakeFrameRecorder recorder,
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
        catch (Exception) when (!cancellationToken.IsCancellationRequested)
        {
            DesktopLogger.Info("wakeword.detector.stopped reason=provider_error");
            IsRunning = false;
            Faulted?.Invoke(this, new WakeWordFailure(WakeWordFailureKind.DetectorException));
        }
        catch (Exception)
        {
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
