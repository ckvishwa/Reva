# Transcription-Only Voice Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing Hold-to-Talk voice turn (which today auto-sends the transcript to Core and auto-plays a TTS reply) into a transcription-only slice: mic capture → STT → populate the composer textbox → stop. Fix the readiness/status contradictions along the way (mic vs. Core vs. TTS are currently tangled).

**Architecture:** All changes are desktop-only (`desktop/src/Reva.Desktop`), no `reva_core` backend changes. `AssistantViewModel.FinishVoiceInputAsync` drops its calls to `SendMessageCoreAsync`/`SynthesizeSpeechAsync`/`PlayAsync` and instead writes the transcription into `ComposerText`. A new `VoiceUiState` enum replaces the two loose "Voice Ready"/"Voice Unavailable" strings with the nine states the spec requires. Hold-to-Talk is gated on mic readiness AND Core connectivity (via a new optional `IRevaCoreLifecycle` dependency on `AssistantViewModel`) — never on TTS. `RevaCoreClient` gets a dedicated, longer timeout for the transcription call, independent of the 10s default used elsewhere, and its `SendAsync` timeout-message bug (voice calls surfacing the generic "REVA Core did not respond in time." instead of the voice-specific message) gets fixed. `WindowsVoiceDevice` captures mono 16kHz PCM WAV directly (no post-capture conversion).

**Tech Stack:** C# / .NET (net10.0-windows10.0.19041.0), WinUI 3, WinRT `Windows.Media.Capture`, xUnit.

## Global Constraints

- STT only — no ADK/assistant auto-invoke, no TTS invocation, from the voice-turn code path (verbatim: "Strict scope: STT only... Do not invoke ADK/assistant automatically. Do not invoke TTS.").
- Never log captured audio or transcript content (existing `DesktopLogger.Info` calls in pointer handlers already log fixed strings only — do not add content to them).
- TTS availability must not affect mic/STT readiness or the Hold-to-Talk enabled state.
- No `reva_core` / Python changes — this slice is desktop-only (design decision, see `docs/superpowers/specs/2026-08-16-transcription-only-voice-slice-design.md`).
- Required exact UI status strings: `Checking Microphone`, `Ready to Talk`, `Listening`, `Transcribing`, `Transcription Ready`, `Permission Denied`, `No Microphone`, `STT Unavailable`, `Transcription Failed`.
- Required exact permission message: `Microphone permission is disabled. Enable it in Windows Settings.`
- Recordings under 250ms must be rejected with a safe message, before any Core call.
- Capture format: mono PCM WAV, 16kHz.
- Commit the feature only after the real-microphone acceptance run passes (last task in this plan) — do not commit Tasks 1-8 individually with `git commit` beyond what each task step says; follow each task's own commit step (small WIP commits are fine on this branch, `phase/1b-windows-desktop`, but the task's final "prove it end to end" step gates calling the work done).

---

## File Structure

- `desktop/src/Reva.Desktop/State/VoiceUiState.cs` — **new**. Enum with the 9 states + a static `ToDisplayText` mapping.
- `desktop/src/Reva.Desktop/Services/VoiceDeviceAvailability.cs` — **modify**. Update `PermissionDenied()` message text.
- `desktop/src/Reva.Desktop/Services/WavAudio.cs` — **new**. Static helper: `TryGetDurationMs(byte[] wav, out int durationMs)`, mirrors `reva_core/api/routes.py`'s `_read_wav_metadata`/`_validate_wav_upload` RIFF/WAVE parsing.
- `desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs` — **modify**. Add `SttRequestTimeout` property + `REVA_DESKTOP_STT_TIMEOUT_SECONDS` env override.
- `desktop/src/Reva.Desktop/Services/RevaCoreClient.cs` — **modify**. Constructor takes timeouts; `TranscribeSpeechAsync` uses the STT timeout; `SendAsync`'s `TaskCanceledException` catch becomes voice-aware.
- `desktop/src/Reva.Desktop/Services/WindowsVoiceDevice.cs` — **modify**. Force mono/16kHz PCM in `StartRecordingAsync`.
- `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs` — **modify**. New `IRevaCoreLifecycle?` constructor parameter, `VoiceUiState`-based status, rewritten `FinishVoiceInputAsync` (transcription-only), WAV duration validation.
- `desktop/src/Reva.Desktop/MainWindow.xaml.cs` — **modify**. Pass `lifecycle` into `AssistantViewModel`; after a successful voice transcription, also set `ComposerBox.Text` directly (same LostFocus-commit gap as `SyncComposerTextFromTextBox`).
- `desktop/src/Reva.Desktop/App.xaml.cs` — **modify**. `httpClient.Timeout = Timeout.InfiniteTimeSpan`; pass both timeouts into `RevaCoreClient`.
- `desktop/tests/Reva.Desktop.Tests/Unit/WavAudioTests.cs` — **new**.
- `desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreClientTests.cs` — **modify**. Add STT-timeout-specific test.
- `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs` — **modify**. Replace the voice-turn test block (everything from `VoiceTurn_TranscribesThenUsesExistingMessagePipelineThenSpeaksReply` through `StopSpeaking_HaltsActivePlaybackImmediately`) with the transcription-only test set. Typed-chat tests (`InitialState_...` through `SendMessageAsync_NeverExposesTokenValue...`) are untouched.

---

### Task 1: `VoiceUiState` enum

**Files:**
- Create: `desktop/src/Reva.Desktop/State/VoiceUiState.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/VoiceUiStateTests.cs`

**Interfaces:**
- Produces: `enum VoiceUiState { CheckingMicrophone, ReadyToTalk, Listening, Transcribing, TranscriptionReady, PermissionDenied, NoMicrophone, SttUnavailable, TranscriptionFailed }` and `static class VoiceUiStateText { public static string For(VoiceUiState state) }`.

- [ ] **Step 1: Write the failing test**

```csharp
using Reva.Desktop.State;

namespace Reva.Desktop.Tests.Unit;

public class VoiceUiStateTests
{
    [Theory]
    [InlineData(VoiceUiState.CheckingMicrophone, "Checking Microphone")]
    [InlineData(VoiceUiState.ReadyToTalk, "Ready to Talk")]
    [InlineData(VoiceUiState.Listening, "Listening")]
    [InlineData(VoiceUiState.Transcribing, "Transcribing")]
    [InlineData(VoiceUiState.TranscriptionReady, "Transcription Ready")]
    [InlineData(VoiceUiState.PermissionDenied, "Permission Denied")]
    [InlineData(VoiceUiState.NoMicrophone, "No Microphone")]
    [InlineData(VoiceUiState.SttUnavailable, "STT Unavailable")]
    [InlineData(VoiceUiState.TranscriptionFailed, "Transcription Failed")]
    public void For_ReturnsExactRequiredText(VoiceUiState state, string expected)
    {
        Assert.Equal(expected, VoiceUiStateText.For(state));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter VoiceUiStateTests`
