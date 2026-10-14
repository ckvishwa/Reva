using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WakeWordFailClosedTests
{
    private const string ActualHash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private const string OtherHash = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210";

    [Theory]
    [InlineData("missing-entry", KeywordResolutionFailure.MissingExpectedHash)]
    [InlineData("blank-entry", KeywordResolutionFailure.MissingExpectedHash)]
    [InlineData("invalid-hash", KeywordResolutionFailure.HashMismatch)]
    [InlineData("mismatched-hash", KeywordResolutionFailure.HashMismatch)]
    public void Resolve_FailsClosed_WhenHashCannotBeVerified(string scenario, KeywordResolutionFailure expected)
    {
        var result = WakeWordKeywordResolver.Resolve(
            Phrases(),
            @"C:\kw",
            new HashingProbe(),
            ManifestFor(scenario));

        Assert.False(result.IsSuccess);
        Assert.Equal(expected, result.Failure);
        Assert.Null(result.KeywordPaths);
    }

    [Fact]
    public void Resolve_EmptyManifestOverloadWithoutManifest_FailsClosed()
    {
        var result = WakeWordKeywordResolver.Resolve(Phrases(), @"C:\kw", new HashingProbe());

        Assert.False(result.IsSuccess);
        Assert.Equal(KeywordResolutionFailure.MissingExpectedHash, result.Failure);
    }

    [Fact]
    public void Resolve_Succeeds_WhenHashMatches()
    {
        var result = WakeWordKeywordResolver.Resolve(
            Phrases(),
            @"C:\kw",
            new HashingProbe(),
            ManifestFor("matching-hash"));

        Assert.True(result.IsSuccess);
        Assert.Equal(new[] { @"C:\kw\hey-reva.ppn" }, result.KeywordPaths);
    }

    [Theory]
    [InlineData("empty-manifest")]
    [InlineData("missing-entry")]
    [InlineData("blank-entry")]
    [InlineData("invalid-hash")]
    [InlineData("mismatched-hash")]
    public async Task Detector_NeverCreatesEngineOrArmsRecorder_WhenValidationFails(string scenario)
    {
        var engines = new CountingEngineFactory();
        var recorders = new CountingRecorderFactory();
        var detector = new PorcupineWakeWordDetector(
            "access-key",
            @"C:\kw",
            new HashingProbe(),
            ManifestFor(scenario),
            engines,
            recorders);

        await Assert.ThrowsAsync<WakeWordConfigurationException>(
            () => detector.StartAsync(new WakeWordConfiguration(Phrases()), new Lease()));

        Assert.False(detector.IsRunning);
        Assert.Equal(0, engines.Created);
        Assert.Equal(0, recorders.Created);
        Assert.Equal(0, recorders.Started);
    }

    [Fact]
    public async Task Detector_ArmsRecorder_OnlyWhenHashMatches()
    {
        var engines = new CountingEngineFactory();
        var recorders = new CountingRecorderFactory();
        var detector = new PorcupineWakeWordDetector(
            "access-key",
            @"C:\kw",
            new HashingProbe(),
            ManifestFor("matching-hash"),
            engines,
            recorders);

        await detector.StartAsync(new WakeWordConfiguration(Phrases()), new Lease());

        Assert.True(detector.IsRunning);
        Assert.Equal(1, engines.Created);
        Assert.Equal(1, recorders.Started);
        await detector.StopAsync();
    }

    private static IReadOnlyList<WakePhraseSetting> Phrases() =>
        new[] { new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f) };

    private static WakeWordModelManifest ManifestFor(string scenario)
    {
        var hashes = new Dictionary<WakePhrase, string>();
        switch (scenario)
        {
            case "empty-manifest":
            case "missing-entry":
                return scenario == "empty-manifest" ? WakeWordModelManifest.Empty : new(string.Empty, string.Empty, hashes);
            case "blank-entry":
                hashes[WakePhrase.HeyReva] = "  ";
                break;
            case "invalid-hash":
                hashes[WakePhrase.HeyReva] = "not-a-sha256";
                break;
            case "mismatched-hash":
                hashes[WakePhrase.HeyReva] = OtherHash;
                break;
            case "matching-hash":
                hashes[WakePhrase.HeyReva] = ActualHash;
                break;
        }

        return new WakeWordModelManifest(
            string.Empty,
            string.Empty,
            hashes);
    }

    private sealed class HashingProbe : IFileSystemProbe
    {
        public bool FileExists(string path) => path == @"C:\kw\hey-reva.ppn";

        public string ComputeSha256(string path) => ActualHash;
    }

    private sealed class Lease : IMicrophoneLease
    {
        public MicrophoneOwner Owner => default;

        public bool IsActive => true;

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class CountingEngineFactory : IWakeWordEngineFactory
    {
        public int Created { get; private set; }

        public IWakeWordEngine Create(
            string accessKey,
            IReadOnlyList<string> keywordPaths,
            IReadOnlyList<float> sensitivities)
        {
            Created++;
            return new Engine();
        }
    }

    private sealed class Engine : IWakeWordEngine
    {
        public int SampleRate => 16000;

        public int FrameLength => 512;

        public int Process(short[] frame) => -1;

        public void Dispose()
        {
        }
    }

    private sealed class CountingRecorderFactory : IWakeFrameRecorderFactory
    {
        public int Created { get; private set; }

        public int Started { get; private set; }

        public IWakeFrameRecorder Create(int frameLength)
        {
            Created++;
            return new Recorder(this);
        }

        public void MarkStarted() => Started++;
    }

    private sealed class Recorder : IWakeFrameRecorder
    {
        private readonly CountingRecorderFactory _owner;

        public Recorder(CountingRecorderFactory owner) => _owner = owner;

        public bool IsRecording { get; private set; }

        public void Start()
        {
            IsRecording = true;
            _owner.MarkStarted();
        }

        public short[] Read()
        {
            Thread.Sleep(5);
            return new short[512];
        }

        public void Stop() => IsRecording = false;

        public void Dispose() => Stop();
    }
}
