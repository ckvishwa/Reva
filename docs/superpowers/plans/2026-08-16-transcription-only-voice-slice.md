# Transcription-Only Voice Slice Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Revision note (v2):** supersedes v1. Changes: added Task 0 (interface reconnaissance) so no task guesses an API surface; fixed the `HttpClient.Timeout = Infinite` regression that would have left `SendBytesAsync` with no timeout at all; corrected the false claim that the `OperationCanceledException` catch is not a behavior change, and added cancellation-semantics coverage; made `VoiceState` reflect Core connectivity so status and button-enablement can never contradict each other; added UI-thread marshalling for lifecycle events; added empty-transcript rejection, composer-draft preservation, error-message clearing, temp-WAV cleanup, and capture-format fallback; replaced the two placebo timeout tests with tests that actually fail before the fix; folded v1's Task 8 into the acceptance run.

**Goal:** Turn the existing Hold-to-Talk voice turn (which today auto-sends the transcript to Core and auto-plays a TTS reply) into a transcription-only slice: mic capture → STT → populate the composer textbox → stop. Fix the readiness/status contradictions along the way (mic vs. Core vs. TTS are currently tangled).

**Architecture:** All changes are desktop-only (`desktop/src/Reva.Desktop`), no `reva_core` backend changes. `AssistantViewModel.FinishVoiceInputAsync` drops its calls to `SendMessageCoreAsync`/`SynthesizeSpeechAsync`/`PlayAsync` and instead writes the transcription into `ComposerText`. A new `VoiceUiState` enum replaces the two loose "Voice Ready"/"Voice Unavailable" strings with the nine states the spec requires, and that state is computed from **both** mic readiness and Core connectivity so the displayed status always agrees with whether the button is enabled. Hold-to-Talk is gated on mic readiness AND Core connectivity (via a new optional `IRevaCoreLifecycle` dependency on `AssistantViewModel`) — never on TTS. `RevaCoreClient` gets per-call timeouts for **every** outbound call, with a dedicated longer timeout for transcription, and its `SendAsync` timeout-message bug (voice calls surfacing the generic "REVA Core did not respond in time." instead of the voice-specific message) gets fixed. `WindowsVoiceDevice` captures mono 16kHz PCM WAV directly, with a fallback for hardware that rejects that profile.

**Tech Stack:** C# / .NET (net10.0-windows10.0.19041.0), WinUI 3, WinRT `Windows.Media.Capture`, xUnit.

## Global Constraints

- STT only — no ADK/assistant auto-invoke, no TTS invocation, from the voice-turn code path (verbatim: "Strict scope: STT only... Do not invoke ADK/assistant automatically. Do not invoke TTS.").
- Never log captured audio or transcript content. Logging the `VoiceUiState` transition and the `CoreErrorKind` **is** permitted and is required by Task 7 — neither carries audio or transcript content, and without it Task 9's failure diagnosis is guesswork.
- The captured WAV must not outlive the turn on disk. Verify deletion (Task 5, Step 3) — an undeleted temp recording is a larger privacy surface than any log line.
- TTS availability must not affect mic/STT readiness or the Hold-to-Talk enabled state.
- No `reva_core` / Python changes — this slice is desktop-only (design decision, see `docs/superpowers/specs/2026-08-16-transcription-only-voice-slice-design.md`).
- Required exact UI status strings: `Checking Microphone`, `Ready to Talk`, `Listening`, `Transcribing`, `Transcription Ready`, `Permission Denied`, `No Microphone`, `STT Unavailable`, `Transcription Failed`.
- Required exact permission message: `Microphone permission is disabled. Enable it in Windows Settings.`
- Recordings under 250ms must be rejected with a safe message, before any Core call.
- Capture format: mono PCM WAV, 16kHz.
- **No status/enablement contradictions.** If `CanStartVoiceInput` is false, `VoiceStatusText` must say why. The nine allowed strings have no "Core Offline" member, so Core-disconnected maps to `STT Unavailable` (accurate: STT cannot run without Core).
- Commit the feature only after the real-microphone acceptance run passes (last task in this plan). Follow each task's own commit step; small WIP commits are fine on this branch (`phase/1b-windows-desktop`), but the task's final "prove it end to end" step gates calling the work done.

---

## File Structure

- `desktop/src/Reva.Desktop/State/VoiceUiState.cs` — **new**. Enum with the 9 states + a static `ToDisplayText` mapping.
- `desktop/src/Reva.Desktop/Services/VoiceDeviceAvailability.cs` — **modify**. Update `PermissionDenied()` message text.
- `desktop/src/Reva.Desktop/Services/WavAudio.cs` — **new**. Static helper: `TryGetDurationMs(byte[]? wav, out int durationMs)`, mirrors `reva_core/api/routes.py`'s `_read_wav_metadata`/`_validate_wav_upload` RIFF/WAVE parsing.
- `desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs` — **modify**. Add `SttRequestTimeout` + public default constants + `REVA_DESKTOP_STT_TIMEOUT_SECONDS` env override.
- `desktop/src/Reva.Desktop/Services/RevaCoreClient.cs` — **modify**. Constructor takes timeouts; per-call CTS on **all** send paths including `SendBytesAsync`; `TranscribeSpeechAsync` uses the STT timeout; timeout catch becomes voice-aware.
- `desktop/src/Reva.Desktop/Services/WindowsVoiceDevice.cs` — **modify**. Force mono/16kHz PCM in `StartRecordingAsync`, with fallback; confirm temp-file cleanup.
- `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs` — **modify**. New `IRevaCoreLifecycle?` constructor parameter, `VoiceUiState`-based status computed from mic + Core, UI-thread-safe lifecycle handling, rewritten `FinishVoiceInputAsync` (transcription-only), WAV duration validation, empty-transcript rejection.
- `desktop/src/Reva.Desktop/MainWindow.xaml.cs` — **modify**. Pass `lifecycle` into `AssistantViewModel`.
- `desktop/src/Reva.Desktop/MainWindow.xaml` — **modify**. Collapse the now-permanently-dead `StopSpeakingButton`.
- `desktop/src/Reva.Desktop/App.xaml.cs` — **modify**. HttpClient backstop timeout; pass both timeouts into `RevaCoreClient`.
- `desktop/tests/Reva.Desktop.Tests/Unit/WavAudioTests.cs` — **new**.
- `desktop/tests/Reva.Desktop.Tests/Unit/VoiceUiStateTests.cs` — **new**.
- `desktop/tests/Reva.Desktop.Tests/Unit/VoiceDeviceAvailabilityTests.cs` — **new**.
- `desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs` — **new or modify** (Task 0 confirms which).
- `desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreClientTests.cs` — **modify**. Add real timeout-selection and cancellation-semantics tests.
- `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs` — **modify**. Replace the voice-turn test block with the transcription-only test set. Typed-chat tests are untouched.
- `desktop/tests/Reva.Desktop.Tests/Unit/TestWav.cs` — **new**. Shared WAV builder used by both `WavAudioTests` and `AssistantViewModelTests` (v1 duplicated this builder in two files).

---

### Task 0: Interface reconnaissance (no code changes)

Six later tasks assume API surfaces that were never verified. A wrong guess here blocks Task 6 entirely and silently weakens Task 3 and Task 8. Spend ten minutes reading before writing anything.

**Files:** none (read-only).

- [ ] **Step 1: Record the actual shape of each assumed API**

Read and note, verbatim, into a scratch file (`docs/superpowers/specs/2026-08-16-voice-slice-recon.md`):