Expected: FAIL (build error — `VoiceUiState`/`VoiceUiStateText` don't exist yet)

- [ ] **Step 3: Write minimal implementation**

```csharp
namespace Reva.Desktop.State;

public enum VoiceUiState
{
    CheckingMicrophone,
    ReadyToTalk,
    Listening,
    Transcribing,
    TranscriptionReady,
    PermissionDenied,
    NoMicrophone,
    SttUnavailable,
    TranscriptionFailed,
}

public static class VoiceUiStateText
{
    public static string For(VoiceUiState state) => state switch
    {
        VoiceUiState.CheckingMicrophone => "Checking Microphone",
        VoiceUiState.ReadyToTalk => "Ready to Talk",
        VoiceUiState.Listening => "Listening",
        VoiceUiState.Transcribing => "Transcribing",
        VoiceUiState.TranscriptionReady => "Transcription Ready",
        VoiceUiState.PermissionDenied => "Permission Denied",
        VoiceUiState.NoMicrophone => "No Microphone",
        VoiceUiState.SttUnavailable => "STT Unavailable",
        VoiceUiState.TranscriptionFailed => "Transcription Failed",
        _ => throw new ArgumentOutOfRangeException(nameof(state)),
    };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter VoiceUiStateTests`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/State/VoiceUiState.cs desktop/tests/Reva.Desktop.Tests/Unit/VoiceUiStateTests.cs
git commit -m "feat(desktop): add VoiceUiState enum with required status text"
```

---

### Task 2: WAV duration validation helper

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/WavAudio.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/WavAudioTests.cs`

**Interfaces:**
- Produces: `static class WavAudio { public static bool TryGetDurationMs(byte[] wav, out int durationMs) }`. Returns `false` (with `durationMs = 0`) for empty input, malformed RIFF/WAVE, or an unreadable `fmt `/`data` chunk. On success, `durationMs = (int)Math.Round(dataBytes / (double)blockAlign / sampleRate * 1000)`.

- [ ] **Step 1: Write the failing test**

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WavAudioTests
{
    // 16kHz, mono, 16-bit PCM WAV: 44-byte header + N bytes of data.
    // blockAlign = 2 (1 channel * 16 bits / 8). frames = dataBytes / blockAlign.
    // durationMs = frames / 16000 * 1000.
    private static byte[] BuildWav(int sampleRate, short channels, short bitsPerSample, int dataBytes)
    {
        short blockAlign = (short)(channels * bitsPerSample / 8);
        int byteRate = sampleRate * blockAlign;
        int riffChunkSize = 36 + dataBytes;

        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write("RIFF"u8.ToArray());
        writer.Write(riffChunkSize);
        writer.Write("WAVE"u8.ToArray());
        writer.Write("fmt "u8.ToArray());
        writer.Write(16); // fmt chunk size
        writer.Write((short)1); // PCM
        writer.Write(channels);
        writer.Write(sampleRate);
        writer.Write(byteRate);
        writer.Write(blockAlign);
        writer.Write(bitsPerSample);
        writer.Write("data"u8.ToArray());
        writer.Write(dataBytes);
        writer.Write(new byte[dataBytes]);
        return stream.ToArray();
    }

    [Fact]
    public void TryGetDurationMs_OneSecond16kHzMono_ReturnsApproximately1000()
    {
        var wav = BuildWav(sampleRate: 16000, channels: 1, bitsPerSample: 16, dataBytes: 16000 * 2);

        var ok = WavAudio.TryGetDurationMs(wav, out var durationMs);

        Assert.True(ok);
        Assert.Equal(1000, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_100Milliseconds_ReturnsApproximately100()
    {
        var wav = BuildWav(sampleRate: 16000, channels: 1, bitsPerSample: 16, dataBytes: 1600 * 2);

        var ok = WavAudio.TryGetDurationMs(wav, out var durationMs);

        Assert.True(ok);
        Assert.Equal(100, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_EmptyArray_ReturnsFalse()
    {
        var ok = WavAudio.TryGetDurationMs(Array.Empty<byte>(), out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_NotRiffWave_ReturnsFalse()
    {
        var ok = WavAudio.TryGetDurationMs(new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 }, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_ZeroDataBytes_ReturnsZeroDuration()
    {
        var wav = BuildWav(sampleRate: 16000, channels: 1, bitsPerSample: 16, dataBytes: 0);

        var ok = WavAudio.TryGetDurationMs(wav, out var durationMs);

        Assert.True(ok);
        Assert.Equal(0, durationMs);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WavAudioTests`
Expected: FAIL (build error — `WavAudio` doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

```csharp
using System.Buffers.Binary;

namespace Reva.Desktop.Services;

public static class WavAudio
{
    public static bool TryGetDurationMs(byte[] wav, out int durationMs)
    {
        durationMs = 0;
        if (wav.Length < 12 || !Tag(wav, 0, "RIFF") || !Tag(wav, 8, "WAVE"))
        {
            return false;
        }

        var offset = 12;
        var sampleRate = 0;
        var blockAlign = 0;
        var dataBytes = -1;

        while (offset + 8 <= wav.Length)
        {
            var chunkId = System.Text.Encoding.ASCII.GetString(wav, offset, 4);
            var chunkSize = (int)BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(offset + 4, 4));
            var chunkStart = offset + 8;
            var chunkEnd = chunkStart + chunkSize;
            if (chunkEnd > wav.Length)
            {
                return false;
            }

            if (chunkId == "fmt " && chunkSize >= 16)
            {
                sampleRate = (int)BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(chunkStart + 4, 4));
                blockAlign = BinaryPrimitives.ReadUInt16LittleEndian(wav.AsSpan(chunkStart + 12, 2));
            }
            else if (chunkId == "data")
            {
                dataBytes = chunkSize;
            }

            offset = chunkEnd + (chunkSize % 2);
        }

        if (sampleRate <= 0 || blockAlign <= 0 || dataBytes < 0)
        {
            return false;
        }

        var frames = dataBytes / (double)blockAlign;
        durationMs = (int)Math.Round(frames / sampleRate * 1000);
        return true;
    }

    private static bool Tag(byte[] data, int offset, string tag) =>
        System.Text.Encoding.ASCII.GetString(data, offset, 4) == tag;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WavAudioTests`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/WavAudio.cs desktop/tests/Reva.Desktop.Tests/Unit/WavAudioTests.cs
git commit -m "feat(desktop): add WAV duration parsing for capture validation"
```

---

### Task 3: Permission message text + `DesktopConfiguration.SttRequestTimeout`

**Files:**
- Modify: `desktop/src/Reva.Desktop/Services/VoiceDeviceAvailability.cs:20-21`
- Modify: `desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/VoiceDeviceAvailabilityTests.cs` (new, small)
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs` (existing file — check first; if absent, create)

**Interfaces:**
- Produces: `VoiceDeviceAvailability.PermissionDenied().SafeMessage == "Microphone permission is disabled. Enable it in Windows Settings."`. `DesktopConfiguration.SttRequestTimeout` (`TimeSpan`, default 30s, env override `REVA_DESKTOP_STT_TIMEOUT_SECONDS`), and a new `DesktopConfiguration(Uri, string, TimeSpan requestTimeout, TimeSpan sttRequestTimeout)` constructor overload.

- [ ] **Step 1: Check for an existing `DesktopConfigurationTests.cs`**

Run: `Get-ChildItem desktop/tests/Reva.Desktop.Tests/Unit -Filter DesktopConfigurationTests.cs` (or `find` on non-Windows shells). If it exists, read it first and add tests in its existing style rather than guessing a new one; the tests below assume none exists.

- [ ] **Step 2: Write the failing tests**

```csharp
// VoiceDeviceAvailabilityTests.cs
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class VoiceDeviceAvailabilityTests
{
    [Fact]
    public void PermissionDenied_HasRequiredSafeMessage()
    {
        var availability = VoiceDeviceAvailability.PermissionDenied();

        Assert.Equal(
            "Microphone permission is disabled. Enable it in Windows Settings.",
            availability.SafeMessage);
        Assert.Equal(VoiceDeviceAvailabilityKind.PermissionDenied, availability.Kind);
        Assert.False(availability.IsReady);
    }
}
```

```csharp
// DesktopConfigurationTests.cs — add if the file doesn't already exist
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class DesktopConfigurationTests
{
    [Fact]
    public void Constructor_DefaultSttTimeout_Is30Seconds()
    {
        var configuration = new DesktopConfiguration(
            new Uri("http://127.0.0.1:8756/"), "C:\\data", TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(30));

        Assert.Equal(TimeSpan.FromSeconds(30), configuration.SttRequestTimeout);
    }

    [Fact]
    public void CreateDefault_SttTimeoutEnvVarOverride_IsRespected()
    {
        Environment.SetEnvironmentVariable("REVA_DESKTOP_STT_TIMEOUT_SECONDS", "45");
        try
        {
            var configuration = DesktopConfiguration.CreateDefault();
            Assert.Equal(TimeSpan.FromSeconds(45), configuration.SttRequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable("REVA_DESKTOP_STT_TIMEOUT_SECONDS", null);
        }
    }
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter "VoiceDeviceAvailabilityTests|DesktopConfigurationTests"`
Expected: FAIL — `PermissionDenied_HasRequiredSafeMessage` fails on the message-text assertion; `DesktopConfigurationTests` fails to build (no `SttRequestTimeout`, no 4-arg constructor).

- [ ] **Step 4: Implement**

In `VoiceDeviceAvailability.cs`, change line 21:

```csharp
    public static VoiceDeviceAvailability PermissionDenied() =>
        new(VoiceDeviceAvailabilityKind.PermissionDenied, "Microphone permission is disabled. Enable it in Windows Settings.");
```

In `DesktopConfiguration.cs`, add the STT timeout throughout:

```csharp
    private const string SttRequestTimeoutSecondsEnvironmentVariable = "REVA_DESKTOP_STT_TIMEOUT_SECONDS";
    private static readonly TimeSpan DefaultSttRequestTimeout = TimeSpan.FromSeconds(30);
```

Add the property next to `RequestTimeout`:

```csharp
    public TimeSpan SttRequestTimeout { get; }
```

Replace the constructor with a version that takes both timeouts (update the call site in `CreateDefault` accordingly — this is a breaking signature change for a class with exactly one production call site, `CreateDefault`, plus test call sites this task is already touching):

```csharp
    public DesktopConfiguration(Uri coreBaseUrl, string coreDataDirectory, TimeSpan requestTimeout, TimeSpan sttRequestTimeout)
    {
        if (!IsLoopback(coreBaseUrl))
        {
            throw new DesktopConfigurationException(
                $"REVA Core URL must be loopback-only (localhost/127.0.0.1/::1), got '{coreBaseUrl.Host}'.");
        }

        CoreBaseUrl = coreBaseUrl;
        CoreDataDirectory = coreDataDirectory;
        RequestTimeout = requestTimeout;
        SttRequestTimeout = sttRequestTimeout;
    }
```

In `CreateDefault()`, after the existing `requestTimeout` computation, add:

```csharp
        var sttTimeoutOverride = Environment.GetEnvironmentVariable(SttRequestTimeoutSecondsEnvironmentVariable);
        var sttRequestTimeout =
            double.TryParse(sttTimeoutOverride, out var sttTimeoutSeconds) && sttTimeoutSeconds > 0
                ? TimeSpan.FromSeconds(sttTimeoutSeconds)
                : DefaultSttRequestTimeout;

        return new DesktopConfiguration(baseUrl, dataDirectory, requestTimeout, sttRequestTimeout);
```

- [ ] **Step 5: Search for and fix any other call sites of the 3-arg `DesktopConfiguration` constructor**

Run: `Select-String -Path desktop/**/*.cs -Pattern "new DesktopConfiguration\("` (or `Grep` for `new DesktopConfiguration(`). Update every match to pass a 4th `TimeSpan` argument (e.g. `TimeSpan.FromSeconds(30)` for tests that don't care about the STT timeout specifically).

- [ ] **Step 6: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter "VoiceDeviceAvailabilityTests|DesktopConfigurationTests"`
Expected: PASS

- [ ] **Step 7: Run the full test suite to catch any other break from the constructor signature change**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS (fix any other call sites Step 5 missed)

- [ ] **Step 8: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/VoiceDeviceAvailability.cs desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs desktop/tests/Reva.Desktop.Tests/Unit/VoiceDeviceAvailabilityTests.cs desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs
git commit -m "fix(desktop): exact permission message text, add dedicated STT timeout config"
```

---

### Task 4: `RevaCoreClient` — dedicated STT timeout + voice-aware timeout message

**Files:**
- Modify: `desktop/src/Reva.Desktop/Services/RevaCoreClient.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreClientTests.cs`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `RevaCoreClient(HttpClient httpClient, ILocalTokenProvider tokenProvider, TimeSpan? requestTimeout = null, TimeSpan? sttRequestTimeout = null)`. `TranscribeSpeechAsync` now enforces `sttRequestTimeout` (default 30s) independent of `httpClient.Timeout`, and its timeout failure returns `CoreErrorKind.CoreTimeout` with message `"REVA voice did not respond in time."` (not the generic Core message).

- [ ] **Step 1: Write the failing test**

Add to `RevaCoreClientTests.cs`:

```csharp
    [Fact]
    public async Task TranscribeSpeechAsync_Timeout_MapsToVoiceTimeoutMessage_NotGenericCoreMessage()
    {
        var (client, _) = AuthenticatedClientFor(FakeHttpMessageHandler.ThrowingTimeout());

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreTimeout, result.Error!.Kind);
        Assert.Equal("REVA voice did not respond in time.", result.Error.SafeMessage);
    }

    [Fact]
    public async Task TranscribeSpeechAsync_UsesSttTimeout_IndependentOfHttpClientDefaultTimeout()
    {
        // httpClient.Timeout left at HttpClient's own default (100s) here —
        // this test only proves the client compiles/runs with an explicit,
        // short sttRequestTimeout and that a slow-but-eventually-responding
        // fake still completes (i.e. the per-call CTS doesn't fire early
        // for a handler that returns promptly). The timeout-firing path
        // itself is covered by the test above via ThrowingTimeout().
        var handler = FakeHttpMessageHandler.ReturningStatus(
            HttpStatusCode.OK,
            """{"schema_version":1,"text":"hello","language":"en","duration_ms":900}""");
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") };
        var client = new RevaCoreClient(
            httpClient, new FakeTokenProvider("t"), TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(30));

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.True(result.IsSuccess);
        Assert.Equal("hello", result.Value!.Text);
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter TranscribeSpeechAsync_Timeout_MapsToVoiceTimeoutMessage_NotGenericCoreMessage`
Expected: FAIL — currently returns `"REVA Core did not respond in time."` (the generic message), not the voice one, because `SendAsync`'s `TaskCanceledException` catch ignores `voiceRequest`.

- [ ] **Step 3: Implement**

Replace the constructor and add the timeout fields in `RevaCoreClient.cs`:

```csharp
    private readonly HttpClient _httpClient;
    private readonly ILocalTokenProvider _tokenProvider;
    private readonly TimeSpan _requestTimeout;
    private readonly TimeSpan _sttRequestTimeout;

    public RevaCoreClient(
        HttpClient httpClient,
        ILocalTokenProvider tokenProvider,
        TimeSpan? requestTimeout = null,
        TimeSpan? sttRequestTimeout = null)
    {
        _httpClient = httpClient;
        _tokenProvider = tokenProvider;
        _requestTimeout = requestTimeout ?? TimeSpan.FromSeconds(10);
        _sttRequestTimeout = sttRequestTimeout ?? TimeSpan.FromSeconds(30);
    }
```

Change `TranscribeSpeechAsync` to pass the STT timeout through:

```csharp
    public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(
        byte[] wavAudio, CancellationToken cancellationToken = default)
    {
        var body = new ByteArrayContent(wavAudio);
        body.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
        return SendAsync<VoiceTranscriptionResponse>(
            HttpMethod.Post,
            "v1/voice/transcriptions",
            requiresAuth: true,
            cancellationToken,
            body,
            voiceRequest: true,
            timeout: _sttRequestTimeout);
    }
```

Change `SendAsync` to accept and enforce a per-call timeout, and to use the voice-specific message on timeout:

```csharp
    private async Task<CoreResult<T>> SendAsync<T>(
        HttpMethod method,
        string relativePath,
        bool requiresAuth,
        CancellationToken cancellationToken,
        HttpContent? content = null,
        bool voiceRequest = false,
        TimeSpan? timeout = null)
    {
        using var request = new HttpRequestMessage(method, relativePath);
        if (content is not null)
        {
            request.Content = content;
        }

        if (requiresAuth)
        {
            var tokenResult = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
            if (!tokenResult.IsAvailable)
            {
                return CoreResult<T>.Failure(
                    CoreErrorKind.CoreUnauthorized, "REVA authorization is unavailable.");
            }

            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", tokenResult.Token);
        }

        using var timeoutCts = new CancellationTokenSource(timeout ?? _requestTimeout);
        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);

        HttpResponseMessage response;
        try
        {
            response = await _httpClient.SendAsync(request, linkedCts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            // Our own per-call timeout fired, distinct from caller-requested
            // cancellation (which we let propagate normally rather than
            // normalizing).
            var message = voiceRequest ? "REVA voice did not respond in time." : "REVA Core did not respond in time.";
            return CoreResult<T>.Failure(CoreErrorKind.CoreTimeout, message);
        }
        catch (HttpRequestException)
        {
            return CoreResult<T>.Failure(CoreErrorKind.CoreUnavailable, "REVA Core is not reachable.");
        }

        using (response)
        {
            return await InterpretResponseAsync<T>(response, cancellationToken, voiceRequest)
                .ConfigureAwait(false);
        }
    }
```

Note the catch changed from `TaskCanceledException` to `OperationCanceledException` (its base type) — `HttpClient.SendAsync` throws `TaskCanceledException` for both its own internal timeout and for a cancelled token, and `TaskCanceledException` already derives from `OperationCanceledException`, so this is not a behavior change for what gets caught, only broadens the catch to also match if the linked-CTS cancellation surfaces as the base type in some path. Leave `SendBytesAsync` and its own `TaskCanceledException` catch untouched — it's out of scope (TTS-only method).

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter RevaCoreClientTests`
Expected: PASS, including all pre-existing `RevaCoreClientTests` (the default-timeout behavior for non-voice calls is unchanged — 10s default, generic message).

- [ ] **Step 5: Update `App.xaml.cs` so the shared `HttpClient`'s own timeout never pre-empts the STT per-call timeout**

In `App.xaml.cs`, change:

```csharp
        var httpClient = new System.Net.Http.HttpClient
        {
            BaseAddress = configuration.CoreBaseUrl,
            Timeout = System.Threading.Timeout.InfiniteTimeSpan,
        };
        var coreClient = new RevaCoreClient(
            httpClient, tokenProvider, configuration.RequestTimeout, configuration.SttRequestTimeout);
```

(Both timeouts are now enforced entirely by `RevaCoreClient`'s own per-call `CancellationTokenSource`, not by `HttpClient.Timeout`.)

- [ ] **Step 6: Run the full test suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/RevaCoreClient.cs desktop/src/Reva.Desktop/App.xaml.cs desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreClientTests.cs
git commit -m "fix(desktop): give voice transcription its own timeout and correct timeout message"
```

---

### Task 5: Mono 16kHz capture in `WindowsVoiceDevice`

**Files:**
- Modify: `desktop/src/Reva.Desktop/Services/WindowsVoiceDevice.cs:79-85`

No unit test here — `WindowsVoiceDevice` requires a real WinRT `MediaCapture` and cannot run under xUnit (this is exactly why `IVoiceDevice` exists as a fake-able seam; `AssistantViewModel`'s tests in Task 7 exercise the format-validation logic against `FakeVoiceDevice`-supplied bytes instead). This task is verified in Task 9's real-microphone acceptance run (WAV size / duration reported there should be consistent with 16kHz mono: roughly `2 bytes * 16000 * seconds` for the `data` chunk).

**Interfaces:** none (internal implementation detail of `IVoiceDevice.StartRecordingAsync`).

- [ ] **Step 1: Implement**

In `StartRecordingAsync`, replace:

```csharp
            var file = await StorageFile.GetFileFromPathAsync(_recordingPath);
            var profile = MediaEncodingProfile.CreateWav(AudioEncodingQuality.High);
            _recording = await _capture.PrepareLowLagRecordToStorageFileAsync(profile, file);
```

with:

```csharp
            var file = await StorageFile.GetFileFromPathAsync(_recordingPath);
            var profile = MediaEncodingProfile.CreateWav(AudioEncodingQuality.High);
            profile.Audio = AudioEncodingProperties.CreatePcm(sampleRate: 16000, channelCount: 1, bitsPerSample: 16);
            _recording = await _capture.PrepareLowLagRecordToStorageFileAsync(profile, file);
```

- [ ] **Step 2: Build the desktop project to confirm it compiles**

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds (0 errors). `AudioEncodingProperties` is already imported via the existing `using Windows.Media.MediaProperties;` at the top of the file.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/WindowsVoiceDevice.cs
git commit -m "fix(desktop): capture mono 16kHz PCM WAV directly instead of 48kHz stereo"
```

---

### Task 6: `AssistantViewModel` readiness wiring (mic + Core, never TTS)

**Files:**
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs`

**Interfaces:**
- Consumes: `Reva.Desktop.State.VoiceUiState` / `VoiceUiStateText` (Task 1), `IRevaCoreLifecycle` (existing, `desktop/src/Reva.Desktop/Services/IRevaCoreLifecycle.cs`: `CoreLifecycleState State`, `event EventHandler? StateChanged`).
- Produces: `AssistantViewModel(IRevaCoreClient coreClient, IVoiceDevice? voiceDevice = null, IRevaCoreLifecycle? lifecycle = null)`. New read-only `VoiceUiState VoiceState { get; }` property. `VoiceStatusText` becomes a computed wrapper: `VoiceUiStateText.For(VoiceState)`. `CanStartVoiceInput`/`CanUseVoiceButton` now require Core connected (when a `lifecycle` was supplied — `lifecycle is null` is treated as "connected" for backward compatibility with every existing test/call site that doesn't pass one).

This task only adds the gating and the `VoiceUiState`-backed status property; it does **not** yet change `FinishVoiceInputAsync`'s behavior (that's Task 7). Keep the existing auto-send/auto-speak behavior working through this task so tests stay green incrementally — Task 7 is where the old voice-turn tests actually get replaced.

- [ ] **Step 1: Write the failing tests**

Add to `AssistantViewModelTests.cs` (near the top, a small fake lifecycle):

```csharp
    private sealed class FakeCoreLifecycle : IRevaCoreLifecycle
    {
        public CoreLifecycleState State { get; set; } = CoreLifecycleState.Connected;

        public string StatusText => "Core Connected";

        public event EventHandler? StateChanged;

        public void RaiseStateChanged() => StateChanged?.Invoke(this, EventArgs.Empty);

        public Task StartAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;

        public void StopMonitoring()
        {
        }
    }
```

And these facts (place near the other voice-availability tests):

```csharp
    [Fact]
    public void CanStartVoiceInput_MicReadyButCoreDisconnected_IsFalse()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.False(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void CanStartVoiceInput_MicReadyAndCoreConnected_IsTrue()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.True(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void CanStartVoiceInput_NoLifecycleProvided_DefaultsToTrueWhenMicReady()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice());

        Assert.True(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void CanStartVoiceInput_CoreDisconnectsAfterConstruction_UpdatesLive()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);
        Assert.True(viewModel.CanStartVoiceInput);

        lifecycle.State = CoreLifecycleState.Unavailable;
        lifecycle.RaiseStateChanged();

        Assert.False(viewModel.CanStartVoiceInput);
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter "CanStartVoiceInput_MicReadyButCoreDisconnected_IsFalse|CanStartVoiceInput_MicReadyAndCoreConnected_IsTrue|CanStartVoiceInput_NoLifecycleProvided_DefaultsToTrueWhenMicReady|CanStartVoiceInput_CoreDisconnectsAfterConstruction_UpdatesLive"`
Expected: FAIL to build — no 3-arg constructor yet.

- [ ] **Step 3: Implement**

In `AssistantViewModel.cs`, add the field and change the constructor:

```csharp
    private readonly IRevaCoreLifecycle? _lifecycle;

    public AssistantViewModel(IRevaCoreClient coreClient, IVoiceDevice? voiceDevice = null, IRevaCoreLifecycle? lifecycle = null)
    {
        _coreClient = coreClient;
        _voiceDevice = voiceDevice ?? new UnavailableVoiceDevice();
        _lifecycle = lifecycle;
        _isVoiceAvailable = _voiceDevice.IsAvailable;
        _voiceStatusText = _isVoiceAvailable ? "Voice Ready" : "Voice Unavailable";
        if (_lifecycle is not null)
        {
            _lifecycle.StateChanged += OnLifecycleStateChanged;
        }
    }

    private bool IsCoreConnected => _lifecycle is null || _lifecycle.State == CoreLifecycleState.Connected;

    private void OnLifecycleStateChanged(object? sender, EventArgs e) => RaiseVoiceAvailabilityProperties();
```

Update the two gating properties:

```csharp
    public bool CanUseVoiceButton => _isVoiceAvailable && IsCoreConnected && !IsPending;

    public bool CanStartVoiceInput => _isVoiceAvailable && IsCoreConnected && !IsPending && !IsVoiceBusy;
```

(Leave `VoiceStatusText`, `RefreshVoiceAvailabilityAsync`, `FinishVoiceInputAsync`, etc. untouched in this task — that's Task 7.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: PASS — all pre-existing tests still pass (none of them pass a `lifecycle`, so `IsCoreConnected` defaults to `true`, preserving current behavior) plus the 4 new tests.

- [ ] **Step 5: Wire `MainWindow.xaml.cs` to pass the lifecycle through**

In `MainWindow.xaml.cs`, change:

```csharp
        Assistant = new AssistantViewModel(coreClient, voiceDevice, lifecycle);
```

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/src/Reva.Desktop/MainWindow.xaml.cs desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "feat(desktop): gate Hold-to-Talk on Core connectivity, never on TTS"
```

---

### Task 7: Rewrite `FinishVoiceInputAsync` — transcription-only, `VoiceUiState`-backed

This is the core behavior change: stop after transcription, populate the composer, never call `SendMessageCoreAsync` or `SynthesizeSpeechAsync`/`PlayAsync` from the voice path.

**Files:**
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs`

**Interfaces:**
- Consumes: `WavAudio.TryGetDurationMs` (Task 2), `VoiceUiState`/`VoiceUiStateText` (Task 1).
- Produces: `AssistantViewModel.VoiceState` transitions through `ReadyToTalk`/`NoMicrophone`/`PermissionDenied`/`SttUnavailable` (idle states) → `Listening` (on press) → `Transcribing` (on release) → `TranscriptionReady` | `TranscriptionFailed` | `SttUnavailable` (terminal states after release). `ComposerText` is set to the transcribed text on success. `IsSpeaking`, `StopSpeaking()`, `CanStopSpeaking`, the `SynthesizeSpeechAsync`/`PlayAsync` calls, and `VoiceLanguageResolver` usage in the voice-turn method are all removed from `FinishVoiceInputAsync` (leave `StopSpeaking()`/`IsSpeaking`/`CanStopSpeaking` as public members — `MainWindow.xaml`'s `StopSpeakingButton` still binds to them — just nothing in the voice-turn path ever sets `IsSpeaking = true` anymore, so the button is permanently disabled, which is correct: this slice never produces speech to stop).

- [ ] **Step 1: Replace the voice-turn test block in `AssistantViewModelTests.cs`**

Delete everything from `VoiceTurn_TranscribesThenUsesExistingMessagePipelineThenSpeaksReply` (line ~349) through `StopSpeaking_HaltsActivePlaybackImmediately` (end of class, ~line 631) and replace with:

```csharp
    [Fact]
    public async Task VoiceTurn_PressBeginsRecordingOnce()
    {
        var client = ImmediateSuccessClient();
        var voiceDevice = new FakeVoiceDevice();
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StartCallCount);
        Assert.Equal(0, voiceDevice.StopCallCount);
        Assert.True(viewModel.IsMicrophoneActive);
        Assert.Equal(VoiceUiState.Listening, viewModel.VoiceState);
        Assert.Equal("Listening", viewModel.VoiceStatusText);
    }

    [Fact]
    public async Task VoiceTurn_ReleaseStopsRecordingOnce_TranscribesOnce_PopulatesComposer_NeverSendsOrSpeaks()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException("transcription-only slice must never call SendMessageAsync"),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello REVA"))),
            (_, _, _) => throw new NotSupportedException("transcription-only slice must never call SynthesizeSpeechAsync"));
        var voiceDevice = new FakeVoiceDevice(recordedAudio: OneSecondMonoWav());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StartCallCount);
        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
        Assert.Equal(0, client.CallCount);
        Assert.Equal(0, client.SynthesizeCallCount);
        Assert.Equal(0, voiceDevice.PlayCallCount);
        Assert.Equal("hello REVA", viewModel.ComposerText);
        Assert.Empty(viewModel.Messages); // nothing auto-sent to the transcript
        Assert.Equal(VoiceUiState.TranscriptionReady, viewModel.VoiceState);
        Assert.Equal("Transcription Ready", viewModel.VoiceStatusText);
        Assert.False(viewModel.IsMicrophoneActive);
    }

    [Fact]
    public async Task VoiceTurn_CanceledPointerStopsSafely()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => throw new NotSupportedException());
        var voiceDevice = new FakeVoiceDevice(recordedAudio: OneSecondMonoWav());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // pointer-canceled routes through the same FinishVoiceInputAsync as release

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.False(viewModel.IsMicrophoneActive);
    }

    [Fact]
    public async Task VoiceTurn_CaptureLossStopsSafely()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => throw new NotSupportedException());
        var voiceDevice = new FakeVoiceDevice(recordedAudio: OneSecondMonoWav());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // pointer-capture-lost routes through the same FinishVoiceInputAsync

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.False(viewModel.IsMicrophoneActive);
    }

    [Fact]
    public async Task VoiceTurn_DuplicateReleaseIsIgnored_StopsExactlyOnce()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => throw new NotSupportedException());
        var voiceDevice = new FakeVoiceDevice(recordedAudio: OneSecondMonoWav());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // duplicate — e.g. release followed by capture-lost

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
    }

    [Fact]
    public async Task VoiceTurn_ReleaseWhileStartupInProgress_WaitsThenStopsOnce()
    {
        var recordingStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var allowRecordingToStart = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hello"))),
            (_, _, _) => throw new NotSupportedException());
        var voiceDevice = new FakeVoiceDevice(
            recordedAudio: OneSecondMonoWav(),
            recordingStarted: recordingStarted,
            allowRecordingToStart: allowRecordingToStart);
        var viewModel = new AssistantViewModel(client, voiceDevice);

        var startTask = viewModel.StartVoiceInputAsync();
        await recordingStarted.Task;
        var finishTask = viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, voiceDevice.StopCallCount);

        allowRecordingToStart.SetResult();
        await startTask;
        await finishTask;

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
    }

    [Fact]
    public async Task VoiceTurn_EmptyRecordingIsRejectedBeforeTranscription()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => throw new NotSupportedException(),
            (_, _, _) => throw new NotSupportedException());
        var voiceDevice = new FakeVoiceDevice(recordedAudio: Array.Empty<byte>());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(0, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
        Assert.NotNull(viewModel.VoiceErrorMessage);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_UnderTwoHundredFiftyMillisecondsIsRejectedBeforeTranscription()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => throw new NotSupportedException(),
            (_, _, _) => throw new NotSupportedException());
        var shortWav = MonoWavOfDuration(TimeSpan.FromMilliseconds(100));
        var voiceDevice = new FakeVoiceDevice(recordedAudio: shortWav);
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
        Assert.Contains("too short", viewModel.VoiceErrorMessage, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_ExactlyTwoHundredFiftyMillisecondsIsAccepted()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("ok"))),
            (_, _, _) => throw new NotSupportedException());
        var exactWav = MonoWavOfDuration(TimeSpan.FromMilliseconds(250));
        var voiceDevice = new FakeVoiceDevice(recordedAudio: exactWav);
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionReady, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceTurn_TranscriptionFailure_ServiceUnavailable_ShowsSttUnavailable_NeverAddsToChat()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Failure(
                CoreErrorKind.CoreUnavailable,
                "REVA voice is unavailable.")),
            (_, _, _) => throw new NotSupportedException());
        var viewModel = new AssistantViewModel(client, new FakeVoiceDevice(recordedAudio: OneSecondMonoWav()));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Empty(viewModel.Messages);
        Assert.Equal(0, client.CallCount);
        Assert.Equal("REVA voice is unavailable.", viewModel.VoiceErrorMessage);
        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_TranscriptionFailure_Timeout_ShowsSttUnavailable_WithVoiceSpecificMessage()
    {
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Failure(
                CoreErrorKind.CoreTimeout,
                "REVA voice did not respond in time.")),
            (_, _, _) => throw new NotSupportedException());
        var viewModel = new AssistantViewModel(client, new FakeVoiceDevice(recordedAudio: OneSecondMonoWav()));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal("REVA voice did not respond in time.", viewModel.VoiceErrorMessage);
        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceFailure_DoesNotBreakTypedChat()
    {
        var client = ImmediateSuccessClient("Received: typed still works");
        var voiceDevice = new FakeVoiceDevice(
            startException: new VoiceCaptureException(VoiceDeviceAvailability.NoMicrophoneFound()));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        viewModel.ComposerText = "typed still works";
        await viewModel.SendMessageAsync();

        Assert.Equal(VoiceUiState.NoMicrophone, viewModel.VoiceState);
        Assert.Equal(1, client.CallCount);
        Assert.Equal(2, viewModel.Messages.Count);
        Assert.Equal("typed still works", viewModel.Messages[0].Text);
        Assert.Equal("Received: typed still works", viewModel.Messages[1].Text);
    }

    [Fact]
    public async Task VoiceTurn_PermissionDenied_ShowsExactRequiredMessage()
    {
        var client = ImmediateSuccessClient();
        var voiceDevice = new FakeVoiceDevice(
            startException: new VoiceCaptureException(VoiceDeviceAvailability.PermissionDenied()));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();

        Assert.False(viewModel.IsMicrophoneActive);
        Assert.False(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.PermissionDenied, viewModel.VoiceState);
        Assert.Equal(
            "Microphone permission is disabled. Enable it in Windows Settings.",
            viewModel.VoiceErrorMessage);
    }

    [Fact]
    public async Task TtsUnavailable_DoesNotDisableVoiceButton()
    {
        // No TTS provider/call path exists in this slice at all — this test
        // documents the requirement by proving SynthesizeSpeechAsync is
        // simply never invoked during a full, successful voice turn, so
        // whatever state TTS is in cannot possibly gate CanStartVoiceInput.
        var client = new FakeCoreClient(
            (_, _) => throw new NotSupportedException(),
            (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription("hi"))),
            (_, _, _) => throw new NotSupportedException("TTS must never be invoked by this slice"));
        var viewModel = new AssistantViewModel(client, new FakeVoiceDevice(recordedAudio: OneSecondMonoWav()));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.SynthesizeCallCount);
        Assert.True(viewModel.CanStartVoiceInput);
    }

    private static byte[] OneSecondMonoWav() => MonoWavOfDuration(TimeSpan.FromSeconds(1));

    private static byte[] MonoWavOfDuration(TimeSpan duration)
    {
        const int sampleRate = 16000;
        const short blockAlign = 2; // mono, 16-bit
        var dataBytes = (int)(duration.TotalSeconds * sampleRate) * blockAlign;

        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write("RIFF"u8.ToArray());
        writer.Write(36 + dataBytes);
        writer.Write("WAVE"u8.ToArray());
        writer.Write("fmt "u8.ToArray());
        writer.Write(16);
        writer.Write((short)1);
        writer.Write((short)1); // mono
        writer.Write(sampleRate);
        writer.Write(sampleRate * blockAlign);
        writer.Write(blockAlign);
        writer.Write((short)16);
        writer.Write("data"u8.ToArray());
        writer.Write(dataBytes);
        writer.Write(new byte[dataBytes]);
        return stream.ToArray();
    }
