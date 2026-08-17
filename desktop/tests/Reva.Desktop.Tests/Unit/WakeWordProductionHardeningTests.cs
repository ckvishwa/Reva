using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;
using Reva.Desktop.Contracts;
using Reva.Desktop.Services;
using Reva.Desktop.State;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class WakeWordProductionHardeningTests
{
    [Fact]
    public void DesktopProject_PinsExactWakeProviderVersions_AndEnablesLockFileRestore()
    {
        var projectPath = Path.Combine(FindRepoRoot(), "desktop", "src", "Reva.Desktop", "Reva.Desktop.csproj");
        var project = XDocument.Load(projectPath);

        Assert.Equal("true", project.Descendants("RestorePackagesWithLockFile").Single().Value);
        AssertPackageVersion(project, "Porcupine", "4.0.2");
        AssertPackageVersion(project, "PvRecorder", "1.2.13");
        Assert.DoesNotContain(project.Descendants("PackageReference"), reference =>
        {
            var version = (string?)reference.Attribute("Version") ?? string.Empty;
            return version.Contains('*') || version.Contains('-');
        });
    }

    [Fact]
    public void PackageLockFile_RecordsExactWakeProviderVersions()
    {
        var lockPath = Path.Combine(FindRepoRoot(), "desktop", "src", "Reva.Desktop", "packages.lock.json");
        using var document = JsonDocument.Parse(File.ReadAllText(lockPath));
        var dependencies = document.RootElement.GetProperty("dependencies");
        var target = dependencies.EnumerateObject().Single().Value;

        Assert.Equal("4.0.2", target.GetProperty("Porcupine").GetProperty("resolved").GetString());
        Assert.Equal("1.2.13", target.GetProperty("PvRecorder").GetProperty("resolved").GetString());
    }

    [Fact]
    public void RuntimeOptions_PreferLocalSetting_AndUseSecureStoreForAccessKey()
    {
        var store = new FakeWakeWordSettingsStore(new WakeWordLocalSettings(
            IsEnabled: true,
            KeywordSetVersion: "2026.08.17",
            ModelHashes: new Dictionary<string, string> { ["hey-reva"] = ExpectedHash }));
        var secrets = new FakeWakeWordSecretStore("stored-key");

        var options = WakeWordRuntimeOptions.Load(
            store,
            secrets,
            _ => null,
            @"C:\Users\me\AppData\Local\Reva");

        Assert.True(options.IsEnabled);
        Assert.Equal("stored-key", options.AccessKey);
        Assert.Equal("2026.08.17", options.ModelManifest.KeywordSetVersion);
        Assert.Equal(ExpectedHash, options.ModelManifest.ExpectedSha256[WakePhrase.HeyReva]);
    }

    [Fact]
    public void RuntimeOptions_EnvironmentVariablesAreDeveloperOverrides()
    {
        var store = new FakeWakeWordSettingsStore(WakeWordLocalSettings.Disabled);
        var secrets = new FakeWakeWordSecretStore("stored-key");
        string? Env(string key) => key switch
        {
            "REVA_WAKE_WORD_ENABLED" => "true",
            "REVA_PICOVOICE_ACCESS_KEY" => "developer-key",
            "REVA_WAKE_WORD_HEY_REVA_SHA256" => ExpectedHash,
            "REVA_WAKE_WORD_KEYWORD_SET_VERSION" => "dev",
            _ => null,
        };

        var options = WakeWordRuntimeOptions.Load(store, secrets, Env, @"C:\Reva");

        Assert.True(options.IsEnabled);
        Assert.Equal("developer-key", options.AccessKey);
        Assert.Equal("dev", options.ModelManifest.KeywordSetVersion);
        Assert.Equal(ExpectedHash, options.ModelManifest.ExpectedSha256[WakePhrase.HeyReva]);
    }

    [Fact]
    public void KeywordResolver_RejectsMissingCorruptAndWrongPlatformModels()
    {
        var phrases = new[] { new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f) };
        var manifest = new WakeWordModelManifest(
            "2026.08.17",
            Architecture: "X64",
            new Dictionary<WakePhrase, string> { [WakePhrase.HeyReva] = ExpectedHash });

        var missing = WakeWordKeywordResolver.Resolve(phrases, @"C:\kw", new FakeFileSystemProbe(), manifest);
        var corrupt = WakeWordKeywordResolver.Resolve(
            phrases,
            @"C:\kw",
            new FakeFileSystemProbe((@"C:\kw\hey-reva.ppn", "not-the-hash")),
            manifest);
        var wrongPlatform = WakeWordKeywordResolver.Resolve(
            phrases,
            @"C:\kw",
            new FakeFileSystemProbe((@"C:\kw\hey-reva.ppn", ExpectedHash)),
            manifest with { Architecture = "Arm64" },
            currentArchitecture: "X64");

        Assert.Equal(KeywordResolutionFailure.MissingFile, missing.Failure);
        Assert.Equal(KeywordResolutionFailure.HashMismatch, corrupt.Failure);
        Assert.Equal(KeywordResolutionFailure.UnsupportedArchitecture, wrongPlatform.Failure);
        Assert.Null(corrupt.KeywordPaths);
    }

    [Fact]
    public void ProviderDiagnostics_RecordPackageVersionsArchitectureAndModelHash_WithoutAccessKey()
    {
        var options = new WakeWordRuntimeOptions(
            true,
            "secret-access-key",
            @"C:\kw",
            new WakeWordConfiguration(WakePhraseDefaults.All),
            new WakeWordModelManifest(
                "2026.08.17",
                "X64",
                new Dictionary<WakePhrase, string> { [WakePhrase.HeyReva] = ExpectedHash }));

        var diagnostics = WakeWordProviderDiagnostics.Create(options, architecture: "X64");
        var text = diagnostics.ToLogString();

        Assert.Contains("porcupine=4.0.2", text);
        Assert.Contains("pvrecorder=1.2.13", text);
        Assert.Contains("arch=X64", text);
        Assert.Contains(ExpectedHash, text);
        Assert.DoesNotContain("secret-access-key", text);
    }

    [Fact]
    public async Task Coordinator_RecoverableStartupFailure_LeavesHoldToTalkAvailable_AndBacksOff()
    {
        var detector = new ScriptedWakeWordDetector(new InvalidOperationException("device path detail"));
        var delays = new List<TimeSpan>();
        var retryGate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var arbiter = new MicrophoneArbiter();
        var coordinator = NewCoordinator(
            detector,
            arbiter,
            delay: (span, _) =>
            {
                delays.Add(span);
                return retryGate.Task;
            });

        await coordinator.EnableAsync(DefaultConfig());
        await using var holdLease = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        Assert.Equal(WakeWordUiState.Recovering, coordinator.State);
        Assert.NotNull(holdLease);
        Assert.Equal(TimeSpan.FromSeconds(1), delays.Single());
        retryGate.SetCanceled();
    }

    [Fact]
    public async Task Coordinator_RecoversAfterMicrophoneDisconnectSleepResumeAndDetectorException()
    {
        var detector = new ScriptedWakeWordDetector(
            new InvalidOperationException("microphone disconnected"),
            null,
            null,
            null);
        var recoveryEvents = new FakeWakeWordRecoveryEvents();
        var coordinator = NewCoordinator(detector, recoveryEvents: recoveryEvents);

        await coordinator.EnableAsync(DefaultConfig());
        await coordinator.WaitForRecoveryAsync();
        recoveryEvents.Raise(WakeWordRecoveryReason.PowerResume);
        await coordinator.WaitForRecoveryAsync();
        recoveryEvents.Raise(WakeWordRecoveryReason.AudioDeviceChanged);
        await coordinator.WaitForRecoveryAsync();
        detector.RaiseFault();
        await coordinator.WaitForRecoveryAsync();

        Assert.Equal(WakeWordUiState.Listening, coordinator.State);
        Assert.True(detector.StartCallCount >= 4);
    }

    [Fact]
    public async Task Coordinator_CoreDisconnectWhileListening_DoesNotRecreateDetector()
    {
        var detector = new ScriptedWakeWordDetector((Exception?)null);
        var lifecycle = new FakeCoreLifecycle();
        var coordinator = NewCoordinator(detector, lifecycle: lifecycle);

        await coordinator.EnableAsync(DefaultConfig());
        lifecycle.State = CoreLifecycleState.Unavailable;
        lifecycle.RaiseStateChanged();

        Assert.Equal(WakeWordUiState.Listening, coordinator.State);
        Assert.Equal(1, detector.StartCallCount);
    }

    [Fact]
    public async Task Coordinator_SttTimeoutThenListeningResumes()
    {
        var client = new FakeCoreClient(transcriptionException: new OperationCanceledException("timeout detail"));
        var detector = new ScriptedWakeWordDetector((Exception?)null);
        var coordinator = NewCoordinator(detector, client: client);

        await coordinator.EnableAsync(DefaultConfig());
        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal(WakeWordUiState.Listening, coordinator.State);
        Assert.Equal(2, detector.StartCallCount);
    }

    [Fact]
    public async Task Coordinator_DuplicateDetectionGeneratesAtMostOneCommand()
    {
        var client = new FakeCoreClient("Hey Reva open chrome");
        var router = new RecordingCommandRouter(new CommandRouteResult(CommandOutcome.Executed, "Opened Google Chrome."));
        var assistant = new AssistantViewModel(client, commandRouter: router);
        var detector = new ScriptedWakeWordDetector((Exception?)null);
        var capture = new BlockingWakeSpeechCapture();
        var coordinator = NewCoordinator(detector, assistant: assistant, capture: capture);

        await coordinator.EnableAsync(DefaultConfig());
        detector.RaiseDetected(WakePhrase.HeyReva);
        detector.RaiseDetected(WakePhrase.HeyReva);
        capture.Allow.SetResult();
        await coordinator.WaitForTurnAsync();

        Assert.Equal(1, router.CallCount);
    }

    [Fact]
    public async Task Coordinator_RepeatedStartStopAndShutdown_DisposeDetectorAndRecoveryEvents()
    {
        var detector = new ScriptedWakeWordDetector(null, null);
        var recoveryEvents = new FakeWakeWordRecoveryEvents();
        var coordinator = NewCoordinator(detector, recoveryEvents: recoveryEvents);

        await coordinator.EnableAsync(DefaultConfig());
        await coordinator.DisableAsync();
        await coordinator.EnableAsync(DefaultConfig());
        await coordinator.DisposeAsync();

        Assert.Equal(1, detector.DisposeCallCount);
        Assert.False(recoveryEvents.IsStarted);
        Assert.Equal(2, detector.StopCallCount);
    }

    [Fact]
    public async Task PorcupineProvider_RepeatedStartStop_DisposesEngineRecorderAndCancellationResources()
    {
        var engine = new FakeWakeWordEngine();
        var recorder = new FakeWakeFrameRecorder();
        var detector = NewProvider(engine, recorder);
        var arbiter = new MicrophoneArbiter();

        await using (var lease1 = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord))
        {
            await detector.StartAsync(DefaultConfig(), lease1!);
            await detector.StopAsync();
        }

        await using (var lease2 = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord))
        {
            await detector.StartAsync(DefaultConfig(), lease2!);
        }

        await detector.DisposeAsync();

        Assert.Equal(2, recorder.StartCallCount);
        Assert.Equal(2, recorder.StopCallCount);
        Assert.Equal(2, recorder.DisposeCallCount);
        Assert.Equal(2, engine.DisposeCallCount);
    }

    [Fact]
    public async Task PorcupineProvider_DetectorExceptionRaisesRecoverableFault()
    {
        var engine = new FakeWakeWordEngine();
        var recorder = new FakeWakeFrameRecorder(readException: new InvalidOperationException("native detail"));
        var detector = NewProvider(engine, recorder);
        var faulted = new TaskCompletionSource<WakeWordFailure>(TaskCreationOptions.RunContinuationsAsynchronously);
        detector.Faulted += (_, failure) => faulted.TrySetResult(failure);
        var arbiter = new MicrophoneArbiter();
        await using var lease = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        await detector.StartAsync(DefaultConfig(), lease!);
        var failure = await faulted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await detector.StopAsync();

        Assert.Equal(WakeWordFailureKind.DetectorException, failure.Kind);
    }

    [Fact]
    public async Task Logs_DoNotContainSecretAudioTranscriptOrExceptionDetails()
    {
        const string accessKey = "secret-access-key";
        const string transcript = "Hey Reva private transcript";
        const string exceptionDetail = "C:\\private\\device";
        using var listener = new CapturingTraceListener();
        Trace.Listeners.Add(listener);
        var detector = new ScriptedWakeWordDetector(new InvalidOperationException(exceptionDetail));
        var coordinator = NewCoordinator(detector, client: new FakeCoreClient(transcript));

        try
        {
            WakeWordProviderDiagnostics.Create(
                new WakeWordRuntimeOptions(
                    true,
                    accessKey,
                    @"C:\kw",
                    DefaultConfig(),
                    new WakeWordModelManifest(
                        "2026.08.17",
                        "X64",
                        new Dictionary<WakePhrase, string> { [WakePhrase.HeyReva] = ExpectedHash })),
                "X64").Log();
            await coordinator.EnableAsync(DefaultConfig());
            var logText = string.Join(Environment.NewLine, listener.Messages);

            Assert.DoesNotContain(accessKey, logText);
            Assert.DoesNotContain(transcript, logText);
            Assert.DoesNotContain(exceptionDetail, logText);
            Assert.DoesNotContain(Convert.ToBase64String(TestWav.Mono16k(TimeSpan.FromMilliseconds(250))), logText);
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    private const string ExpectedHash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    private static WakeWordConfiguration DefaultConfig() =>
        new(new[] { new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f) });

    private static WakeWordCoordinator NewCoordinator(
        ScriptedWakeWordDetector detector,
        MicrophoneArbiter? arbiter = null,
        AssistantViewModel? assistant = null,
        IWakeSpeechCapture? capture = null,
        FakeCoreClient? client = null,
        IRevaCoreLifecycle? lifecycle = null,
        IWakeWordRecoveryEvents? recoveryEvents = null,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        client ??= new FakeCoreClient("Hey Reva open chrome");
        assistant ??= new AssistantViewModel(
            client,
            commandRouter: new RecordingCommandRouter(new CommandRouteResult(CommandOutcome.Executed, "Opened Google Chrome.")));
        return new WakeWordCoordinator(
            detector,
            arbiter ?? new MicrophoneArbiter(),
            capture ?? new FakeWakeSpeechCapture(),
            client,
            assistant,
            new FakeChimePlayer(),
            lifecycle,
            recoveryEvents,
            delay ?? ((_, _) => Task.CompletedTask));
    }

    private static PorcupineWakeWordDetector NewProvider(
        FakeWakeWordEngine engine,
        FakeWakeFrameRecorder recorder)
    {
        var manifest = new WakeWordModelManifest(
            "2026.08.17",
            System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture.ToString(),
            new Dictionary<WakePhrase, string> { [WakePhrase.HeyReva] = ExpectedHash });
        return new PorcupineWakeWordDetector(
            "access-key",
            @"C:\kw",
            new FakeFileSystemProbe((@"C:\kw\hey-reva.ppn", ExpectedHash)),
            manifest,
            new FakeWakeWordEngineFactory(engine),
            new FakeWakeFrameRecorderFactory(recorder));
    }

    private static void AssertPackageVersion(XDocument project, string packageName, string expected)
    {
        var reference = project.Descendants("PackageReference")
            .Single(element => (string?)element.Attribute("Include") == packageName);
        Assert.Equal(expected, (string?)reference.Attribute("Version"));
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "desktop", "src", "Reva.Desktop", "Reva.Desktop.csproj")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new InvalidOperationException("Could not locate repository root.");
    }

    private sealed class FakeWakeWordSettingsStore : IWakeWordSettingsStore
    {
        private readonly WakeWordLocalSettings _settings;

        public FakeWakeWordSettingsStore(WakeWordLocalSettings settings) => _settings = settings;

        public WakeWordLocalSettings Load() => _settings;
    }

    private sealed class FakeWakeWordSecretStore : IWakeWordSecretStore
    {
        private readonly string? _accessKey;

        public FakeWakeWordSecretStore(string? accessKey) => _accessKey = accessKey;

        public string? GetAccessKey() => _accessKey;
    }

    private sealed class FakeFileSystemProbe : IFileSystemProbe
    {
        private readonly Dictionary<string, string> _hashes;

        public FakeFileSystemProbe(params (string Path, string Sha256)[] hashes) =>
            _hashes = hashes.ToDictionary(item => item.Path, item => item.Sha256, StringComparer.OrdinalIgnoreCase);

        public bool FileExists(string path) => _hashes.ContainsKey(path);

        public string ComputeSha256(string path) => _hashes[path];
    }

    private sealed class FakeWakeWordRecoveryEvents : IWakeWordRecoveryEvents
    {
        public event EventHandler<WakeWordRecoveryReason>? RecoveryRequested;

        public bool IsStarted { get; private set; }

        public void Start() => IsStarted = true;

        public void Stop() => IsStarted = false;

        public void Dispose() => Stop();

        public void Raise(WakeWordRecoveryReason reason) => RecoveryRequested?.Invoke(this, reason);
    }

    private sealed class FakeWakeWordEngineFactory : IWakeWordEngineFactory
    {
        private readonly FakeWakeWordEngine _engine;

        public FakeWakeWordEngineFactory(FakeWakeWordEngine engine) => _engine = engine;

        public IWakeWordEngine Create(
            string accessKey,
            IReadOnlyList<string> keywordPaths,
            IReadOnlyList<float> sensitivities) => _engine.Clone();
    }

    private sealed class FakeWakeWordEngine : IWakeWordEngine
    {
        private readonly Counter _counter;

        public FakeWakeWordEngine() : this(new Counter())
        {
        }

        private FakeWakeWordEngine(Counter counter) => _counter = counter;

        public int SampleRate => 16000;
        public int FrameLength => 512;
        public int DisposeCallCount => _counter.Count;

        public int Process(short[] frame) => -1;

        public void Dispose() => _counter.Count++;

        public FakeWakeWordEngine Clone() => new(_counter);
    }

    private sealed class FakeWakeFrameRecorderFactory : IWakeFrameRecorderFactory
    {
        private readonly FakeWakeFrameRecorder _recorder;

        public FakeWakeFrameRecorderFactory(FakeWakeFrameRecorder recorder) => _recorder = recorder;

        public IWakeFrameRecorder Create(int frameLength) => _recorder.Clone();
    }

    private sealed class FakeWakeFrameRecorder : IWakeFrameRecorder
    {
        private readonly Counter _startCounter;
        private readonly Counter _stopCounter;
        private readonly Counter _disposeCounter;
        private readonly Exception? _readException;

        public FakeWakeFrameRecorder(Exception? readException = null)
            : this(new Counter(), new Counter(), new Counter(), readException)
        {
        }

        private FakeWakeFrameRecorder(
            Counter startCounter,
            Counter stopCounter,
            Counter disposeCounter,
            Exception? readException)
        {
            _startCounter = startCounter;
            _stopCounter = stopCounter;
            _disposeCounter = disposeCounter;
            _readException = readException;
        }

        public bool IsRecording { get; private set; }
        public int StartCallCount => _startCounter.Count;
        public int StopCallCount => _stopCounter.Count;
        public int DisposeCallCount => _disposeCounter.Count;

        public void Start()
        {
            _startCounter.Count++;
            IsRecording = true;
        }

        public short[] Read()
        {
            if (_readException is not null)
            {
                throw _readException;
            }

            Thread.Sleep(10);
            return new short[512];
        }

        public void Stop()
        {
            _stopCounter.Count++;
            IsRecording = false;
        }

        public void Dispose() => _disposeCounter.Count++;

        public FakeWakeFrameRecorder Clone() =>
            new(_startCounter, _stopCounter, _disposeCounter, _readException);
    }

    private sealed class Counter
    {
        public int Count;
    }

    private sealed class ScriptedWakeWordDetector : IWakeWordDetector
    {
        private readonly Queue<Exception?> _startResults;

        public ScriptedWakeWordDetector(params Exception?[] startResults) =>
            _startResults = new Queue<Exception?>(startResults);

        public event EventHandler<WakeWordDetection>? Detected;
        public event EventHandler<WakeWordFailure>? Faulted;

        public bool IsRunning { get; private set; }
        public int StartCallCount { get; private set; }
        public int StopCallCount { get; private set; }
        public int DisposeCallCount { get; private set; }

        public Task StartAsync(
            WakeWordConfiguration configuration,
            IMicrophoneLease lease,
            CancellationToken cancellationToken = default)
        {
            StartCallCount++;
            var result = _startResults.Count == 0 ? null : _startResults.Dequeue();
            if (result is not null)
            {
                throw result;
            }

            IsRunning = true;
            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken cancellationToken = default)
        {
            StopCallCount++;
            IsRunning = false;
            return Task.CompletedTask;
        }

        public void RaiseDetected(WakePhrase phrase) =>
            Detected?.Invoke(this, new WakeWordDetection(phrase, DateTimeOffset.UtcNow));

        public void RaiseFault() =>
            Faulted?.Invoke(this, new WakeWordFailure(WakeWordFailureKind.DetectorException));

        public ValueTask DisposeAsync()
        {
            DisposeCallCount++;
            IsRunning = false;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class RecordingCommandRouter : ICommandRouter
    {
        private readonly CommandRouteResult _result;

        public RecordingCommandRouter(CommandRouteResult result) => _result = result;

        public int CallCount { get; private set; }

        public Task<CommandRouteResult> RouteAsync(
            string text,
            CommandSource source,
            CancellationToken cancellationToken = default)
        {
            CallCount++;
            return Task.FromResult(_result);
        }
    }

    private sealed class FakeWakeSpeechCapture : IWakeSpeechCapture
    {
        public Task<byte[]> CaptureAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(TestWav.Mono16k(TimeSpan.FromSeconds(1)));
    }

    private sealed class BlockingWakeSpeechCapture : IWakeSpeechCapture
    {
        public TaskCompletionSource Allow { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public async Task<byte[]> CaptureAsync(CancellationToken cancellationToken = default)
        {
            await Allow.Task.WaitAsync(cancellationToken);
            return TestWav.Mono16k(TimeSpan.FromSeconds(1));
        }
    }

    private sealed class FakeChimePlayer : IChimePlayer
    {
        public Task PlayAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
    }

    private sealed class FakeCoreLifecycle : IRevaCoreLifecycle
    {
        public CoreLifecycleState State { get; set; } = CoreLifecycleState.Connected;
        public string StatusText => State.ToString();
        public event EventHandler? StateChanged;
        public Task StartAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public void StopMonitoring() { }
        public void RaiseStateChanged() => StateChanged?.Invoke(this, EventArgs.Empty);
    }

    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly Queue<string> _transcripts;
        private readonly Exception? _transcriptionException;

        public FakeCoreClient(params string[] transcripts)
        {
            _transcripts = new Queue<string>(transcripts);
        }

        public FakeCoreClient(Exception? transcriptionException = null)
        {
            _transcripts = new Queue<string>();
            _transcriptionException = transcriptionException;
        }

        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(
            string content,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("Wake hardening tests must not call Core chat.");

        public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
            byte[] wavAudio,
            CancellationToken cancellationToken = default)
        {
            if (_transcriptionException is not null)
            {
                throw _transcriptionException;
            }

            return Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(
                new VoiceTranscriptionResponse(1, _transcripts.Dequeue(), "en", 900)));
        }

        public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(
            string text,
            string language,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException("Wake hardening tests must not call TTS.");

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(
            string content,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(
            string query,
            int limit,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }

    private sealed class CapturingTraceListener : TraceListener
    {
        public List<string> Messages { get; } = new();

        public override void Write(string? message)
        {
            if (message is not null)
            {
                Messages.Add(message);
            }
        }

        public override void WriteLine(string? message)
        {
            if (message is not null)
            {
                Messages.Add(message);
            }
        }
    }
}