1. `desktop/src/Reva.Desktop/Services/IRevaCoreLifecycle.cs` — full member list, and the exact member names of `CoreLifecycleState` (the plan assumes `Connected` and `Unavailable`; if they differ, fix every reference in Tasks 6/7 before starting them).
2. Whether `IRevaCoreLifecycle.StateChanged` is raised from a background thread. Find the raise site — a timer, a poll loop, or an `await` continuation without a dispatcher hop all mean **yes**. Note how `CoreStatusText` currently survives this (it may already marshal, or it may be a latent bug).
3. `desktop/src/Reva.Desktop/State/ObservableObject.cs` — the exact name and accessibility of the `PropertyChanged`-raising method (the plan writes `RaisePropertyChanged`; it may be `OnPropertyChanged`), and confirm `SetProperty` raises synchronously.
4. `RevaCoreClient.SendBytesAsync` — does it create its own `CancellationTokenSource`, or does it rely entirely on `HttpClient.Timeout`? **This determines whether Task 4 Step 5 is a one-line change or a regression.**
5. Every current call site of `RevaCoreClient`'s methods, and whether each caller has a `catch (OperationCanceledException)`. Needed for Task 4 Step 4.
6. `WindowsVoiceDevice` — where `_recordingPath` is written, and whether that file is deleted after `StopRecordingAsync` returns.
7. Whether `desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs` already exists (v1 asked this mid-task; do it up front).
8. Whether `MainWindow.xaml.cs` calls `RefreshVoiceAvailabilityAsync` at startup. If it does not, `VoiceState` will sit on `Checking Microphone` forever for an unavailable device — Task 6 must add the call.
9. `FakeHttpMessageHandler` in the test project — what factory methods exist (`ThrowingTimeout`, `ReturningStatus`, …). Task 4 needs a delaying one; note whether you must add it.
10. Whether `Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread()` returns `null` (rather than throwing) when called from an xUnit test thread. Confirm with a five-line throwaway test; Task 6's marshalling depends on it.

- [ ] **Step 2: Reconcile**

For every assumption above that turned out wrong, edit this plan's affected task before implementing it. Do not "adapt while coding" — a silently-renamed enum member becomes a compile error three tasks later with no obvious cause.

- [ ] **Step 3: Commit the recon note**