```

Also update `FakeVoiceDevice`'s default `RecordedAudio` (currently `new byte[] { 1, 2, 3 }`, which is not a valid/long-enough WAV) — change its default to `OneSecondMonoWav()` so tests that don't explicitly pass `recordedAudio` (e.g. `VoiceTurn_PressBeginsRecordingOnce`, which never reaches the duration check) keep working, and any test that *does* reach `FinishVoiceInputAsync` without an explicit override gets a valid, well-formed recording rather than 3 garbage bytes:

```csharp
        public FakeVoiceDevice(
            byte[]? recordedAudio = null,
            ...)
        {
            RecordedAudio = recordedAudio ?? OneSecondMonoWavStatic();
            ...
        }
```

(Since `FakeVoiceDevice` is a nested private class, reference the test class's own `OneSecondMonoWav()`/`MonoWavOfDuration` helpers directly — no separate static needed, just call `AssistantViewModelTests.OneSecondMonoWav()` is unnecessary since they're in the same class; use `OneSecondMonoWav()` directly as the default-value expression is not allowed for a non-const in C#, so keep the `null`-coalescing pattern in the constructor body as shown above, not as a parameter default.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: FAIL to build — `VoiceState` property doesn't exist yet, old `FinishVoiceInputAsync` still auto-sends/auto-speaks so the new assertions (`Assert.Equal(0, client.CallCount)` etc.) would fail even if it built.

- [ ] **Step 3: Implement — rewrite `FinishVoiceInputAsync` and the status model**

In `AssistantViewModel.cs`:

1. Add `using Reva.Desktop.State;` at the top.
2. Replace the `_voiceStatusText` field and `VoiceStatusText` property with a `VoiceUiState` field. `ObservableObject.SetProperty` is the minimal 3-parameter form (`ref field, value, [CallerMemberName]`) — no post-change callback overload exists, so raise the dependent `VoiceStatusText` change explicitly:

```csharp
    private VoiceUiState _voiceState = VoiceUiState.CheckingMicrophone;
```

```csharp
    public VoiceUiState VoiceState
    {
        get => _voiceState;
        private set
        {
            if (SetProperty(ref _voiceState, value))
            {
                RaisePropertyChanged(nameof(VoiceStatusText));
            }
        }
    }

    public string VoiceStatusText => VoiceUiStateText.For(VoiceState);
```

3. Update the constructor's initial state:

```csharp
        _isVoiceAvailable = _voiceDevice.IsAvailable;
        _voiceState = _isVoiceAvailable ? VoiceUiState.ReadyToTalk : VoiceUiState.CheckingMicrophone;
```

4. Update `RefreshVoiceAvailabilityAsync`:

```csharp
    public async Task RefreshVoiceAvailabilityAsync(CancellationToken cancellationToken = default)
    {
        VoiceState = VoiceUiState.CheckingMicrophone;
        try
        {
            var availability = await _voiceDevice.VerifyAvailabilityAsync(cancellationToken);
            _isVoiceAvailable = availability.IsReady;
            VoiceState = MapAvailability(availability);
            VoiceErrorMessage = availability.IsReady ? null : availability.SafeMessage;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            _isVoiceAvailable = false;
            VoiceState = VoiceUiState.NoMicrophone;
            VoiceErrorMessage = VoiceDeviceAvailability.RecordingFailed().SafeMessage;
        }
        finally
        {
            RaiseVoiceAvailabilityProperties();
        }
    }

    private static VoiceUiState MapAvailability(VoiceDeviceAvailability availability) => availability.Kind switch
    {
        VoiceDeviceAvailabilityKind.Ready => VoiceUiState.ReadyToTalk,
        VoiceDeviceAvailabilityKind.PermissionDenied => VoiceUiState.PermissionDenied,
        VoiceDeviceAvailabilityKind.NoMicrophoneFound => VoiceUiState.NoMicrophone,
        _ => VoiceUiState.NoMicrophone,
    };