```bash
git add docs/superpowers/specs/2026-08-16-voice-slice-recon.md
git commit -m "docs(desktop): record verified interface surfaces for the voice slice"
```

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

    [Fact]
    public void For_CoversEveryEnumMember()
    {
        // Guards against a future state being added without its required string.
        foreach (VoiceUiState state in Enum.GetValues<VoiceUiState>())
        {
            Assert.False(string.IsNullOrWhiteSpace(VoiceUiStateText.For(state)));
        }
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
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/State/VoiceUiState.cs desktop/tests/Reva.Desktop.Tests/Unit/VoiceUiStateTests.cs
git commit -m "feat(desktop): add VoiceUiState enum with required status text"
```

---

### Task 2: WAV duration validation helper

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/WavAudio.cs`
- Create: `desktop/tests/Reva.Desktop.Tests/Unit/TestWav.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/WavAudioTests.cs`

**Interfaces:**
- Produces: `static class WavAudio { public static bool TryGetDurationMs(byte[]? wav, out int durationMs) }`. Returns `false` (with `durationMs = 0`) for null/empty input, malformed RIFF/WAVE, an unreadable `fmt `/`data` chunk, or a declared chunk size that doesn't fit the buffer. On success, `durationMs = (int)Math.Round(dataBytes / (double)blockAlign / sampleRate * 1000)`.
- Produces: `static class TestWav { public static byte[] Mono16k(TimeSpan duration); public static byte[] Build(int sampleRate, short channels, short bitsPerSample, int dataBytes); }` — shared by both test files.

- [ ] **Step 1: Write the shared builder**

```csharp
namespace Reva.Desktop.Tests.Unit;

internal static class TestWav
{
    public static byte[] Mono16k(TimeSpan duration)
    {
        const int sampleRate = 16000;
        const short blockAlign = 2; // mono, 16-bit
        var dataBytes = (int)Math.Round(duration.TotalSeconds * sampleRate) * blockAlign;
        return Build(sampleRate, channels: 1, bitsPerSample: 16, dataBytes: dataBytes);
    }

    public static byte[] Build(int sampleRate, short channels, short bitsPerSample, int dataBytes)
    {
        short blockAlign = (short)(channels * bitsPerSample / 8);
        int byteRate = sampleRate * blockAlign;

        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write("RIFF"u8.ToArray());
        writer.Write(36 + dataBytes);
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
}
```

- [ ] **Step 2: Write the failing test**

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WavAudioTests
{
    [Fact]
    public void TryGetDurationMs_OneSecond16kHzMono_Returns1000()
    {
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.FromSeconds(1)), out var durationMs);

        Assert.True(ok);
        Assert.Equal(1000, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_100Milliseconds_Returns100()
    {
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.FromMilliseconds(100)), out var durationMs);

        Assert.True(ok);
        Assert.Equal(100, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_Exactly250Milliseconds_Returns250()
    {
        // Boundary that Task 7's acceptance rule depends on.
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.FromMilliseconds(250)), out var durationMs);

        Assert.True(ok);
        Assert.Equal(250, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_Null_ReturnsFalse()
    {
        var ok = WavAudio.TryGetDurationMs(null, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
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
        var ok = WavAudio.TryGetDurationMs(TestWav.Mono16k(TimeSpan.Zero), out var durationMs);

        Assert.True(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_DeclaredDataSizeExceedsBuffer_ReturnsFalse()
    {
        var wav = TestWav.Mono16k(TimeSpan.FromSeconds(1));
        // Corrupt the data chunk size to claim far more bytes than are present.
        BitConverter.GetBytes(int.MaxValue).CopyTo(wav, 40);

        var ok = WavAudio.TryGetDurationMs(wav, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }

    [Fact]
    public void TryGetDurationMs_ChunkSizeAboveIntMaxValue_ReturnsFalseNotNegative()
    {
        // Guards the unchecked (int) cast: 0xFFFFFFFF must not become -1 and
        // slip past the bounds check as a "smaller" value.
        var wav = TestWav.Mono16k(TimeSpan.FromSeconds(1));
        BitConverter.GetBytes(uint.MaxValue).CopyTo(wav, 40);

        var ok = WavAudio.TryGetDurationMs(wav, out var durationMs);

        Assert.False(ok);
        Assert.Equal(0, durationMs);
    }
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WavAudioTests`
Expected: FAIL (build error — `WavAudio` doesn't exist yet)

- [ ] **Step 4: Write minimal implementation**

```csharp
using System.Buffers.Binary;
using System.Text;

namespace Reva.Desktop.Services;

public static class WavAudio
{
    public static bool TryGetDurationMs(byte[]? wav, out int durationMs)
    {
        durationMs = 0;
        if (wav is null || wav.Length < 12 || !Tag(wav, 0, "RIFF") || !Tag(wav, 8, "WAVE"))
        {
            return false;
        }

        var offset = 12;
        var sampleRate = 0;
        var blockAlign = 0;
        long dataBytes = -1;

        while (offset + 8 <= wav.Length)
        {
            var chunkId = Encoding.ASCII.GetString(wav, offset, 4);
            var chunkSize = BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(offset + 4, 4));
            if (chunkSize > int.MaxValue)
            {
                return false;
            }

            long chunkStart = offset + 8;
            long chunkEnd = chunkStart + chunkSize;
            if (chunkEnd > wav.Length)
            {
                return false;
            }

            if (chunkId == "fmt " && chunkSize >= 16)
            {
                sampleRate = (int)BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan((int)chunkStart + 4, 4));
                blockAlign = BinaryPrimitives.ReadUInt16LittleEndian(wav.AsSpan((int)chunkStart + 12, 2));
            }
            else if (chunkId == "data")
            {
                dataBytes = chunkSize;
            }

            offset = (int)(chunkEnd + (chunkSize % 2));
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
        Encoding.ASCII.GetString(data, offset, 4) == tag;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WavAudioTests`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/WavAudio.cs desktop/tests/Reva.Desktop.Tests/Unit/WavAudioTests.cs desktop/tests/Reva.Desktop.Tests/Unit/TestWav.cs
git commit -m "feat(desktop): add WAV duration parsing for capture validation"
```

---

### Task 3: Permission message text + `DesktopConfiguration.SttRequestTimeout`

**Files:**
- Modify: `desktop/src/Reva.Desktop/Services/VoiceDeviceAvailability.cs:20-21`
- Modify: `desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/VoiceDeviceAvailabilityTests.cs` (new)
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs` (Task 0 Step 1.7 established whether this exists — if it does, add to it in its existing style)

**Interfaces:**
- Produces: `VoiceDeviceAvailability.PermissionDenied().SafeMessage == "Microphone permission is disabled. Enable it in Windows Settings."`
- Produces: `DesktopConfiguration.SttRequestTimeout` (`TimeSpan`), `public static readonly TimeSpan DefaultRequestTimeout` / `DefaultSttRequestTimeout` (single source of truth — `RevaCoreClient` consumes these in Task 4 rather than redeclaring its own literals), env override `REVA_DESKTOP_STT_TIMEOUT_SECONDS`, and a `DesktopConfiguration(Uri, string, TimeSpan requestTimeout, TimeSpan sttRequestTimeout)` constructor.

- [ ] **Step 1: Write the failing tests**

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
// DesktopConfigurationTests.cs
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

// Environment variables are process-global and xUnit parallelizes across
// classes; without this, CreateDefault() called concurrently from another
// class sees a mutated environment and fails intermittently.
[CollectionDefinition("EnvironmentVariables", DisableParallelization = true)]
public class EnvironmentVariablesCollection;

[Collection("EnvironmentVariables")]
public class DesktopConfigurationTests
{
    private const string SttEnvVar = "REVA_DESKTOP_STT_TIMEOUT_SECONDS";

    [Fact]
    public void CreateDefault_NoOverride_UsesThirtySecondSttTimeout()
    {
        var previous = Environment.GetEnvironmentVariable(SttEnvVar);
        Environment.SetEnvironmentVariable(SttEnvVar, null);
        try
        {
            Assert.Equal(TimeSpan.FromSeconds(30), DesktopConfiguration.CreateDefault().SttRequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable(SttEnvVar, previous);
        }
    }

    [Fact]
    public void CreateDefault_SttTimeoutEnvVarOverride_IsRespected()
    {
        var previous = Environment.GetEnvironmentVariable(SttEnvVar);
        Environment.SetEnvironmentVariable(SttEnvVar, "45");
        try
        {
            Assert.Equal(TimeSpan.FromSeconds(45), DesktopConfiguration.CreateDefault().SttRequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable(SttEnvVar, previous);
        }
    }

    [Theory]
    [InlineData("0")]
    [InlineData("-5")]
    [InlineData("banana")]
    [InlineData("")]
    public void CreateDefault_InvalidSttTimeoutOverride_FallsBackToDefault(string value)
    {
        var previous = Environment.GetEnvironmentVariable(SttEnvVar);
        Environment.SetEnvironmentVariable(SttEnvVar, value);
        try
        {
            Assert.Equal(TimeSpan.FromSeconds(30), DesktopConfiguration.CreateDefault().SttRequestTimeout);
        }
        finally
        {
            Environment.SetEnvironmentVariable(SttEnvVar, previous);
        }
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter "VoiceDeviceAvailabilityTests|DesktopConfigurationTests"`
Expected: FAIL — `PermissionDenied_HasRequiredSafeMessage` fails on the message-text assertion; `DesktopConfigurationTests` fails to build (no `SttRequestTimeout`, no 4-arg constructor).

- [ ] **Step 3: Implement**

In `VoiceDeviceAvailability.cs`, change line 21:

```csharp
    public static VoiceDeviceAvailability PermissionDenied() =>
        new(VoiceDeviceAvailabilityKind.PermissionDenied, "Microphone permission is disabled. Enable it in Windows Settings.");
```

In `DesktopConfiguration.cs`:

```csharp
    private const string SttRequestTimeoutSecondsEnvironmentVariable = "REVA_DESKTOP_STT_TIMEOUT_SECONDS";

    // Single source of truth — RevaCoreClient's constructor defaults reference
    // these rather than redeclaring their own literals (v1 had 10s/30s written
    // in two files, free to drift).
    public static readonly TimeSpan DefaultRequestTimeout = TimeSpan.FromSeconds(10);
    public static readonly TimeSpan DefaultSttRequestTimeout = TimeSpan.FromSeconds(30);
```

Add the property next to `RequestTimeout`:

```csharp
    public TimeSpan SttRequestTimeout { get; }
```

Replace the constructor (breaking signature change; production call sites are `CreateDefault` plus test call sites this task already touches):

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

In `CreateDefault()`, after the existing `requestTimeout` computation:

```csharp
        var sttTimeoutOverride = Environment.GetEnvironmentVariable(SttRequestTimeoutSecondsEnvironmentVariable);
        var sttRequestTimeout =
            double.TryParse(
                sttTimeoutOverride,
                System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture,
                out var sttTimeoutSeconds) && sttTimeoutSeconds > 0
                ? TimeSpan.FromSeconds(sttTimeoutSeconds)
                : DefaultSttRequestTimeout;

        return new DesktopConfiguration(baseUrl, dataDirectory, requestTimeout, sttRequestTimeout);
```

(Invariant culture is deliberate: a comma-decimal locale would otherwise reject `"45.5"` and silently fall back. Apply the same treatment to the existing `requestTimeout` parse while you're in the file.)

- [ ] **Step 4: Fix every other call site of the 3-arg constructor**

Run: `Select-String -Path desktop -Include *.cs -Recurse -Pattern "new DesktopConfiguration\("`. Update every match to pass a 4th argument (`DesktopConfiguration.DefaultSttRequestTimeout` for tests that don't care).

- [ ] **Step 5: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter "VoiceDeviceAvailabilityTests|DesktopConfigurationTests"`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS (catch any call site Step 4 missed)

- [ ] **Step 7: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/VoiceDeviceAvailability.cs desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs desktop/tests/Reva.Desktop.Tests/Unit/VoiceDeviceAvailabilityTests.cs desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs
git commit -m "fix(desktop): exact permission message text, add dedicated STT timeout config"
```

---

### Task 4: `RevaCoreClient` — per-call timeouts on every path + voice-aware timeout message

**Files:**
- Modify: `desktop/src/Reva.Desktop/Services/RevaCoreClient.cs`
- Modify: `desktop/src/Reva.Desktop/App.xaml.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreClientTests.cs`

**Interfaces:**
- Produces: `RevaCoreClient(HttpClient httpClient, ILocalTokenProvider tokenProvider, TimeSpan? requestTimeout = null, TimeSpan? sttRequestTimeout = null)`, defaulting to `DesktopConfiguration.DefaultRequestTimeout` / `DefaultSttRequestTimeout`. `TranscribeSpeechAsync` enforces the STT timeout independent of `HttpClient.Timeout`, and its timeout failure returns `CoreErrorKind.CoreTimeout` with message `"REVA voice did not respond in time."`
- **Behavior change, deliberate:** caller-requested cancellation now propagates as `OperationCanceledException` instead of being normalized into a `CoreTimeout` failure result. v1 claimed this was not a behavior change; it is. Step 4 audits and covers it.

> **Two traps this task exists to avoid.** First: v1 set `httpClient.Timeout = Timeout.InfiniteTimeSpan` while explicitly leaving `SendBytesAsync` (TTS) untouched. If `SendBytesAsync` had no CTS of its own (Task 0 Step 1.4 tells you), that combination removes its only timeout and a hung TTS call hangs forever. Every send path gets a per-call CTS here, and `HttpClient.Timeout` keeps a generous backstop rather than going infinite. Second: broadening the catch and adding an exception filter changes what callers observe — that needs a test, not a footnote.

- [ ] **Step 1: Add a delaying fake handler if one doesn't exist**

Per Task 0 Step 1.9. It must honour the token, or the timeout tests will hang instead of failing:

```csharp
    public static FakeHttpMessageHandler Delayed(TimeSpan delay, HttpStatusCode status, string json) =>
        new(async (_, cancellationToken) =>
        {
            await Task.Delay(delay, cancellationToken).ConfigureAwait(false);
            return new HttpResponseMessage(status)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            };
        });
```

- [ ] **Step 2: Write the failing tests**

```csharp
    private const string TranscriptionJson =
        """{"schema_version":1,"text":"hello","language":"en","duration_ms":900}""";

    private static RevaCoreClient ClientWith(
        HttpMessageHandler handler, TimeSpan requestTimeout, TimeSpan sttRequestTimeout) =>
        new(
            new HttpClient(handler)
            {
                BaseAddress = new Uri("http://127.0.0.1:8756/"),
                Timeout = Timeout.InfiniteTimeSpan,
            },
            new FakeTokenProvider("t"),
            requestTimeout,
            sttRequestTimeout);

    [Fact]
    public async Task TranscribeSpeechAsync_Timeout_MapsToVoiceTimeoutMessage_NotGenericCoreMessage()
    {
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromSeconds(5), HttpStatusCode.OK, TranscriptionJson),
            requestTimeout: TimeSpan.FromSeconds(10),
            sttRequestTimeout: TimeSpan.FromMilliseconds(100));

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreTimeout, result.Error!.Kind);
        Assert.Equal("REVA voice did not respond in time.", result.Error.SafeMessage);
    }

    [Fact]
    public async Task TranscribeSpeechAsync_SlowerThanRequestTimeoutButFasterThanSttTimeout_Succeeds()
    {
        // The test v1 was missing: proves the STT call actually selects the
        // longer STT timeout rather than the short general one. Fails if
        // TranscribeSpeechAsync forgets to pass timeout: _sttRequestTimeout.
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromMilliseconds(400), HttpStatusCode.OK, TranscriptionJson),
            requestTimeout: TimeSpan.FromMilliseconds(50),
            sttRequestTimeout: TimeSpan.FromSeconds(5));

        var result = await client.TranscribeSpeechAsync(new byte[] { 1, 2, 3 });

        Assert.True(result.IsSuccess);
        Assert.Equal("hello", result.Value!.Text);
    }

    [Fact]
    public async Task SendMessageAsync_ExceedingRequestTimeout_StillReturnsGenericCoreTimeoutMessage()
    {
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromSeconds(5), HttpStatusCode.OK, "{}"),
            requestTimeout: TimeSpan.FromMilliseconds(100),
            sttRequestTimeout: TimeSpan.FromSeconds(30));

        var result = await client.SendMessageAsync("hi");

        Assert.False(result.IsSuccess);
        Assert.Equal(CoreErrorKind.CoreTimeout, result.Error!.Kind);
        Assert.Equal("REVA Core did not respond in time.", result.Error.SafeMessage);
    }

    [Fact]
    public async Task SendMessageAsync_CallerCancellation_PropagatesOperationCanceled()
    {
        // Documents the deliberate semantic change: caller cancellation is no
        // longer laundered into a CoreTimeout failure result.
        var client = ClientWith(
            FakeHttpMessageHandler.Delayed(TimeSpan.FromSeconds(5), HttpStatusCode.OK, "{}"),
            requestTimeout: TimeSpan.FromSeconds(30),
            sttRequestTimeout: TimeSpan.FromSeconds(30));
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(50));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => client.SendMessageAsync("hi", cts.Token));
    }
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter RevaCoreClientTests`
Expected: FAIL — the voice-message test returns the generic string; the STT-selection test times out at 50ms; the cancellation test gets a failure result instead of an exception.

- [ ] **Step 4: Audit the cancellation change before implementing it**

Using Task 0 Step 1.5's call-site list, confirm every caller of a `RevaCoreClient` method either passes `CancellationToken.None` or has a `catch (OperationCanceledException)`. `AssistantViewModel.SendMessageAsync` is the one to check closely. If a caller would now surface an unhandled exception where it previously showed an error banner, fix that caller in this task — do not discover it in Task 9.

- [ ] **Step 5: Implement**

Constructor and fields:

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
        _requestTimeout = requestTimeout ?? DesktopConfiguration.DefaultRequestTimeout;
        _sttRequestTimeout = sttRequestTimeout ?? DesktopConfiguration.DefaultSttRequestTimeout;
    }
```

`TranscribeSpeechAsync` passes the STT timeout through:

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

`SendAsync` accepts and enforces a per-call timeout:

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
            var message = voiceRequest ? "REVA voice did not respond in time." : "REVA Core did not respond in time.";
            return CoreResult<T>.Failure(CoreErrorKind.CoreTimeout, message);
        }
        catch (HttpRequestException)
        {
            return CoreResult<T>.Failure(CoreErrorKind.CoreUnavailable, "REVA Core is not reachable.");
        }

        using (response)
        {
            return await InterpretResponseAsync<T>(response, cancellationToken, voiceRequest).ConfigureAwait(false);
        }
    }
```

**And give `SendBytesAsync` the same treatment** — the exact edit depends on its current body (Task 0 Step 1.4). It must wrap its send in a `CancellationTokenSource(_requestTimeout)` linked to the caller's token, with the same `catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)` shape. This is not scope creep: without it, Step 6's `HttpClient` change leaves TTS with no timeout.

- [ ] **Step 6: Update `App.xaml.cs`**

```csharp
        var httpClient = new System.Net.Http.HttpClient
        {
            BaseAddress = configuration.CoreBaseUrl,
            // Backstop only. Every call path enforces its own shorter, per-call
            // timeout; this exists so a future method added without a CTS
            // cannot hang forever. Must stay comfortably above the STT timeout
            // (30s default, env-overridable) so it never pre-empts it.
            Timeout = TimeSpan.FromSeconds(300),
        };
        var coreClient = new RevaCoreClient(
            httpClient, tokenProvider, configuration.RequestTimeout, configuration.SttRequestTimeout);
```

If `REVA_DESKTOP_STT_TIMEOUT_SECONDS` is ever set above 300, the backstop wins — note this in the env var's documentation comment.

- [ ] **Step 7: Run the full test suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, including all pre-existing `RevaCoreClientTests`.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/RevaCoreClient.cs desktop/src/Reva.Desktop/App.xaml.cs desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreClientTests.cs
git commit -m "fix(desktop): per-call timeouts on every Core path, voice-specific timeout message"
```

---

### Task 5: Mono 16kHz capture + temp-file hygiene in `WindowsVoiceDevice`

**Files:**
- Modify: `desktop/src/Reva.Desktop/Services/WindowsVoiceDevice.cs`

No unit test here — `WindowsVoiceDevice` requires a real WinRT `MediaCapture` and cannot run under xUnit (this is why `IVoiceDevice` exists as a fake-able seam; `AssistantViewModel`'s tests in Task 7 exercise format validation against `FakeVoiceDevice`-supplied bytes instead). Verified in Task 9's acceptance run: the `data` chunk should be roughly `2 bytes × 16000 × seconds`.

- [ ] **Step 1: Force the format, with a fallback**

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
            // Positional args deliberately — the projected WinRT parameter names
            // are not guaranteed to match the C# names you'd expect.
            profile.Audio = AudioEncodingProperties.CreatePcm(16000, 1, 16);
            try
            {
                _recording = await _capture.PrepareLowLagRecordToStorageFileAsync(profile, file);
            }
            catch (Exception ex) when (ex is ArgumentException or NotSupportedException || ex.HResult == unchecked((int)0xC00D5212))
            {
                // Some capture hardware refuses 16kHz mono. Falling back to the
                // default WAV profile is better than surfacing a generic
                // recording failure — reva_core's _validate_wav_upload accepts
                // other rates, it just prefers this one.
                DesktopLogger.Info("voice.capture.format_fallback");
                _recording = await _capture.PrepareLowLagRecordToStorageFileAsync(
                    MediaEncodingProfile.CreateWav(AudioEncodingQuality.High), file);
            }
```

Confirm the fallback's HRESULT guard against what the device actually throws during Task 9; widen or narrow it then. If `reva_core` in fact rejects non-16kHz uploads, delete the fallback and let the failure surface — check `_validate_wav_upload` before deciding.

- [ ] **Step 2: Remove any now-redundant post-capture conversion**

If Task 0 or a read of this file turns up existing resampling/downmixing after capture, remove it — the profile now produces the target format directly, and running both wastes time and can double-process the audio.

- [ ] **Step 3: Confirm the temp WAV is deleted**

Per Task 0 Step 1.6. After `StopRecordingAsync` has read the bytes, the file at `_recordingPath` must be deleted, including on the failure and cancellation paths (a `finally`). If it currently persists, fix it here. A recording left on disk contradicts this slice's own privacy constraint far more than a log line would.

- [ ] **Step 4: Build**

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds (0 errors). `AudioEncodingProperties` is already imported via the existing `using Windows.Media.MediaProperties;`.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/WindowsVoiceDevice.cs
git commit -m "fix(desktop): capture mono 16kHz PCM WAV directly and clean up temp recordings"
```

---

### Task 6: `AssistantViewModel` readiness wiring (mic + Core, never TTS)

**Files:**
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs`
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs`

**Interfaces:**
- Consumes: `Reva.Desktop.State.VoiceUiState` / `VoiceUiStateText` (Task 1), `IRevaCoreLifecycle` (existing — exact surface confirmed in Task 0).
- Produces: `AssistantViewModel(IRevaCoreClient coreClient, IVoiceDevice? voiceDevice = null, IRevaCoreLifecycle? lifecycle = null)`. New read-only `VoiceUiState VoiceState { get; }`; `VoiceStatusText` becomes `VoiceUiStateText.For(VoiceState)`. `CanStartVoiceInput`/`CanUseVoiceButton` require Core connected (a null `lifecycle` counts as connected, for the existing call sites that don't pass one). **When Core is disconnected and the mic is fine, `VoiceState` is `SttUnavailable`, not `ReadyToTalk`** — otherwise the status text claims readiness while the button is greyed out, which is the same class of contradiction this slice exists to remove.

This task adds gating, the `VoiceUiState`-backed status, and thread-safe lifecycle handling. It does **not** yet change `FinishVoiceInputAsync`'s behavior (Task 7). Keep auto-send/auto-speak working through this task so the suite stays green incrementally.

- [ ] **Step 1: Write the failing tests**

Fake lifecycle (adjust members to Task 0's findings):

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

```csharp
    [Fact]
    public void CanStartVoiceInput_MicReadyButCoreDisconnected_IsFalse()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.False(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void VoiceState_MicReadyButCoreDisconnected_ReportsSttUnavailable_NotReadyToTalk()
    {
        // The status must explain the disabled button. "Ready to Talk" next to a
        // greyed-out control is the contradiction this slice removes.
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);
        Assert.Equal("STT Unavailable", viewModel.VoiceStatusText);
    }

    [Fact]
    public void CanStartVoiceInput_MicReadyAndCoreConnected_IsTrue()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);

        Assert.True(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
    }

    [Fact]
    public void CanStartVoiceInput_NoLifecycleProvided_DefaultsToTrueWhenMicReady()
    {
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice());

        Assert.True(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public void CoreDisconnectsAfterConstruction_UpdatesButtonAndStatusTogether()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), new FakeVoiceDevice(), lifecycle);
        Assert.True(viewModel.CanStartVoiceInput);

        lifecycle.State = CoreLifecycleState.Unavailable;
        lifecycle.RaiseStateChanged();

        Assert.False(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.SttUnavailable, viewModel.VoiceState);

        lifecycle.State = CoreLifecycleState.Connected;
        lifecycle.RaiseStateChanged();

        Assert.True(viewModel.CanStartVoiceInput);
        Assert.Equal(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
    }

    [Fact]
    public void CoreStateChange_DoesNotOverrideMicSpecificFailureStates()
    {
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Connected };
        var voiceDevice = new FakeVoiceDevice(isAvailable: false);
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice, lifecycle);

        lifecycle.RaiseStateChanged();

        Assert.NotEqual(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: FAIL to build — no 3-arg constructor, no `VoiceState` property yet.

- [ ] **Step 3: Implement**

```csharp
    private readonly IRevaCoreLifecycle? _lifecycle;
    private readonly DispatcherQueue? _dispatcherQueue = TryGetDispatcherQueue();

    public AssistantViewModel(
        IRevaCoreClient coreClient,
        IVoiceDevice? voiceDevice = null,
        IRevaCoreLifecycle? lifecycle = null)
    {
        _coreClient = coreClient;
        _voiceDevice = voiceDevice ?? new UnavailableVoiceDevice();
        _lifecycle = lifecycle;
        _isVoiceAvailable = _voiceDevice.IsAvailable;
        _voiceState = _isVoiceAvailable
            ? (IsCoreConnected ? VoiceUiState.ReadyToTalk : VoiceUiState.SttUnavailable)
            : VoiceUiState.CheckingMicrophone;

        if (_lifecycle is not null)
        {
            _lifecycle.StateChanged += OnLifecycleStateChanged;
        }
    }

    // Captured on the constructing thread: the UI thread in MainWindow, null
    // under xUnit. Never throws — a null queue simply means "already on the
    // right thread, invoke directly."
    private static DispatcherQueue? TryGetDispatcherQueue()
    {
        try
        {
            return DispatcherQueue.GetForCurrentThread();
        }
        catch
        {
            return null;
        }
    }

    private bool IsCoreConnected => _lifecycle is null || _lifecycle.State == CoreLifecycleState.Connected;

    private void OnLifecycleStateChanged(object? sender, EventArgs e)
    {
        // StateChanged may be raised from a poll/timer thread. Raising
        // PropertyChanged from there drives a WinUI binding update off-thread
        // and throws RPC_E_WRONG_THREAD at runtime.
        if (_dispatcherQueue is not null && !_dispatcherQueue.HasThreadAccess)
        {
            _dispatcherQueue.TryEnqueue(ApplyLifecycleChange);
            return;
        }

        ApplyLifecycleChange();
    }

    private void ApplyLifecycleChange()
    {
        RefreshIdleVoiceState();
        RaiseVoiceAvailabilityProperties();
    }

    // Recomputes the idle status from mic + Core so status and enablement can
    // never disagree. Deliberately does nothing mid-turn, and never overwrites
    // a mic-specific failure (which is more informative than "STT Unavailable").
    private void RefreshIdleVoiceState()
    {
        if (IsMicrophoneActive || IsVoiceBusy)
        {
            return;
        }

        if (VoiceState is VoiceUiState.PermissionDenied
            or VoiceUiState.NoMicrophone
            or VoiceUiState.CheckingMicrophone)
        {
            return;
        }

        if (!_isVoiceAvailable)
        {
            return;
        }

        VoiceState = IsCoreConnected ? VoiceUiState.ReadyToTalk : VoiceUiState.SttUnavailable;
        VoiceErrorMessage = IsCoreConnected ? null : "REVA Core is not connected.";
    }

    public void DetachLifecycle()
    {
        if (_lifecycle is not null)
        {
            _lifecycle.StateChanged -= OnLifecycleStateChanged;
        }
    }
```

Gating properties:

```csharp
    public bool CanUseVoiceButton => _isVoiceAvailable && IsCoreConnected && !IsPending;

    public bool CanStartVoiceInput => _isVoiceAvailable && IsCoreConnected && !IsPending && !IsVoiceBusy;
```

`VoiceState`/`VoiceStatusText` (property-changed method name per Task 0 Step 1.3):

```csharp
    private VoiceUiState _voiceState;

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

Delete the old `_voiceStatusText` field and its string-literal initialization.

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: PASS — all pre-existing tests (none pass a `lifecycle`, so `IsCoreConnected` is `true` and behavior is preserved) plus the 6 new ones.

- [ ] **Step 5: Wire `MainWindow.xaml.cs`**

```csharp
        Assistant = new AssistantViewModel(coreClient, voiceDevice, lifecycle);
```

Call `DetachLifecycle()` from the window's `Closed` handler. If Task 0 Step 1.8 found that `RefreshVoiceAvailabilityAsync` is not called at startup, add that call now — otherwise an unavailable mic leaves the UI on "Checking Microphone" permanently.

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/src/Reva.Desktop/MainWindow.xaml.cs desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "feat(desktop): gate Hold-to-Talk on Core connectivity with matching status, never on TTS"
```

---

### Task 7: Rewrite `FinishVoiceInputAsync` — transcription-only, `VoiceUiState`-backed

The core behavior change: stop after transcription, populate the composer, never call `SendMessageCoreAsync` or `SynthesizeSpeechAsync`/`PlayAsync` from the voice path.

**Files:**
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs`
- Modify: `desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs`

**Interfaces:**
- Consumes: `WavAudio.TryGetDurationMs` (Task 2), `VoiceUiState`/`VoiceUiStateText` (Task 1).
- Produces: `VoiceState` transitions through the idle states → `Listening` (press) → `Transcribing` (release) → `TranscriptionReady` | `TranscriptionFailed` | `SttUnavailable`. `ComposerText` receives the transcribed text. `IsSpeaking`/`StopSpeaking()`/`CanStopSpeaking` remain as public members but are never set true by the voice path.

**Two decisions v1 left implicit, now explicit:**

1. **An empty or whitespace-only transcript is a failure, not a success.** Silence returns HTTP 200 with `text: ""`; reporting "Transcription Ready" over an empty composer is a lie the user can't act on.
2. **A non-empty composer draft is preserved.** Transcription appends (space-separated) rather than overwriting. Destroying half a typed message because the user reached for the mic is a data-loss bug, not a UX preference.

- [ ] **Step 1: Replace the voice-turn test block**

Delete everything from `VoiceTurn_TranscribesThenUsesExistingMessagePipelineThenSpeaksReply` (line ~349) through `StopSpeaking_HaltsActivePlaybackImmediately` (end of class, ~line 631) and replace with:

```csharp
    [Fact]
    public async Task VoiceTurn_PressBeginsRecordingOnce()
    {
        var voiceDevice = new FakeVoiceDevice();
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice);

        await viewModel.StartVoiceInputAsync();

        Assert.Equal(1, voiceDevice.StartCallCount);
        Assert.Equal(0, voiceDevice.StopCallCount);
        Assert.True(viewModel.IsMicrophoneActive);
        Assert.Equal(VoiceUiState.Listening, viewModel.VoiceState);
        Assert.Equal("Listening", viewModel.VoiceStatusText);
    }

    [Fact]
    public async Task VoiceTurn_PressClearsStaleErrorFromPreviousTurn()
    {
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromMilliseconds(100)));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // too short — leaves an error
        Assert.NotNull(viewModel.VoiceErrorMessage);

        await viewModel.StartVoiceInputAsync();

        Assert.Null(viewModel.VoiceErrorMessage);
        Assert.Equal(VoiceUiState.Listening, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceTurn_ReleaseStopsOnce_TranscribesOnce_PopulatesComposer_NeverSendsOrSpeaks()
    {
        var client = TranscribingClient("hello REVA");
        var voiceDevice = new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1)));
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
    public async Task VoiceTurn_ExistingComposerDraftIsPreserved_TranscriptIsAppended()
    {
        var client = TranscribingClient("and also this");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));
        viewModel.ComposerText = "typed draft";

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal("typed draft and also this", viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_EmptyTranscriptIsTreatedAsFailure_NotReady()
    {
        var client = TranscribingClient("   ");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
        Assert.NotNull(viewModel.VoiceErrorMessage);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_CanceledPointerStopsSafely()
    {
        var viewModel = new AssistantViewModel(
            TranscribingClient("hello"),
            new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // pointer-canceled routes through the same method

        Assert.False(viewModel.IsMicrophoneActive);
    }

    [Fact]
    public async Task VoiceTurn_DuplicateReleaseIsIgnored_StopsExactlyOnce()
    {
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1)));
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync(); // e.g. release followed by capture-lost

        Assert.Equal(1, voiceDevice.StopCallCount);
        Assert.Equal(1, client.TranscribeCallCount);
    }

    [Fact]
    public async Task VoiceTurn_ReleaseWhileStartupInProgress_WaitsThenStopsOnce()
    {
        var recordingStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var allowRecordingToStart = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(
            recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1)),
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
    public async Task VoiceTurn_CancellationRestoresReadyState()
    {
        var client = TranscribingClient("hello");
        var voiceDevice = new FakeVoiceDevice(stopThrows: new OperationCanceledException());
        var viewModel = new AssistantViewModel(client, voiceDevice);

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(VoiceUiState.ReadyToTalk, viewModel.VoiceState);
        Assert.False(viewModel.IsVoiceBusy);
        Assert.True(viewModel.CanStartVoiceInput);
    }

    [Fact]
    public async Task VoiceTurn_EmptyRecordingIsRejectedBeforeTranscription()
    {
        var client = NeverTranscribingClient();
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
        var client = NeverTranscribingClient();
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromMilliseconds(100))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
        Assert.Contains("too short", viewModel.VoiceErrorMessage!, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(string.Empty, viewModel.ComposerText);
    }

    [Fact]
    public async Task VoiceTurn_ExactlyTwoHundredFiftyMillisecondsIsAccepted()
    {
        var client = TranscribingClient("ok");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromMilliseconds(250))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(1, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionReady, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceTurn_MalformedWavIsRejectedBeforeTranscription()
    {
        var client = NeverTranscribingClient();
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 }));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.TranscribeCallCount);
        Assert.Equal(VoiceUiState.TranscriptionFailed, viewModel.VoiceState);
    }

    [Fact]
    public async Task VoiceTurn_TranscriptionFailure_ServiceUnavailable_ShowsSttUnavailable_NeverAddsToChat()
    {
        var client = FailingTranscriptionClient(CoreErrorKind.CoreUnavailable, "REVA voice is unavailable.");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

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
        var client = FailingTranscriptionClient(CoreErrorKind.CoreTimeout, "REVA voice did not respond in time.");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

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
        var voiceDevice = new FakeVoiceDevice(
            startException: new VoiceCaptureException(VoiceDeviceAvailability.PermissionDenied()));
        var viewModel = new AssistantViewModel(ImmediateSuccessClient(), voiceDevice);

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
        // No TTS call path exists in this slice — this proves
        // SynthesizeSpeechAsync is never invoked during a full successful turn,
        // so whatever state TTS is in cannot gate CanStartVoiceInput.
        var client = TranscribingClient("hi");
        var viewModel = new AssistantViewModel(
            client, new FakeVoiceDevice(recordedAudio: TestWav.Mono16k(TimeSpan.FromSeconds(1))));

        await viewModel.StartVoiceInputAsync();
        await viewModel.FinishVoiceInputAsync();

        Assert.Equal(0, client.SynthesizeCallCount);
        Assert.True(viewModel.CanStartVoiceInput);
    }

    private static FakeCoreClient TranscribingClient(string text) => new(
        (_, _) => throw new NotSupportedException("transcription-only slice must never call SendMessageAsync"),
        (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Success(SuccessTranscription(text))),
        (_, _, _) => throw new NotSupportedException("transcription-only slice must never call SynthesizeSpeechAsync"));

    private static FakeCoreClient NeverTranscribingClient() => new(
        (_, _) => throw new NotSupportedException(),
        (_, _) => throw new NotSupportedException("must be rejected before any Core call"),
        (_, _, _) => throw new NotSupportedException());

    private static FakeCoreClient FailingTranscriptionClient(CoreErrorKind kind, string message) => new(
        (_, _) => throw new NotSupportedException(),
        (_, _) => Task.FromResult(CoreResult<VoiceTranscriptionResponse>.Failure(kind, message)),
        (_, _, _) => throw new NotSupportedException());