```

5. Update `StartVoiceInputAsync` — replace the `VoiceStatusText = "Listening…"` line and the reset-on-cancel line:

```csharp
        VoiceState = VoiceUiState.Listening;
```

```csharp
        catch (OperationCanceledException)
        {
            IsMicrophoneActive = false;
            IsVoiceBusy = false;
            VoiceState = _isVoiceAvailable ? VoiceUiState.ReadyToTalk : VoiceUiState.NoMicrophone;
        }
```

6. Replace `FinishVoiceInputAsync` entirely:

```csharp
    public async Task FinishVoiceInputAsync(CancellationToken cancellationToken = default)
    {
        if (!IsMicrophoneActive)
        {
            return;
        }

        var turnCancellation = _voiceTurnCancellation;
        var linkedToken = turnCancellation?.Token ?? cancellationToken;
        IsMicrophoneActive = false;
        VoiceState = VoiceUiState.Transcribing;

        try
        {
            if (_recordingStartTask is not null)
            {
                await _recordingStartTask;
            }

            var audio = await _voiceDevice.StopRecordingAsync(linkedToken);
            if (audio.Length == 0 || !WavAudio.TryGetDurationMs(audio, out var durationMs) || durationMs < 250)
            {
                VoiceErrorMessage = audio.Length == 0
                    ? "No voice audio was captured."
                    : "Recording is too short. Hold the button and speak for at least a quarter second.";
                VoiceState = VoiceUiState.TranscriptionFailed;
                return;
            }

            var transcription = await _coreClient.TranscribeSpeechAsync(audio, linkedToken);
            if (!transcription.IsSuccess)
            {
                ApplyVoiceFailure(transcription.Error!);
                return;
            }

            ComposerText = transcription.Value!.Text;
            VoiceErrorMessage = null;
            VoiceState = VoiceUiState.TranscriptionReady;
        }
        catch (OperationCanceledException)
        {
            VoiceState = _isVoiceAvailable ? VoiceUiState.ReadyToTalk : VoiceUiState.NoMicrophone;
        }
        catch (VoiceCaptureException ex)
        {
            ApplyVoiceCaptureFailure(ex.Availability);
        }
        catch (Exception)
        {
            VoiceErrorMessage = VoiceDeviceAvailability.RecordingFailed().SafeMessage;
            VoiceState = VoiceUiState.TranscriptionFailed;
        }
        finally
        {
            _recordingStartTask = null;
            IsVoiceBusy = false;
        }
    }
```

7. Update `ApplyVoiceFailure` and `ApplyVoiceCaptureFailure`:

```csharp
    private void ApplyVoiceFailure(CoreError error)
    {
        VoiceErrorMessage = error.SafeMessage;
        VoiceState = error.Kind is CoreErrorKind.CoreUnavailable or CoreErrorKind.CoreTimeout
            ? VoiceUiState.SttUnavailable
            : VoiceUiState.TranscriptionFailed;
    }

    private void ApplyVoiceCaptureFailure(VoiceDeviceAvailability availability)
    {
        _isVoiceAvailable = false;
        VoiceState = MapAvailability(availability);
        VoiceErrorMessage = availability.SafeMessage;
        IsMicrophoneActive = false;
        IsVoiceBusy = false;
        RaiseVoiceAvailabilityProperties();
    }
```

8. Delete now-dead members: `IsSpeaking` setter usage inside the voice turn is gone, but leave the `IsSpeaking`/`CanStopSpeaking`/`StopSpeaking()` members themselves (still bound from XAML per this task's Interfaces note) — do **not** delete them. Delete `VoiceLanguageResolver` usage from this file if that using/call was only referenced here (leave the `VoiceLanguageResolver` class itself alone; it's out of scope — just remove the now-unused call site). Remove the `_speechPlaybackCancellation` creation from `FinishVoiceInputAsync` (already gone in the rewrite above) — but keep the field and `StopSpeaking()`'s use of it, since `StopSpeaking()` is still a live public method.

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: PASS — every test in the file, both the untouched typed-chat tests and the rewritten voice-turn tests.

- [ ] **Step 5: Run the full suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "feat(desktop): make Hold-to-Talk transcription-only (no auto-send, no auto-speak)"
```