```

Also update `FakeVoiceDevice`: its default `RecordedAudio` is currently `new byte[] { 1, 2, 3 }`, which is neither a valid WAV nor long enough. `FakeVoiceDevice` is nested inside this test class, so it can call the shared builder directly:

```csharp
        public FakeVoiceDevice(
            byte[]? recordedAudio = null,
            /* existing parameters unchanged */)
        {
            RecordedAudio = recordedAudio ?? TestWav.Mono16k(TimeSpan.FromSeconds(1));
            // ...
        }
```

Add `bool isAvailable = true` and `Exception? stopThrows = null` parameters if they don't already exist — Task 6's `CoreStateChange_DoesNotOverrideMicSpecificFailureStates` and this task's cancellation test need them.

- [ ] **Step 2: Run tests to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: FAIL — the old `FinishVoiceInputAsync` still auto-sends and auto-speaks, so `Assert.Equal(0, client.CallCount)` and the `NotSupportedException` guards fire.

- [ ] **Step 3: Implement**

1. Add `using Reva.Desktop.State;`.
2. `StartVoiceInputAsync` — set `Listening` and clear the previous turn's error:

```csharp
        VoiceErrorMessage = null;
        VoiceState = VoiceUiState.Listening;
        DesktopLogger.Info("voice.state=Listening");