---

### Task 8: Wire the composer `TextBox` + startup readiness check

**Files:**
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml.cs`

**Interfaces:**
- Consumes: `AssistantViewModel.ComposerText`, `AssistantViewModel.VoiceState` (Task 7).

The x:Bind `TwoWay` LostFocus-commit gap (documented at `MainWindow.xaml.cs:66-81`, `SyncComposerTextFromTextBox`) means setting `Assistant.ComposerText` alone from a background continuation does update the bound `ComposerBox.Text` in practice for WinUI `x:Bind` **from ViewModel to View** (that direction is a normal `PropertyChanged`-driven push, not the LostFocus-gated direction — the LostFocus gap only affects the View → ViewModel direction, i.e. reading what the user typed). Confirm this understanding before adding a redundant write: read `desktop/src/Reva.Desktop/State/ObservableObject.cs` to confirm `SetProperty` raises `PropertyChanged`, and confirm `ComposerBox.Text="{x:Bind Assistant.ComposerText, Mode=TwoWay}"` — TwoWay `x:Bind` always reacts to source `PropertyChanged` immediately regardless of the LostFocus quirk (the quirk is specifically about the control committing user edits back to the source). If that holds, **no code-behind change is needed** for the ComposerBox to visually update — `ComposerText = transcription.Value!.Text;` in Task 7 already suffices.

- [ ] **Step 1: Verify by inspection**

Read `desktop/src/Reva.Desktop/State/ObservableObject.cs` in full and confirm `SetProperty` calls a `PropertyChanged` event synchronously. Read the WinUI x:Bind TwoWay semantics comment at `MainWindow.xaml.cs:66-77` again carefully — it says TwoWay "only commits to the ViewModel on LostFocus", which is the View→ViewModel direction. Nothing in that comment claims ViewModel→View pushes are delayed.

- [ ] **Step 2: Add a manual verification note (no code change) — confirmed in Task 9's real run**

If Task 9's manual run shows the `ComposerBox` does *not* visually update after a successful transcription, add this fallback in `FinishVoiceInputAsync`'s success branch is not possible (ViewModel can't touch WinUI types) — instead add an event on `AssistantViewModel`:

```csharp
    public event EventHandler<string>? TranscriptionCompleted;
```

fired right after `ComposerText = transcription.Value!.Text;`, and in `MainWindow.xaml.cs`'s constructor:

```csharp
        Assistant.TranscriptionCompleted += (_, text) => ComposerBox.Text = text;
```

Only add this if Task 9 actually observes a stale textbox — do not add speculative code for a gap that WinUI's TwoWay x:Bind doesn't actually have in the ViewModel→View direction. Document which outcome occurred in the Task 9 report.

- [ ] **Step 3: Build**

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds (this task may end up being a no-op code change plus a documented verification — that's an acceptable outcome, not a failure to complete the task).

- [ ] **Step 4: Commit (only if Step 2's fallback was needed)**

```bash
git add desktop/src/Reva.Desktop/MainWindow.xaml.cs desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs
git commit -m "fix(desktop): push transcription text into the live ComposerBox explicitly"
```

---

### Task 9: Real-microphone acceptance run and final commit

**Files:** none (verification task).

- [ ] **Step 1: Full automated suite, one last time**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures. This must be green before touching the physical microphone.

- [ ] **Step 2: Build Release**

Run: `dotnet build desktop/Reva.Desktop.sln -c Release`
Expected: succeeds. Locate the produced executable (`desktop/src/Reva.Desktop/bin/Release/net10.0-windows10.0.19041.0/Reva.Desktop.exe` or similar — confirm the exact path from the build output).

- [ ] **Step 3: Ensure `reva_core` is reachable**

The desktop app expects Core at `http://127.0.0.1:8756/` (loopback, see `DesktopConfiguration`). Start `reva_core` per its normal run instructions (check `reva_core/README.md` or the repo's top-level docs if unsure of the exact launch command) before launching the desktop exe, or let `App.xaml.cs`'s `RevaCoreLifecycle` launch it automatically if that's how this repo already runs Core (check `CoreProcessLauncher`/`DeveloperModeCoreExecutableLocator` usage in `App.xaml.cs` — if Core auto-launches, no separate step is needed).

- [ ] **Step 4: Run the Release executable**

Launch the exe from Step 2. Wait for `CoreStatusText` to show "Core Connected" and `VoiceStatusText` to show "Ready to Talk".

- [ ] **Step 5: Physical hold-to-talk test**

Hold the physical mouse button down on the "Hold to Talk" button. Say: "Hey Reva, this is a microphone transcription test." Release the button.

- [ ] **Step 6: Observe and record**

Confirm:
- `VoiceStatusText` transitioned `Listening` → `Transcribing` → `Transcription Ready`.
- The `ComposerBox` now contains text that is exact or meaning-equivalent to "Hey Reva, this is a microphone transcription test."
- The message did **not** get auto-sent — `MessageList` gained no new entries from this action, and the message is still sitting in `ComposerBox` editable.
- No TTS/speech playback occurred (no audio played back, `StopSpeakingButton` stayed disabled throughout).

- [ ] **Step 7: Report the required metrics**

Record and report: capture duration (from press to release, observable via a stopwatch or the recorded WAV's own duration once retrieved — if `WindowsVoiceDevice` still has the temp WAV file path accessible during a debug session, note its file size in bytes; otherwise time press-to-release manually), STT latency (time from release to `Transcription Ready`, observable via a stopwatch), and the exact recognized text now sitting in the composer box.

- [ ] **Step 8: If it fails, diagnose before retrying**

If `VoiceStatusText` shows `STT Unavailable`, `Permission Denied`, or `No Microphone` instead of proceeding through the flow, that's a real environment/config issue to fix (Core not running, mic permission off, no mic device) — not a reason to weaken the implementation. Fix the actual cause, rebuild if code changed, and repeat from Step 4.

- [ ] **Step 9: Commit is already done incrementally — tag completion**

Every implementation task (1-8) already ended with its own commit. This step is the acceptance gate confirming those commits are safe to consider the slice "done," not a new commit by itself. If Step 6/7 surfaced any last-mile fix (e.g. Task 8's fallback), commit that now:

```bash
git status
git add -A
git commit -m "fix(desktop): address real-microphone acceptance findings"
```

(Skip this if there's nothing uncommitted — `git status` should be clean if Tasks 1-8 already committed everything.)

- [ ] **Step 10: Report to the user**

Summarize: capture duration, WAV size, STT latency, recognized text, and explicit confirmation that no assistant (`/v1/messages`) request and no TTS (`/v1/voice/speech`) request occurred during the run (cross-check against `reva_core`'s own request logs / audit log if available, e.g. `voice_transcription_completed` present, `voice_speech_completed` absent, for this run's correlation window).

---

## Self-Review Notes

- **Spec coverage:** readiness (Task 6), UI states (Tasks 1, 6, 7), permission message (Task 3), capture format (Task 5), duration validation + 250ms rejection (Tasks 2, 7), timeouts (Tasks 3, 4), cancellation restores ready state (Task 7 `OperationCanceledException` branch), all 12 required tests (Tasks 6-7's test additions cover press/release/cancel/capture-lost/duplicate-release/empty-rejected/permission-denied/STT-timeout/composer-populated/not-auto-sent/TTS-unaffected/typed-chat-still-works), real acceptance run (Task 9).
- **No backend changes** anywhere in this plan, per the confirmed design decision.
- **Type consistency check:** `VoiceUiState`/`VoiceUiStateText` (Task 1) used identically in Tasks 6-7. `WavAudio.TryGetDurationMs` (Task 2) signature used identically in Task 7. `AssistantViewModel`'s 3-arg constructor (Task 6) used identically in Task 9's manual run expectations and nowhere contradicted later. `DesktopConfiguration`'s 4-arg constructor (Task 3) and `RevaCoreClient`'s 4-arg constructor (Task 4) are both consumed consistently in `App.xaml.cs` (Task 4, Step 5).