```

and on its cancel path:

```csharp
        catch (OperationCanceledException)
        {
            IsMicrophoneActive = false;
            IsVoiceBusy = false;
            RestoreIdleVoiceState();
        }
```

3. `RefreshVoiceAvailabilityAsync`:

```csharp
    public async Task RefreshVoiceAvailabilityAsync(CancellationToken cancellationToken = default)
    {
        VoiceState = VoiceUiState.CheckingMicrophone;
        try
        {
            var availability = await _voiceDevice.VerifyAvailabilityAsync(cancellationToken);
            _isVoiceAvailable = availability.IsReady;
            VoiceState = availability.IsReady ? IdleState() : MapAvailability(availability);
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

    private VoiceUiState IdleState() =>
        !_isVoiceAvailable ? VoiceUiState.NoMicrophone
        : IsCoreConnected ? VoiceUiState.ReadyToTalk
        : VoiceUiState.SttUnavailable;

    private void RestoreIdleVoiceState() => VoiceState = IdleState();

    private static VoiceUiState MapAvailability(VoiceDeviceAvailability availability) => availability.Kind switch
    {
        VoiceDeviceAvailabilityKind.Ready => VoiceUiState.ReadyToTalk,
        VoiceDeviceAvailabilityKind.PermissionDenied => VoiceUiState.PermissionDenied,
        VoiceDeviceAvailabilityKind.NoMicrophoneFound => VoiceUiState.NoMicrophone,
        _ => VoiceUiState.NoMicrophone,
    };
```

4. Replace `FinishVoiceInputAsync` entirely:

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
        DesktopLogger.Info("voice.state=Transcribing");

        try
        {
            if (_recordingStartTask is not null)
            {
                await _recordingStartTask;
            }

            var audio = await _voiceDevice.StopRecordingAsync(linkedToken);

            if (audio.Length == 0)
            {
                FailTurn("No voice audio was captured.", "empty_capture");
                return;
            }

            if (!WavAudio.TryGetDurationMs(audio, out var durationMs))
            {
                FailTurn("The recording could not be read. Try again.", "malformed_wav");
                return;
            }

            if (durationMs < MinimumRecordingMs)
            {
                FailTurn(
                    "Recording is too short. Hold the button and speak for at least a quarter second.",
                    "too_short");
                return;
            }

            var transcription = await _coreClient.TranscribeSpeechAsync(audio, linkedToken);
            if (!transcription.IsSuccess)
            {
                ApplyVoiceFailure(transcription.Error!);
                return;
            }

            var text = transcription.Value!.Text?.Trim() ?? string.Empty;
            if (text.Length == 0)
            {
                // 200 OK with no words — silence, not success. Reporting
                // "Transcription Ready" over an empty composer is misleading.
                FailTurn("No speech was recognized. Try again.", "empty_transcript");
                return;
            }

            ComposerText = string.IsNullOrWhiteSpace(ComposerText)
                ? text
                : $"{ComposerText.TrimEnd()} {text}";
            VoiceErrorMessage = null;
            VoiceState = VoiceUiState.TranscriptionReady;
            DesktopLogger.Info("voice.state=TranscriptionReady");
        }
        catch (OperationCanceledException)
        {
            RestoreIdleVoiceState();
            DesktopLogger.Info("voice.state=canceled");
        }
        catch (VoiceCaptureException ex)
        {
            ApplyVoiceCaptureFailure(ex.Availability);
        }
        catch (Exception)
        {
            FailTurn(VoiceDeviceAvailability.RecordingFailed().SafeMessage, "recording_failed");
        }
        finally
        {
            _recordingStartTask = null;
            IsVoiceBusy = false;
        }
    }

    private const int MinimumRecordingMs = 250;

    // reason is a fixed identifier, never audio or transcript content.
    private void FailTurn(string safeMessage, string reason)
    {
        VoiceErrorMessage = safeMessage;
        VoiceState = VoiceUiState.TranscriptionFailed;
        DesktopLogger.Info($"voice.state=TranscriptionFailed reason={reason}");
    }
```

5. Failure appliers:

```csharp
    private void ApplyVoiceFailure(CoreError error)
    {
        VoiceErrorMessage = error.SafeMessage;
        VoiceState = error.Kind is CoreErrorKind.CoreUnavailable or CoreErrorKind.CoreTimeout
            ? VoiceUiState.SttUnavailable
            : VoiceUiState.TranscriptionFailed;
        DesktopLogger.Info($"voice.state={VoiceState} kind={error.Kind}");
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

6. Leave `IsSpeaking`/`CanStopSpeaking`/`StopSpeaking()` and `_speechPlaybackCancellation` in place (still referenced from XAML until Task 8), but nothing in the voice path sets `IsSpeaking = true` anymore. Remove the now-unused `VoiceLanguageResolver` call site from this file; leave the class itself alone.

- [ ] **Step 4: Run tests to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter AssistantViewModelTests`
Expected: PASS — the untouched typed-chat tests and the rewritten voice-turn tests.

- [ ] **Step 5: Run the full suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "feat(desktop): make Hold-to-Talk transcription-only (no auto-send, no auto-speak)"
```

---

### Task 8: Retire the dead speech UI

**Files:**
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml`

`StopSpeakingButton` binds to `CanStopSpeaking`, which is now permanently false — a visible control that can never be used is itself a readiness contradiction, and it invites the next reader to assume TTS is one bug away from working.

- [ ] **Step 1: Collapse it**

Set `Visibility="Collapsed"` on `StopSpeakingButton` (keep the binding and the ViewModel members intact so the control can be revived when TTS returns as its own slice), and add a one-line XAML comment pointing at the design doc.

Do **not** delete `IsSpeaking`/`CanStopSpeaking`/`StopSpeaking()` — deleting them widens the diff into the TTS path this slice is scoped out of.

- [ ] **Step 2: Note the composer binding, don't change it**

v1 worried that a background continuation setting `ComposerText` wouldn't reach `ComposerBox`. It does: the `LostFocus` quirk documented at `MainWindow.xaml.cs:66-81` affects the **View→ViewModel** direction (the control committing user edits back), not ViewModel→View, which is an ordinary `PropertyChanged` push. Confirm `SetProperty` raises synchronously (Task 0 Step 1.3) and add no code.

The one real risk is threading: if `FinishVoiceInputAsync` resumes on a non-UI thread, the push crashes rather than arriving stale. Grep this file for `ConfigureAwait(false)` — there should be none in the ViewModel's voice path. Task 9 Step 6 confirms behavior against the real UI; only if the textbox is observably stale there, add:

```csharp
    public event EventHandler<string>? TranscriptionCompleted;
```

fired after `ComposerText` is set, with `Assistant.TranscriptionCompleted += (_, text) => ComposerBox.Text = text;` in the `MainWindow` constructor. Do not add it speculatively.

- [ ] **Step 3: Build and commit**

```bash
dotnet build desktop/Reva.Desktop.sln
git add desktop/src/Reva.Desktop/MainWindow.xaml
git commit -m "chore(desktop): hide the permanently-disabled stop-speaking control"
```

---

### Task 9: Real-microphone acceptance run

**Files:** none (verification task).

- [ ] **Step 1: Full automated suite, one last time**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures. Green before touching the physical microphone.

- [ ] **Step 2: Build Release**

Run: `dotnet build desktop/Reva.Desktop.sln -c Release`
Expected: succeeds. Confirm the produced exe path from the build output (`desktop/src/Reva.Desktop/bin/Release/net10.0-windows10.0.19041.0/Reva.Desktop.exe` or similar).

- [ ] **Step 3: Ensure `reva_core` is reachable**

Core is expected at `http://127.0.0.1:8756/`. Either start it per `reva_core/README.md`, or confirm `App.xaml.cs`'s `RevaCoreLifecycle`/`CoreProcessLauncher` auto-launches it.

- [ ] **Step 4: Run the Release executable**

Wait for `CoreStatusText` = "Core Connected" and `VoiceStatusText` = "Ready to Talk".

- [ ] **Step 5: Core-offline contradiction check (do this first)**

Before the happy path, stop `reva_core` (or launch the exe with Core down). Confirm: the Hold-to-Talk button is disabled **and** `VoiceStatusText` reads "STT Unavailable" — not "Ready to Talk". This is the v1 bug this plan exists to prevent; catching it here is the whole point. Restart Core and confirm both recover without restarting the app (this also exercises the off-thread `StateChanged` path from Task 6 — a crash or frozen status here means the dispatcher hop is wrong).

- [ ] **Step 6: Physical hold-to-talk test**

Hold the mouse button on "Hold to Talk". Say: "Hey Reva, this is a microphone transcription test." Release.

- [ ] **Step 7: Observe and record**

Confirm:
- `VoiceStatusText` transitioned `Listening` → `Transcribing` → `Transcription Ready`.
- `ComposerBox` contains text exact or meaning-equivalent to the spoken sentence, and updated without needing a click (if stale, apply Task 8 Step 2's fallback and note it).
- Nothing was auto-sent — `MessageList` gained no entries, the text is still editable in the composer.
- No audio played back; `StopSpeakingButton` is collapsed.
- The temp WAV from this turn no longer exists on disk (check the `_recordingPath` directory).

- [ ] **Step 8: Short-recording and silence checks**

Tap the button (< 250ms): expect "Transcription Failed" with the too-short message, and **no** Core request. Then hold for two seconds in silence: expect "Transcription Failed" with "No speech was recognized", not "Transcription Ready" over an empty box.

- [ ] **Step 8a: Draft-preservation check (added after final review, finding #5)**

Type a partial message in the composer but do **not** click elsewhere or otherwise move focus off `ComposerBox`. While still focused there, hold-to-talk and speak. Release. Confirm the typed draft survives and the transcript is appended after it (`"typed draft transcribed words"`), not silently overwritten. This exercises a real risk the unit tests can't see: `ComposerBox`'s `x:Bind TwoWay` only commits the user's typed text back to `Assistant.ComposerText` on `LostFocus`, so if focus never left the box before the transcript-append code reads `ComposerText`, that read could be stale. Expected to pass (the Hold-to-Talk button takes pointer focus on press, which should force the commit before release), but this is unverified against real WinUI focus timing until this step runs.

- [ ] **Step 8b: Pending-chat status check (added after final review, finding #3)**

Type a message and click Send, and while that request is still in flight (before a reply appears), observe `VoiceStatusText`. Expected/accepted limitation: it will read "Ready to Talk" even though Hold-to-Talk is disabled (`CanStartVoiceInput` includes `!IsPending`, and `VoiceUiState` has no pending-aware member among the nine required strings). This is a known, accepted gap — confirm it matches this description exactly (transient, self-resolves when the chat reply arrives) rather than surfacing as something worse (e.g. a stuck state that doesn't recover once the chat completes).

- [ ] **Step 9: Report the required metrics**

Record: capture duration (press-to-release), WAV size in bytes (should be ≈ `2 × 16000 × seconds` + 44 — this is Task 5's only real verification), STT latency (release → "Transcription Ready"), and the exact recognized text.

- [ ] **Step 10: If it fails, diagnose before retrying**

`STT Unavailable` / `Permission Denied` / `No Microphone` are real environment problems (Core down, mic permission off, no device) — fix the cause, not the implementation. The `voice.state=` log lines from Task 7 tell you which branch fired. Rebuild if code changed and repeat from Step 4.

- [ ] **Step 11: Commit any last-mile fixes**

```bash
git status
git add -A
git commit -m "fix(desktop): address real-microphone acceptance findings"
```

(Skip if `git status` is clean — Tasks 0-8 committed everything.)

- [ ] **Step 12: Report**

Summarize capture duration, WAV size, STT latency, recognized text, the Core-offline status behavior from Step 5, and explicit confirmation that no assistant (`/v1/messages`) and no TTS (`/v1/voice/speech`) request occurred — cross-check `reva_core`'s audit log for this run's correlation window (`voice_transcription_completed` present, `voice_speech_completed` absent).

---

## Self-Review Notes

- **Spec coverage:** readiness (Task 6), UI states (Tasks 1, 6, 7), permission message (Task 3), capture format (Task 5), duration validation + 250ms rejection (Tasks 2, 7), timeouts (Tasks 3, 4), cancellation restores ready state (Task 7 — now with `VoiceTurn_CancellationRestoresReadyState` actually covering it, which v1 claimed without testing), real acceptance run (Task 9).
- **All 12 required behaviors are tested:** press, release, cancel, capture-lost, duplicate-release, empty-rejected, permission-denied, STT-timeout, composer-populated, not-auto-sent, TTS-unaffected, typed-chat-still-works — plus five the spec implies but v1 left uncovered: malformed WAV, empty transcript, draft preservation, stale error clearing, and status/enablement agreement when Core is offline.
- **No backend changes** anywhere in this plan.
- **Type consistency:** `VoiceUiState`/`VoiceUiStateText` (Task 1) used identically in Tasks 6-7. `WavAudio.TryGetDurationMs` (Task 2) signature used identically in Task 7. `AssistantViewModel`'s 3-arg constructor (Task 6) consistent through Task 9. `DesktopConfiguration`'s 4-arg constructor and timeout constants (Task 3) are the single source consumed by `RevaCoreClient` (Task 4) and `App.xaml.cs` (Task 4 Step 6).
- **Deliberate behavior changes, each with a test:** caller cancellation propagates from `RevaCoreClient` instead of becoming a `CoreTimeout` result (Task 4); transcription appends to rather than replaces a composer draft (Task 7); an empty transcript is a failure (Task 7); Core-disconnected reads as `STT Unavailable` (Task 6).
- **Known accepted limitation:** the nine required status strings have no "Core Offline" member, so a disconnected Core and a genuinely broken STT service are indistinguishable in the status line. `VoiceErrorMessage` carries the distinction. If the spec's string list can be extended later, a tenth state is the cleaner fix.
- **Known accepted limitation (from final whole-branch review):** while a typed chat message is in flight (`IsPending`), Hold-to-Talk is correctly disabled but `VoiceStatusText` still reads "Ready to Talk" — the nine-string set has no pending-aware member, and adding an `IsPending` branch to `VoiceState`'s computation would require a tenth state the spec doesn't define. Transient and self-resolving (clears when the chat reply arrives); verified via Task 9 Step 8b.
- **Known accepted limitation (from final whole-branch review):** `ApplyVoiceCaptureFailure(VoiceDeviceAvailability.RecordingFailed())` maps to `VoiceUiState.NoMicrophone` ("No Microphone"), which is factually imprecise for a transient recording failure (mic exists, this specific attempt failed) — `VoiceErrorMessage` carries the accurate detail. Not fixable within the nine-string set.
- **Post-implementation fix wave (after final whole-branch review, before Task 9):** three Important findings fixed and full-suite-verified in commit `f56a3bd`: (1) `WindowsVoiceDevice.StopRecordingAsync` could get permanently wedged if `StopAsync()`/`FinishAsync()` threw mid-teardown (device unplugged mid-recording) — teardown moved into `finally` so it's unconditional; (2) no way to recover from `Permission Denied` after granting mic access without restarting the app — `MicrophoneSettingsButton_Click` now re-probes via `RefreshVoiceAvailabilityAsync()` after the Settings deep-link; (3) a capture-format-fallback exception falling outside the guarded HRESULT filter left no diagnostic evidence — the outer catch now logs the HResult (a numeric code, not content) before throwing.