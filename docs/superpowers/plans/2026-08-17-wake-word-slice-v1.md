# Wake-Word Slice (multi-phrase) v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Gate update (2026-08-17):** begin implementation on `feature/windows-app-command-routing` after the app-command routing acceptance work. Product behavior changed from "wake transcripts never execute" to asymmetric router reuse: safe Open commands may auto-execute through the existing deterministic router; Close commands may only create the existing confirmation prompt; ordinary speech only fills the composer. Do not begin physical acceptance until the automated implementation and Release build are clean.
>
> Previous gate context retained for physical acceptance readiness. Before physical acceptance, confirm:
> 1. `docs/superpowers/plans/2026-08-17-windows-app-command-routing-v2.md` — every task reviewed clean, Task 7 physical acceptance passed and reported, **including Step 7 (the spoken-confirm check)**. This slice's safety story is built on that mechanism working.
> 2. The transcription-only voice slice's Task 9 physical-microphone acceptance is fully closed out.
> 3. Picovoice custom-keyword licensing/expiry verified against the actual account and tier. Cannot be resolved by reasoning.
>
> **The chime asset is no longer a gate item.** v1 required it before Task 0 while its own Task 6 produced it — a gate that could never clear. It is Task 6 here, an ordinary task.

**Supersedes the v1 plan (2026-08-17).** Structural changes: the microphone arbiter now owns the audio stream and issues leases (v1's advisory flag could not prevent, and did not prevent, two components capturing at once); frame capture is built once in Task 4 instead of being deferred Task 4 → Task 5 → Task 8; `IComposerSink` gains real append semantics; detection events are marshalled to the UI thread; the `SttUnavailable` state now has an exit; the chime no longer lands inside the recording it precedes; four v1 tests that could not have passed or passed for the wrong reason are fixed.

**Goal:** Local, always-listening wake-word detection ("Hey Reva" plus three optional phrases) that arms and disarms explicitly, reuses the existing STT pipeline, strips only the leading wake phrase, and submits the remaining text through the existing `AssistantViewModel`/`ICommandRouter` Send path.

**Asymmetric command rule:** safe Open commands may execute automatically through the existing app-command allowlist and executor. Close commands may create the existing confirmation state, but spoken `confirm` remains `CommandSource.Transcribed` and cannot approve closure. Non-command speech is restored to `ComposerText` and is never sent to Core/ADK/LLM.

**Architecture:** `MicrophoneArbiter` owns the single capture right and issues `IMicrophoneLease`s — the only source of audio frames in the app. `PorcupineWakeWordDetector` (one Porcupine instance, N keywords) reads frames from a lease handed to it. `Endpointer` (RMS + hysteresis + hard cap) decides when captured speech ends. `WakeWordCoordinator` owns the state machine, pauses detection while capturing, plays the activation chime, transcribes, strips the wake phrase, and calls an `AssistantViewModel` transcription-submit entry point that reuses the existing `SendMessageCoreAsync` router path. `WakeWordCoordinator` never owns app matching, allowlists, process execution, Core chat calls, memory, or TTS.

**Tech Stack:** C# / .NET (net10.0-windows10.0.19041.0), Porcupine .NET SDK (added in Task 5), `Windows.Media.Capture` / `Windows.Media.Audio` (via the arbiter), `System.TimeProvider`, xUnit.

## Global Constraints

- Wake word OFF by default; every phrase except `HeyReva` OFF by default even after enabling.
- No STT call, no recording file, and no Assistant call before a detection.
- Wake-word detection never executes Windows actions directly — it submits text through the existing `ICommandRouter` and `AssistantViewModel` Send path.
- Safe Open commands may auto-execute only through the existing app-command allowlist/executor.
- Close commands may auto-prompt only; typed confirmation is still required for the actual close.
- Non-command wake speech restores to `ComposerText`; it is not sent to Core/ADK/LLM.
- **A wake-word transcript is marked `Transcribed`**, so app-command routing will not let a spoken "confirm" resolve a pending destructive action.
- **No wake path may auto-send ordinary speech to Core/ADK/LLM.** `CommandOutcome.NotACommand` is restored to the composer.
- Never log PCM, transcript text, or confidence/per-frame data. Fixed state identifiers and phrase enum values only.
- Pre-wake audio is never written to disk.
- Post-wake audio is deleted in a `finally` on every path — and the coordinator owns that cleanup.
- AccessKey read from `REVA_PICOVOICE_ACCESS_KEY` only; never committed, logged, or echoed.
- Keyword `.ppn` files read from a fixed local directory, never downloaded at runtime.
- **Audio frames come from a microphone lease or they do not come at all.** No component constructs its own `MediaCapture`.
- Hold-to-Talk suspends wake word and resumes it on every exit path — success, cancel, capture-lost, error.
- No status/enablement contradiction: if the toggle is on and the feature is non-functional, the state says why.
- Provider-specific (Porcupine) code appears only in `PorcupineWakeWordDetector`.
- Desktop-only — no `reva_core`/Python changes.

---

## File Structure

- `Services/WakePhrase.cs` — **new**. `WakePhrase`, `WakePhraseSetting`, `WakeWordConfiguration`, `WakePhraseDefaults`.
- `State/WakeWordUiState.cs` — **new**. 10 states + display text, mirroring `VoiceUiState`.
- `Services/IMicrophoneArbiter.cs` — **new**. `IMicrophoneArbiter`, `IMicrophoneLease`, `MicrophoneOwner`.
- `Services/MicrophoneArbiter.cs` — **new**. Owns the single capture graph, issues leases.
- `Services/IWakeWordDetector.cs` — **new**. Interface + `WakeWordDetection`.
- `Services/WakeWordKeywordResolver.cs` — **new**. Enabled phrases → `.ppn` paths + sensitivities.
- `Services/Endpointer.cs` — **new**. Pure DSP.
- `Services/IChimePlayer.cs` / `ChimePlayer.cs` — **new**.
- `Services/PorcupineWakeWordDetector.cs` — **new**. The only file referencing the Porcupine SDK.
- `Services/IComposerSink.cs` — **new**. `void AppendTranscription(string text)` plus `Task<WakeWordSubmitResult> SubmitTranscriptionAsync(string text, CancellationToken cancellationToken = default)` or equivalent `AssistantViewModel` entry point that reuses `SendMessageCoreAsync`.
- `ViewModels/WakeWordCoordinator.cs` — **new**. The state machine. No WinUI types beyond `DispatcherQueue`, no Porcupine types, no command parsing.
- `ViewModels/AssistantViewModel.cs` — **modify**. Implement `IComposerSink`; take a lease for Hold-to-Talk.
- `Services/WindowsVoiceDevice.cs` — **modify**. Capture through a lease instead of its own `MediaCapture`.
- `MainWindow.xaml` / `.xaml.cs`, `App.xaml.cs` — **modify**.
- Tests: `WakePhraseTests`, `WakeWordUiStateTests`, `WakeWordKeywordResolverTests`, `EndpointerTests`, `MicrophoneArbiterTests`, `WakeWordCoordinatorTests`. No test file for `PorcupineWakeWordDetector` or the arbiter's real capture graph — established precedent for real OS/SDK dependencies (`WindowsVoiceDevice`, `WindowsAppExecutor`), verified in Task 9.
- `desktop/tests/Reva.Desktop.Tests/Unit/Fakes/` — **new**. Shared `FakeCoreClient`, `FakeCoreLifecycle`, `TestWav`. Three plans have now written three divergent `FakeCoreClient`s; this task consolidates them.

---

### Task 0: Confirm the gate, then re-verify against the code that actually landed

**Files:** none (read-only).

- [ ] **Step 1: Confirm the gate has cleared.** Check the app-command routing plan's task list and Task 7 report, and the transcription slice's Task 9 status, directly. Do not proceed on this plan's age.

- [ ] **Step 2: Re-read what shipped.** `AssistantViewModel.cs`, `WindowsVoiceDevice.cs`, `CommandRouter.cs`, `AppAllowlist.cs`. Record, in writing:
  1. The exact name and signature of the private append helper `FinishVoiceInputAsync` uses (the app-command plan calls it `AppendTranscribedText`) — Task 7's `IComposerSink` implementation delegates to it.
  2. How `_composerSource` is set and cleared, and confirm a wake-word write can mark it `Transcribed`.
  2a. The exact `AssistantViewModel` entry point wake word will use to submit transcribed text through `ICommandRouter`, restore `NotACommand` text to the composer, and avoid Core/ADK/LLM for ordinary speech.
  3. `WindowsVoiceDevice`'s current capture shape — what it constructs, how it produces WAV bytes, where the temp file lives, and where it is deleted. Task 4 moves this behind a lease and must not lose behavior.
  4. Whether `[InternalsVisibleTo]` is already configured for the test project.
  5. Whether `DispatcherQueue.GetForCurrentThread()` returns null (not throws) on an xUnit thread — the transcription slice's Task 0 should already have this answer; confirm it still holds.

- [ ] **Step 3: Confirm the licensing gate item is still true**, and that a Picovoice SDK version is available that matches it.

- [ ] **Step 4: Commit the recon note** to `docs/superpowers/specs/2026-08-17-wake-word-recon.md`.

### Required asymmetric integration tests

Add focused tests before implementation for:

- wake + open chrome reaches `ICommandRouter` as `CommandSource.Transcribed` and never Core;
- wake + close chrome creates confirmation but does not close;
- wake + spoken confirm cannot approve closure;
- typed confirm still approves;
- ordinary wake transcript populates composer without Core/ADK;
- Hold-to-Talk blocks wake capture;
- wake capture blocks Hold-to-Talk;
- detector resumes after STT failure/cancellation;
- no transcript, audio, or exception details are logged.

---

### Task 1: Consolidate test fakes

Doing this first because three of the six later test files would otherwise each grow their own `FakeCoreClient`, and two already have divergent ones in the shipped code.

**Files:**
- Create: `desktop/tests/Reva.Desktop.Tests/Unit/Fakes/TestWav.cs` (move from wherever the transcription slice left it)
- Create: `desktop/tests/Reva.Desktop.Tests/Unit/Fakes/FakeCoreClient.cs`
- Create: `desktop/tests/Reva.Desktop.Tests/Unit/Fakes/FakeCoreLifecycle.cs`
- Modify: `AssistantViewModelTests.cs` — delete its nested copies, use the shared ones.

- [ ] **Step 1: Extract without changing behavior**

`FakeCoreClient` takes optional per-method responders; every unsupplied method throws `NotSupportedException` with a message naming the method, so a test that accidentally reaches an unexpected endpoint fails loudly rather than returning a default.

```csharp
namespace Reva.Desktop.Tests.Unit.Fakes;

internal sealed class FakeCoreClient : IRevaCoreClient
{
    private readonly Func<string, CancellationToken, Task<CoreResult<TypedMessageResponse>>>? _send;
    private readonly Func<byte[], CancellationToken, Task<CoreResult<VoiceTranscriptionResponse>>>? _transcribe;
    private readonly Func<string, string, CancellationToken, Task<CoreResult<byte[]>>>? _synthesize;

    public FakeCoreClient(
        Func<string, CancellationToken, Task<CoreResult<TypedMessageResponse>>>? send = null,
        Func<byte[], CancellationToken, Task<CoreResult<VoiceTranscriptionResponse>>>? transcribe = null,
        Func<string, string, CancellationToken, Task<CoreResult<byte[]>>>? synthesize = null)
    {
        _send = send;
        _transcribe = transcribe;
        _synthesize = synthesize;
    }

    public int CallCount { get; private set; }
    public int TranscribeCallCount { get; private set; }
    public int SynthesizeCallCount { get; private set; }

    public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(string content, CancellationToken ct = default)
    {
        CallCount++;
        return _send?.Invoke(content, ct)
            ?? throw new NotSupportedException("SendMessageAsync was not expected in this test.");
    }

    public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(byte[] wav, CancellationToken ct = default)
    {
        TranscribeCallCount++;
        return _transcribe?.Invoke(wav, ct)
            ?? throw new NotSupportedException("TranscribeSpeechAsync was not expected in this test.");
    }

    public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(string text, string lang, CancellationToken ct = default)
    {
        SynthesizeCallCount++;
        return _synthesize?.Invoke(text, lang, ct)
            ?? throw new NotSupportedException("SynthesizeSpeechAsync was not expected in this test.");
    }

    public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken ct = default) =>
        throw new NotSupportedException(nameof(GetHealthAsync));
    public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken ct = default) =>
        throw new NotSupportedException(nameof(GetVersionAsync));
    public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(string c, CancellationToken ct = default) =>
        throw new NotSupportedException(nameof(CreateMemoryAsync));
    public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(string q, int l, CancellationToken ct = default) =>
        throw new NotSupportedException(nameof(QueryMemoriesAsync));

    public static FakeCoreClient Transcribing(string text) => new(
        transcribe: (_, _) => Task.FromResult(
            CoreResult<VoiceTranscriptionResponse>.Success(new VoiceTranscriptionResponse(1, text, "en", 900))));
}
```

- [ ] **Step 2: Full suite must stay green**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures. This is a pure refactor — any behavior change here is a bug in the extraction, not an improvement.

- [ ] **Step 3: Commit**

```bash
git add desktop/tests/Reva.Desktop.Tests/Unit/Fakes desktop/tests/Reva.Desktop.Tests/Unit/AssistantViewModelTests.cs
git commit -m "test(desktop): consolidate shared test fakes"
```

---

### Task 2: Phrase types + UI states + keyword resolution

**Files:**
- Create: `Services/WakePhrase.cs`, `State/WakeWordUiState.cs`, `Services/IWakeWordDetector.cs`, `Services/WakeWordKeywordResolver.cs`
- Test: `WakePhraseTests.cs`, `WakeWordUiStateTests.cs`, `WakeWordKeywordResolverTests.cs`

- [ ] **Step 1: Write the failing tests**

```csharp
public class WakePhraseTests
{
    [Fact]
    public void Defaults_HasFourPhrases() => Assert.Equal(4, WakePhraseDefaults.All.Count);

    [Fact]
    public void Defaults_OnlyHeyRevaEnabledByDefault()
    {
        var enabled = WakePhraseDefaults.All.Where(p => p.Enabled).Select(p => p.Phrase).ToList();

        Assert.Equal(new[] { WakePhrase.HeyReva }, enabled);
    }

    [Theory]
    [InlineData(WakePhrase.HeyReva, 0.55f)]
    [InlineData(WakePhrase.YouUpReva, 0.45f)]
    [InlineData(WakePhrase.DaddysHome, 0.45f)]
    [InlineData(WakePhrase.RevaWakeUp, 0.40f)]
    public void Defaults_MatchDesignDocSensitivities(WakePhrase phrase, float expected)
    {
        Assert.Equal(expected, WakePhraseDefaults.All.Single(p => p.Phrase == phrase).Sensitivity);
    }

    [Fact]
    public void Defaults_NoBareTwoSyllableWakeUpPhrase()
    {
        // Regression guard for the resolved decision: the 2-syllable "wake up"
        // must never come back. "Reva wake up" is the shippable form.
        Assert.DoesNotContain(WakePhraseDefaults.All, p => p.Phrase.ToString() == "WakeUp");
    }

    [Fact]
    public void Defaults_EverySensitivityIsInPorcupinesValidRange()
    {
        foreach (var setting in WakePhraseDefaults.All)
        {
            Assert.InRange(setting.Sensitivity, 0f, 1f);
        }
    }
}
```

```csharp
public class WakeWordUiStateTests
{
    [Theory]
    [InlineData(WakeWordUiState.Off, "Wake Word Off")]
    [InlineData(WakeWordUiState.Starting, "Starting")]
    [InlineData(WakeWordUiState.Armed, "Wake Word Armed")]
    [InlineData(WakeWordUiState.Detected, "Detected")]
    [InlineData(WakeWordUiState.Listening, "Listening")]
    [InlineData(WakeWordUiState.Transcribing, "Transcribing")]
    [InlineData(WakeWordUiState.Cooldown, "Cooldown")]
    [InlineData(WakeWordUiState.MicrophoneUnavailable, "Microphone Unavailable")]
    [InlineData(WakeWordUiState.SttUnavailable, "STT Unavailable")]
    [InlineData(WakeWordUiState.WakeWordError, "Wake Word Error")]
    public void For_ReturnsExactRequiredText(WakeWordUiState state, string expected) =>
        Assert.Equal(expected, WakeWordUiStateText.For(state));

    [Fact]
    public void For_CoversEveryEnumMember()
    {
        foreach (WakeWordUiState state in Enum.GetValues<WakeWordUiState>())
        {
            Assert.False(string.IsNullOrWhiteSpace(WakeWordUiStateText.For(state)));
        }
    }
}
```

```csharp
public class WakeWordKeywordResolverTests
{
    private sealed class FakeFileSystemProbe : IFileSystemProbe
    {
        private readonly HashSet<string> _present;
        public FakeFileSystemProbe(IEnumerable<string> present) => _present = new(present, StringComparer.OrdinalIgnoreCase);
        public bool Exists(string path) => _present.Contains(path);
    }

    private static readonly WakePhraseSetting HeyReva = new(WakePhrase.HeyReva, true, 0.55f);
    private static readonly WakePhraseSetting YouUpReva = new(WakePhrase.YouUpReva, true, 0.45f);

    [Fact]
    public void Resolve_AllFilesPresent_ReturnsPathsSensitivitiesAndOrderInLockstep()
    {
        var fs = new FakeFileSystemProbe(new[] { @"C:\kw\hey-reva.ppn", @"C:\kw\you-up-reva.ppn" });

        var resolution = WakeWordKeywordResolver.Resolve(new[] { HeyReva, YouUpReva }, @"C:\kw", fs);

        Assert.True(resolution.IsSuccess);
        Assert.Equal(new[] { @"C:\kw\hey-reva.ppn", @"C:\kw\you-up-reva.ppn" }, resolution.KeywordPaths);
        Assert.Equal(new[] { 0.55f, 0.45f }, resolution.Sensitivities);
        Assert.Equal(new[] { WakePhrase.HeyReva, WakePhrase.YouUpReva }, resolution.PhraseOrder);
    }

    [Fact]
    public void Resolve_ThreeParallelArrays_AreAlwaysTheSameLength()
    {
        // The paired-array invariant. A mismatch here silently applies the
        // wrong sensitivity to every phrase and mislabels every detection —
        // and nothing downstream can detect it.
        var fs = new FakeFileSystemProbe(new[] { @"C:\kw\hey-reva.ppn", @"C:\kw\you-up-reva.ppn" });

        var resolution = WakeWordKeywordResolver.Resolve(new[] { HeyReva, YouUpReva }, @"C:\kw", fs);

        Assert.Equal(resolution.KeywordPaths!.Count, resolution.Sensitivities!.Count);
        Assert.Equal(resolution.KeywordPaths!.Count, resolution.PhraseOrder!.Count);
    }

    [Fact]
    public void Resolve_MissingKeywordFile_FailsNamingThePhrase_ArmsNothing()
    {
        var fs = new FakeFileSystemProbe(new[] { @"C:\kw\hey-reva.ppn" });

        var resolution = WakeWordKeywordResolver.Resolve(new[] { HeyReva, YouUpReva }, @"C:\kw", fs);

        Assert.False(resolution.IsSuccess);
        Assert.Equal(WakePhrase.YouUpReva, resolution.MissingPhrase);
        Assert.Null(resolution.KeywordPaths);
    }

    [Fact]
    public void Resolve_NoEnabledPhrases_ReturnsFailure_NeverArmsEmpty()
    {
        var resolution = WakeWordKeywordResolver.Resolve(
            Array.Empty<WakePhraseSetting>(), @"C:\kw", new FakeFileSystemProbe(Array.Empty<string>()));

        Assert.False(resolution.IsSuccess);
    }

    [Fact]
    public void Resolve_DisabledPhraseIsExcluded_ItsMissingFileDoesNotFailResolution()
    {
        var fs = new FakeFileSystemProbe(new[] { @"C:\kw\hey-reva.ppn" });

        var resolution = WakeWordKeywordResolver.Resolve(
            new[] { HeyReva, YouUpReva with { Enabled = false } }, @"C:\kw", fs);

        Assert.True(resolution.IsSuccess);
        Assert.Single(resolution.KeywordPaths!);
    }
}
```

- [ ] **Step 2: Run to verify they fail.** `dotnet test desktop/Reva.Desktop.sln --filter "WakePhraseTests|WakeWordUiStateTests|WakeWordKeywordResolverTests"` → FAIL (build errors).

- [ ] **Step 3: Implement**

```csharp
namespace Reva.Desktop.Services;

public enum WakePhrase { HeyReva, YouUpReva, DaddysHome, RevaWakeUp }

public sealed record WakePhraseSetting(WakePhrase Phrase, bool Enabled, float Sensitivity);

public sealed record WakeWordConfiguration(IReadOnlyList<WakePhraseSetting> Phrases);

public static class WakePhraseDefaults
{
    /// <summary>Display strings are separate from training strings: Picovoice
    /// Console takes lowercase words with no punctuation, so "Daddy's home"
    /// trains as "daddys home". Keeping both here stops them drifting.</summary>
    public static string DisplayName(WakePhrase phrase) => phrase switch
    {
        WakePhrase.HeyReva => "Hey Reva",
        WakePhrase.YouUpReva => "You up Reva",
        WakePhrase.DaddysHome => "Daddy's home",
        WakePhrase.RevaWakeUp => "Reva wake up",
        _ => throw new ArgumentOutOfRangeException(nameof(phrase)),
    };

    public static readonly IReadOnlyList<WakePhraseSetting> All = new[]
    {
        new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f),
        new WakePhraseSetting(WakePhrase.YouUpReva, Enabled: false, Sensitivity: 0.45f),
        new WakePhraseSetting(WakePhrase.DaddysHome, Enabled: false, Sensitivity: 0.45f),
        new WakePhraseSetting(WakePhrase.RevaWakeUp, Enabled: false, Sensitivity: 0.40f),
    };
}
```

`WakeWordUiState.cs` — the 10-member enum plus `WakeWordUiStateText.For`, exactly as the test's `[InlineData]` table specifies, mirroring `VoiceUiStateText`.

`IWakeWordDetector.cs`:

```csharp
namespace Reva.Desktop.Services;

public sealed record WakeWordDetection(WakePhrase Phrase, DateTimeOffset DetectedAtUtc);

/// <summary>Provider seam. Note there is no Suspend/Resume: the lease IS the
/// microphone, so suspending means stopping and disposing the lease. v1 had
/// Suspend/Resume that toggled an advisory flag while the capture loop kept
/// running — a component could be "suspended" and still reading frames.</summary>
public interface IWakeWordDetector : IAsyncDisposable
{
    bool IsRunning { get; }

    event EventHandler<WakeWordDetection>? Detected;

    Task StartAsync(
        WakeWordConfiguration configuration,
        IMicrophoneLease lease,
        CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);
}
```

`WakeWordKeywordResolver.cs` — as in v1, with `IFileSystemProbe`/`RealFileSystemProbe`, `KeywordResolution(bool IsSuccess, IReadOnlyList<string>? KeywordPaths, IReadOnlyList<float>? Sensitivities, IReadOnlyList<WakePhrase>? PhraseOrder, WakePhrase? MissingPhrase)`, filtering to enabled phrases, failing on the first missing file, and building the three arrays in one loop so they cannot desynchronize.

- [ ] **Step 4: Run to verify they pass. Step 5: Commit.**

```bash
git commit -m "feat(desktop): add wake-word phrase table, UI states, keyword resolution"
```

---

### Task 3: `Endpointer` (RMS + hysteresis + hard cap)

Pure DSP — no I/O, no WinRT, no Porcupine.

**Files:** Create `Services/Endpointer.cs`; test `EndpointerTests.cs`.

- [ ] **Step 1: Write the failing tests**

```csharp
public class EndpointerTests
{
    private const int SampleRate = 16000;
    private const int FrameSamples = 512;                       // 32ms at 16kHz
    private static readonly TimeSpan FrameDuration = TimeSpan.FromMilliseconds(32);

    private static short[] Silence() => new short[FrameSamples];

    private static short[] Loud()
    {
        var frame = new short[FrameSamples];
        for (var i = 0; i < FrameSamples; i++)
        {
            frame[i] = (short)(i % 2 == 0 ? 12000 : -12000);
        }

        return frame;
    }

    private static short[] RoomNoise(short amplitude)
    {
        var frame = new short[FrameSamples];
        var random = new Random(1);   // seeded: this must not be a flaky test
        for (var i = 0; i < FrameSamples; i++)
        {
            frame[i] = (short)random.Next(-amplitude, amplitude);
        }

        return frame;
    }

    private static Endpointer New() => new(TimeSpan.FromMilliseconds(800), TimeSpan.FromSeconds(8), SampleRate);

    [Fact]
    public void ProcessFrame_ContinuousSpeech_NeverSignalsSilence()
    {
        var endpointer = New();
        var elapsed = TimeSpan.Zero;

        for (var i = 0; i < 10; i++)
        {
            Assert.Equal(EndpointerSignal.Continue, endpointer.ProcessFrame(Loud(), elapsed).Signal);
            elapsed += FrameDuration;
        }
    }

    [Fact]
    public void ProcessFrame_SilenceBeforeAnySpeech_NeverEndsTheTurn()
    {
        // Someone triggers the wake word then pauses to think. Ending the turn
        // at 800ms of initial silence would capture nothing at all.
        var endpointer = New();
        var elapsed = TimeSpan.Zero;

        while (elapsed < TimeSpan.FromSeconds(3))
        {
            Assert.Equal(EndpointerSignal.Continue, endpointer.ProcessFrame(Silence(), elapsed).Signal);
            elapsed += FrameDuration;
        }
    }

    [Fact]
    public void ProcessFrame_SilenceAfterSpeech_SignalsAtEightHundredMillisecondsNotBefore()
    {
        var endpointer = New();
        var elapsed = TimeSpan.Zero;

        endpointer.ProcessFrame(Loud(), elapsed);
        var speechEndedAt = elapsed;
        elapsed += FrameDuration;

        TimeSpan? signalledAt = null;
        while (elapsed < TimeSpan.FromMilliseconds(2000) && signalledAt is null)
        {
            if (endpointer.ProcessFrame(Silence(), elapsed).Signal == EndpointerSignal.SilenceReached)
            {
                signalledAt = elapsed;
            }

            elapsed += FrameDuration;
        }

        Assert.NotNull(signalledAt);
        var silenceHeld = signalledAt!.Value - speechEndedAt;
        Assert.InRange(silenceHeld, TimeSpan.FromMilliseconds(800), TimeSpan.FromMilliseconds(880));
    }

    [Fact]
    public void ProcessFrame_BriefMidSentencePause_DoesNotEndTheTurn()
    {
        var endpointer = New();
        var elapsed = TimeSpan.Zero;

        endpointer.ProcessFrame(Loud(), elapsed);
        elapsed += FrameDuration;

        for (var i = 0; i < 5; i++)   // 160ms — well under the 800ms floor
        {
            Assert.Equal(EndpointerSignal.Continue, endpointer.ProcessFrame(Silence(), elapsed).Signal);
            elapsed += FrameDuration;
        }

        Assert.Equal(EndpointerSignal.Continue, endpointer.ProcessFrame(Loud(), elapsed).Signal);
    }

    [Fact]
    public void ProcessFrame_SilenceTimerResetsAfterAPause()
    {
        // 700ms silence, a word, then 700ms more silence must NOT end the turn:
        // the timer restarts, it does not accumulate.
        var endpointer = New();
        var elapsed = TimeSpan.Zero;
        endpointer.ProcessFrame(Loud(), elapsed);
        elapsed += FrameDuration;

        for (var i = 0; i < 21; i++)   // ~672ms
        {
            endpointer.ProcessFrame(Silence(), elapsed);
            elapsed += FrameDuration;
        }

        endpointer.ProcessFrame(Loud(), elapsed);
        elapsed += FrameDuration;

        for (var i = 0; i < 21; i++)
        {
            Assert.Equal(EndpointerSignal.Continue, endpointer.ProcessFrame(Silence(), elapsed).Signal);
            elapsed += FrameDuration;
        }
    }

    [Fact]
    public void ProcessFrame_EightSecondMaximum_SignalsEvenDuringContinuousSpeech()
    {
        var endpointer = New();
        var elapsed = TimeSpan.Zero;

        EndpointerResult? last = null;
        while (elapsed <= TimeSpan.FromSeconds(8))
        {
            last = endpointer.ProcessFrame(Loud(), elapsed);
            elapsed += FrameDuration;
        }

        Assert.Equal(EndpointerSignal.MaximumDurationReached, last!.Signal);
    }

    [Fact]
    public void ProcessFrame_QuietRoomNoise_IsTreatedAsSilence()
    {
        // The threshold must sit above a realistic noise floor, or the turn
        // never ends. This is the assumption the Task 9 calibration checks.
        var endpointer = New();
        var elapsed = TimeSpan.Zero;
        endpointer.ProcessFrame(Loud(), elapsed);
        elapsed += FrameDuration;

        EndpointerResult? last = null;
        while (elapsed < TimeSpan.FromMilliseconds(1200))
        {
            last = endpointer.ProcessFrame(RoomNoise(120), elapsed);
            elapsed += FrameDuration;
        }

        Assert.Equal(EndpointerSignal.SilenceReached, last!.Signal);
    }

    [Fact]
    public void ProcessFrame_EmptyFrame_DoesNotThrow()
    {
        Assert.Equal(EndpointerSignal.Continue, New().ProcessFrame(Array.Empty<short>(), TimeSpan.Zero).Signal);
    }
}
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```csharp
namespace Reva.Desktop.Services;

public enum EndpointerSignal { Continue, SilenceReached, MaximumDurationReached }

public sealed record EndpointerResult(EndpointerSignal Signal);

/// <summary>Energy/RMS voice-activity endpointing with hysteresis. Pure DSP —
/// no capture, no provider dependency, testable against synthetic PCM.</summary>
public sealed class Endpointer
{
    /// <summary>Starting point for 16-bit PCM speech vs. a quiet room.
    /// Calibrated for real against Task 9's acceptance run — a value tuned only
    /// against synthetic square waves will not survive a real noise floor.</summary>
    public const double DefaultRmsThreshold = 500.0;

    private readonly TimeSpan _trailingSilence;
    private readonly TimeSpan _maximumDuration;
    private readonly double _rmsThreshold;

    private TimeSpan? _silenceStartedAt;
    private bool _hasHeardSpeech;

    public Endpointer(
        TimeSpan trailingSilence,
        TimeSpan maximumDuration,
        int sampleRate,
        double rmsThreshold = DefaultRmsThreshold)
    {
        _trailingSilence = trailingSilence;
        _maximumDuration = maximumDuration;
        _rmsThreshold = rmsThreshold;
        _ = sampleRate;   // fixed at 16kHz today; kept for a rate-aware threshold later
    }

    public EndpointerResult ProcessFrame(short[] pcmFrame, TimeSpan elapsedSinceStart)
    {
        if (elapsedSinceStart >= _maximumDuration)
        {
            return new EndpointerResult(EndpointerSignal.MaximumDurationReached);
        }

        if (ComputeRms(pcmFrame) >= _rmsThreshold)
        {
            _hasHeardSpeech = true;
            _silenceStartedAt = null;   // the timer restarts; it never accumulates
            return new EndpointerResult(EndpointerSignal.Continue);
        }

        if (!_hasHeardSpeech)
        {
            // Silence before any speech — the user is still thinking, not done.
            return new EndpointerResult(EndpointerSignal.Continue);
        }

        _silenceStartedAt ??= elapsedSinceStart;
        return elapsedSinceStart - _silenceStartedAt.Value >= _trailingSilence
            ? new EndpointerResult(EndpointerSignal.SilenceReached)
            : new EndpointerResult(EndpointerSignal.Continue);
    }

    private static double ComputeRms(short[] frame)
    {
        if (frame.Length == 0)
        {
            return 0;
        }

        double sumOfSquares = 0;
        foreach (var sample in frame)
        {
            sumOfSquares += (double)sample * sample;
        }

        return Math.Sqrt(sumOfSquares / frame.Length);
    }
}
```

- [ ] **Step 4: Run to verify they pass. Step 5: Commit.**

```bash
git commit -m "feat(desktop): add RMS endpointer with hysteresis and hard cap"
```

---

### Task 4: `MicrophoneArbiter` — single owner of the audio stream

The task v1 got structurally wrong. The arbiter is not a flag; it is the only thing in the app that touches audio input, and it hands out leases.

**Files:**
- Create: `Services/IMicrophoneArbiter.cs`, `Services/MicrophoneArbiter.cs`
- Modify: `Services/WindowsVoiceDevice.cs` — capture through a lease instead of constructing its own `MediaCapture`
- Test: `MicrophoneArbiterTests.cs`

**Interfaces:** `IMicrophoneArbiter.TryAcquireAsync(MicrophoneOwner, CancellationToken) → IMicrophoneLease?`; `IMicrophoneLease : IAsyncDisposable` with `Owner`, `IsActive`, `ReadFramesAsync(int frameLength, CancellationToken)`, `RecordUntilAsync(Func<short[], bool> stopWhen, CancellationToken)`.

> **Why the shape changed.** v1's arbiter tracked ownership while `WindowsVoiceDevice` and `PorcupineWakeWordDetector` each still constructed their own `MediaCapture`. Nothing forced either to ask, v1's `SuspendAsync` released the flag without stopping the capture loop, and `ResumeAsync` discarded the acquire result entirely — so a resume that failed left the detector reporting `IsRunning == true` and the UI reporting "Wake Word Armed" while the microphone belonged to Hold-to-Talk. Making the lease the stream means a component that doesn't hold one cannot read a frame, and a failed resume is a null the caller must handle.

- [ ] **Step 1: Write the failing tests**

```csharp
public class MicrophoneArbiterTests
{
    // The real capture graph is a Task 9 concern (real OS dependency, same
    // precedent as WindowsVoiceDevice). These tests cover the ownership
    // contract, which is where the bugs live.
    private static MicrophoneArbiter NewArbiter() => new(new FakeAudioSource());

    [Fact]
    public async Task TryAcquireAsync_NoCurrentOwner_ReturnsALease()
    {
        var arbiter = NewArbiter();

        await using var lease = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        Assert.NotNull(lease);
        Assert.Equal(MicrophoneOwner.WakeWord, lease!.Owner);
        Assert.True(lease.IsActive);
        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
    }

    [Fact]
    public async Task TryAcquireAsync_AlreadyOwnedByAnother_ReturnsNull_DoesNotChangeOwner()
    {
        var arbiter = NewArbiter();
        await using var first = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        var second = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        Assert.Null(second);
        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
    }

    [Fact]
    public async Task DisposingALease_ReleasesOwnership_AndTheOtherOwnerCanAcquire()
    {
        var arbiter = NewArbiter();
        var wakeWord = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        await wakeWord!.DisposeAsync();

        Assert.Null(arbiter.CurrentOwner);
        await using var holdToTalk = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);
        Assert.NotNull(holdToTalk);
    }

    [Fact]
    public async Task DisposedLease_CannotStillReadFrames()
    {
        // The whole point of the redesign: "suspended" must mean "cannot read",
        // not "promised not to read".
        var arbiter = NewArbiter();
        var lease = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);
        await lease!.DisposeAsync();

        Assert.False(lease.IsActive);
        await Assert.ThrowsAsync<ObjectDisposedException>(async () =>
        {
            await foreach (var _ in lease.ReadFramesAsync(512, CancellationToken.None))
            {
                Assert.Fail("a disposed lease must never yield a frame");
            }
        });
    }

    [Fact]
    public async Task DisposingALeaseTwice_IsSafe()
    {
        var arbiter = NewArbiter();
        var lease = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        await lease!.DisposeAsync();
        await lease.DisposeAsync();

        Assert.Null(arbiter.CurrentOwner);
    }

    [Fact]
    public async Task ADisposedLeaseDoesNotReleaseAnOwnershipItNoLongerHolds()
    {
        // Stale-lease guard: dispose a lease, let the other owner acquire, then
        // dispose the stale one again. It must not evict the live owner.
        var arbiter = NewArbiter();
        var wakeWord = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);
        await wakeWord!.DisposeAsync();
        await using var holdToTalk = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        await wakeWord.DisposeAsync();

        Assert.Equal(MicrophoneOwner.HoldToTalk, arbiter.CurrentOwner);
    }

    [Fact]
    public async Task ReadFramesAsync_YieldsExactlyFrameLengthSamples()
    {
        // Porcupine rejects partial frames; the lease is where that is guaranteed.
        var arbiter = NewArbiter();
        await using var lease = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        using var cts = new CancellationTokenSource();
        var count = 0;
        await foreach (var frame in lease!.ReadFramesAsync(512, cts.Token))
        {
            Assert.Equal(512, frame.Length);
            if (++count == 5)
            {
                cts.Cancel();
            }
        }

        Assert.Equal(5, count);
    }

    [Fact]
    public async Task ConcurrentAcquire_OnlyOneWins()
    {
        var arbiter = NewArbiter();

        var results = await Task.WhenAll(
            Enumerable.Range(0, 16).Select(i => arbiter.TryAcquireAsync(
                i % 2 == 0 ? MicrophoneOwner.WakeWord : MicrophoneOwner.HoldToTalk).AsTask()));

        Assert.Single(results.Where(lease => lease is not null));
    }
}
```

`FakeAudioSource` (in `Fakes/`) implements the arbiter's internal `IAudioSource` — an infinite generator of synthetic 16kHz mono frames — so the ownership contract is testable without hardware.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

```csharp
namespace Reva.Desktop.Services;

public enum MicrophoneOwner { WakeWord, HoldToTalk }

public interface IMicrophoneLease : IAsyncDisposable
{
    MicrophoneOwner Owner { get; }
    bool IsActive { get; }
    IAsyncEnumerable<short[]> ReadFramesAsync(int frameLength, CancellationToken cancellationToken);
    Task<byte[]> RecordUntilAsync(Func<short[], bool> stopWhen, CancellationToken cancellationToken);
}

/// <summary>The single owner of audio input. There is no other way to obtain a
/// frame — a component without a lease cannot capture, by construction rather
/// than by convention.</summary>
public interface IMicrophoneArbiter
{
    MicrophoneOwner? CurrentOwner { get; }

    Task<IMicrophoneLease?> TryAcquireAsync(
        MicrophoneOwner owner, CancellationToken cancellationToken = default);
}
```

`MicrophoneArbiter` holds a `SemaphoreSlim(1,1)` (not a `lock` — acquisition starts the capture graph and is genuinely async), a `MicrophoneOwner? _currentOwner`, and a generation counter so a stale lease's `DisposeAsync` cannot release a newer owner's claim. Each lease wraps the shared `IAudioSource`, buffers into exact `frameLength` chunks, and on disposal stops the source and clears ownership *only if its generation is still current*.

`RecordUntilAsync` accumulates frames into the same 16kHz mono PCM WAV format `WindowsVoiceDevice` already produces, so `WavAudio.TryGetDurationMs` and the existing 250ms floor apply unchanged.

- [ ] **Step 4: Move `WindowsVoiceDevice` onto a lease**

`WindowsVoiceDevice` takes an `IMicrophoneArbiter`, acquires `MicrophoneOwner.HoldToTalk` in `StartRecordingAsync`, records through `RecordUntilAsync`, and disposes the lease in a `finally` in `StopRecordingAsync` — including on the cancel and error paths. **A null lease means the microphone is busy**, which surfaces as the existing `VoiceCaptureException` with a safe message, so the transcription slice's `VoiceUiState` handling covers it with no new state.

Run the full suite: every existing transcription-slice test must still pass unchanged. If any voice test needs editing beyond constructor wiring, behavior was lost — stop and fix it.

- [ ] **Step 5: Run to verify they pass, then the full suite.**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(desktop): make the microphone arbiter own the audio stream via leases"
```

---

### Task 5: `PorcupineWakeWordDetector`

No unit tests — real native SDK dependency, same precedent as `WindowsVoiceDevice`/`WindowsAppExecutor`. **But unlike v1, this task ships a complete listen loop.** v1 stubbed `RunListenLoopAsync` as `await Task.CompletedTask` and deferred it to its Task 8, which meant the detector compiled, reported `IsRunning == true`, and never detected anything — and no task in between owned frame delivery at all. With Task 4's lease, the loop is a dozen lines and there is nothing left to defer.

**Files:** Create `Services/PorcupineWakeWordDetector.cs`; modify `Reva.Desktop.csproj`.

- [ ] **Step 1: Add the package reference**

`<PackageReference Include="Porcupine" Version="…" />` — pin the exact version verified against Task 0 Step 3's licensing check. The version is filled in at implementation time from the licensed SDK, not guessed now.

- [ ] **Step 2: Implement**

```csharp
using Pv;

namespace Reva.Desktop.Services;

public sealed class PorcupineWakeWordDetector : IWakeWordDetector
{
    private readonly string _accessKey;
    private readonly string _keywordDirectory;
    private readonly IFileSystemProbe _fileSystem;

    private Porcupine? _porcupine;
    private IReadOnlyList<WakePhrase>? _phraseOrder;
    private CancellationTokenSource? _loopCancellation;
    private Task? _loop;

    public PorcupineWakeWordDetector(string accessKey, string keywordDirectory, IFileSystemProbe fileSystem)
    {
        _accessKey = accessKey;
        _keywordDirectory = keywordDirectory;
        _fileSystem = fileSystem;
    }

    public bool IsRunning => _loop is { IsCompleted: false };

    public event EventHandler<WakeWordDetection>? Detected;

    public Task StartAsync(
        WakeWordConfiguration configuration, IMicrophoneLease lease, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(_accessKey))
        {
            throw new WakeWordConfigurationException("Wake word requires a configured access key.");
        }

        var resolution = WakeWordKeywordResolver.Resolve(configuration.Phrases, _keywordDirectory, _fileSystem);
        if (!resolution.IsSuccess)
        {
            throw resolution.MissingPhrase is { } missing
                ? new WakeWordConfigurationException($"Missing keyword file for {WakePhraseDefaults.DisplayName(missing)}.")
                : new WakeWordConfigurationException("No wake phrases are enabled.");
        }

        // One instance for every enabled keyword — never one per phrase.
        _porcupine = Porcupine.FromKeywordPaths(
            _accessKey,
            resolution.KeywordPaths!.ToArray(),
            sensitivities: resolution.Sensitivities!.ToArray());
        _phraseOrder = resolution.PhraseOrder;

        if (_porcupine.SampleRate != 16000)
        {
            throw new WakeWordConfigurationException(
                "Wake word requires a 16kHz model to match the capture format.");
        }

        _loopCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _loop = RunListenLoopAsync(lease, _porcupine.FrameLength, _loopCancellation.Token);
        return Task.CompletedTask;
    }

    private async Task RunListenLoopAsync(IMicrophoneLease lease, int frameLength, CancellationToken cancellationToken)
    {
        try
        {
            // The lease guarantees exactly frameLength samples of 16kHz mono
            // PCM per iteration — Porcupine rejects partial frames, and this is
            // the only place that contract has to hold.
            await foreach (var frame in lease.ReadFramesAsync(frameLength, cancellationToken))
            {
                var index = _porcupine!.Process(frame);
                if (index >= 0 && _phraseOrder is { } order && index < order.Count)
                {
                    Detected?.Invoke(this, new WakeWordDetection(order[index], DateTimeOffset.UtcNow));
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Normal stop.
        }
        catch (ObjectDisposedException)
        {
            // The lease was disposed out from under us — also a normal stop
            // (Hold-to-Talk took the microphone).
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        _loopCancellation?.Cancel();
        if (_loop is not null)
        {
            try
            {
                await _loop.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }

        _loop = null;
        _loopCancellation?.Dispose();
        _loopCancellation = null;
        _porcupine?.Dispose();
        _porcupine = null;
        _phraseOrder = null;
    }

    public async ValueTask DisposeAsync() => await StopAsync().ConfigureAwait(false);
}

public sealed class WakeWordConfigurationException : Exception
{
    public WakeWordConfigurationException(string message) : base(message)
    {
    }
}
```

Note `IsRunning` is derived from the loop task, not from `_porcupine is not null` — v1's version reported "running" for a detector whose loop had never started or had already died.

The detector does **not** touch the arbiter. Acquisition happens in exactly one place (the coordinator), which is what makes Task 7's `MicrophoneUnavailable` test meaningful rather than vacuous.

- [ ] **Step 3: Build. Step 4: Commit.**

```bash
git commit -m "feat(desktop): add PorcupineWakeWordDetector (single instance, N keywords)"
```

---

### Task 6: Chime asset + player

**Files:** the chime asset; `Services/IChimePlayer.cs`, `Services/ChimePlayer.cs`; `.csproj`.

**Asset spec:**
- `.wav`, mono, 16-bit PCM — consistent with the rest of the audio handling, no new decode dependency.
- Duration ≤ 400ms. Perceptible, and short enough that the discarded capture prefix (below) costs almost nothing.
- Peak ≈ -6 dBFS. Present but not startling at normal system volume.
- Delivered as an embedded resource; played through the same `MediaPlayer`/`InMemoryRandomAccessStream` pattern `WindowsVoiceDevice` already uses for WAV bytes. **Never through `SynthesizeSpeechAsync` or the TTS path** — this is about the playback helper, not the speech pipeline.

- [ ] **Step 1: Source or record the chime.** A short, simple, non-startling one- or two-tone chime. A genuine asset-creation step; flag it explicitly if no suitable asset exists and it blocks the task.

- [ ] **Step 2: Verify format, duration, and peak level** (`ffprobe` or equivalent) against the spec.

- [ ] **Step 3: Pin the discard constant.** Define `ChimePlayer.CapturePrefixToDiscard = <asset duration> + 100ms margin`. Capture starts immediately on detection and the chime plays concurrently, so this prefix is trimmed from the captured audio before the 250ms floor is applied. Without it the chime is inside the recording and will transcribe as a spurious token — v1 asserted the `Detected` state prevented overlap but nothing enforced it.

- [ ] **Step 4: Implement `IChimePlayer { Task PlayAsync(CancellationToken); }` and `ChimePlayer`.** A standalone component, not a method on the detector, so the coordinator can suppress it on the Core-disconnected path without reaching into the detector.

- [ ] **Step 5: Build. Step 6: Commit.**

```bash
git commit -m "feat(desktop): add wake-word activation chime"
```

---

### Task 7: `WakeWordCoordinator` — the state machine

**Files:** Create `Services/IComposerSink.cs`, `ViewModels/WakeWordCoordinator.cs`; modify `ViewModels/AssistantViewModel.cs`; test `WakeWordCoordinatorTests.cs`.

**Interfaces:**
- Consumes: `IWakeWordDetector`, `IMicrophoneArbiter`, `Endpointer`, `IChimePlayer`, `IRevaCoreClient.TranscribeSpeechAsync`, `IComposerSink`, `IRevaCoreLifecycle`, `TimeProvider`.
- Produces: `WakeWordCoordinator(IWakeWordDetector, IMicrophoneArbiter, IRevaCoreClient, IComposerSink, IChimePlayer, IRevaCoreLifecycle? = null, TimeProvider? = null)`; `WakeWordUiState State`; `bool IsArmed`; `int DroppedDetectionCount`; `EnableAsync`, `DisableAsync`, `SuspendForHoldToTalkAsync`, `ResumeAfterHoldToTalkAsync`.

- [ ] **Step 1: `IComposerSink` — with real append semantics**

```csharp
namespace Reva.Desktop.Services;

/// <summary>The seam WakeWordCoordinator writes transcribed text through.
/// AssistantViewModel implements it by delegating to the SAME private append
/// helper FinishVoiceInputAsync uses, so draft preservation and
/// transcribed-source marking have exactly one implementation.</summary>
public interface IComposerSink
{
    void AppendTranscription(string text);
}
```

> **This is the v1 defect that mattered most.** v1 defined the seam as `{ string ComposerText { get; set; } }` and asserted `AssistantViewModel` "already has exactly the right append semantics." It does not — the append lives *inside* `FinishVoiceInputAsync`, not in the setter. Writing through v1's sink would have silently overwritten the user's draft, and v1's own `Detection_ExistingComposerDraftIsPreserved_TranscriptAppends` test could not have passed with its plain-auto-property fake. Worse, making it pass would have meant duplicating the append logic into the coordinator — the exact reimplementation the design forbids.

On `AssistantViewModel`, add `: IComposerSink` and:

```csharp
    public void AppendTranscription(string text) => AppendTranscribedText(text);
```

That single line is the whole implementation, and it carries the `CommandSource.Transcribed` marking with it — which is what stops a hands-free "confirm" from closing an app.

- [ ] **Step 2: Write the failing tests**

```csharp
public class WakeWordCoordinatorTests
{
    private sealed class FakeWakeWordDetector : IWakeWordDetector
    {
        public bool IsRunning { get; private set; }
        public int StartCallCount { get; private set; }
        public int StopCallCount { get; private set; }
        public IMicrophoneLease? LastLease { get; private set; }
        public Exception? StartThrows { get; set; }

        public event EventHandler<WakeWordDetection>? Detected;

        public void RaiseDetected(WakePhrase phrase) =>
            Detected?.Invoke(this, new WakeWordDetection(phrase, DateTimeOffset.UtcNow));

        public Task StartAsync(WakeWordConfiguration configuration, IMicrophoneLease lease, CancellationToken ct = default)
        {
            if (StartThrows is not null)
            {
                throw StartThrows;
            }

            StartCallCount++;
            LastLease = lease;
            IsRunning = true;
            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken ct = default)
        {
            StopCallCount++;
            IsRunning = false;
            return Task.CompletedTask;
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class FakeComposerSink : IComposerSink
    {
        public string Text { get; private set; } = string.Empty;

        public FakeComposerSink(string initial = "") => Text = initial;

        // Mirrors AssistantViewModel.AppendTranscribedText exactly. If these
        // two ever diverge, the coordinator is relying on behavior the real
        // sink doesn't have — which is precisely how v1's version was wrong.
        public void AppendTranscription(string text) =>
            Text = string.IsNullOrWhiteSpace(Text) ? text : $"{Text.TrimEnd()} {text}";
    }

    private sealed class FakeChimePlayer : IChimePlayer
    {
        public int PlayCallCount { get; private set; }

        public Task PlayAsync(CancellationToken ct = default)
        {
            PlayCallCount++;
            return Task.CompletedTask;
        }
    }

    private sealed class ManualTimeProvider : TimeProvider
    {
        public DateTimeOffset UtcNow { get; set; } = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => UtcNow;
    }

    private static WakeWordConfiguration DefaultConfig() => new(WakePhraseDefaults.All);

    // --- Enable / disable ---

    [Fact]
    public void InitialState_IsOff()
    {
        var coordinator = NewCoordinator(out _, out _, out _);

        Assert.Equal(WakeWordUiState.Off, coordinator.State);
        Assert.False(coordinator.IsArmed);
    }

    [Fact]
    public async Task EnableAsync_AcquiresTheMicrophoneAndStartsTheDetectorOnce()
    {
        var coordinator = NewCoordinator(out var detector, out var arbiter, out _);

        await coordinator.EnableAsync(DefaultConfig());

        Assert.Equal(1, detector.StartCallCount);
        Assert.NotNull(detector.LastLease);
        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
        Assert.Equal(WakeWordUiState.Armed, coordinator.State);
    }

    [Fact]
    public async Task EnableAsync_MicrophoneAlreadyHeld_ReportsMicrophoneUnavailable_NeverStartsTheDetector()
    {
        // v1's version of this test passed vacuously: its fake detector ignored
        // the arbiter entirely, so nothing was actually being verified. With
        // acquisition in the coordinator, the assertion is real.
        var arbiter = new MicrophoneArbiter(new FakeAudioSource());
        await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);
        var detector = new FakeWakeWordDetector();
        var coordinator = NewCoordinator(detector, arbiter);

        await coordinator.EnableAsync(DefaultConfig());

        Assert.Equal(WakeWordUiState.MicrophoneUnavailable, coordinator.State);
        Assert.False(coordinator.IsArmed);
        Assert.Equal(0, detector.StartCallCount);
    }

    [Fact]
    public async Task EnableAsync_DetectorConfigurationFails_ReportsWakeWordError_AndReleasesTheMicrophone()
    {
        var arbiter = new MicrophoneArbiter(new FakeAudioSource());
        var detector = new FakeWakeWordDetector
        {
            StartThrows = new WakeWordConfigurationException("Missing keyword file for Daddy's home."),
        };
        var coordinator = NewCoordinator(detector, arbiter);

        await coordinator.EnableAsync(DefaultConfig());

        Assert.Equal(WakeWordUiState.WakeWordError, coordinator.State);
        Assert.Contains("Daddy's home", coordinator.ErrorMessage);
        Assert.Null(arbiter.CurrentOwner);   // no leaked lease on the failure path
    }

    [Fact]
    public async Task EnableAsync_ErrorMessage_NeverContainsTheAccessKey()
    {
        var detector = new FakeWakeWordDetector
        {
            StartThrows = new WakeWordConfigurationException("Wake word requires a configured access key."),
        };
        var coordinator = NewCoordinator(detector, new MicrophoneArbiter(new FakeAudioSource()));

        await coordinator.EnableAsync(DefaultConfig());

        Assert.Equal(WakeWordUiState.WakeWordError, coordinator.State);
        Assert.DoesNotContain("=", coordinator.ErrorMessage);   // no key-ish fragment
    }

    [Fact]
    public async Task DisableAsync_StopsTheDetectorAndReleasesTheMicrophone()
    {
        var coordinator = NewCoordinator(out var detector, out var arbiter, out _);
        await coordinator.EnableAsync(DefaultConfig());

        await coordinator.DisableAsync();

        Assert.Equal(1, detector.StopCallCount);
        Assert.Null(arbiter.CurrentOwner);
        Assert.Equal(WakeWordUiState.Off, coordinator.State);
    }

    // --- Detection turn ---

    [Fact]
    public async Task Detection_PopulatesComposer_ChimesOnce_NeverSendsOrSpeaks()
    {
        var time = new ManualTimeProvider();
        var composer = new FakeComposerSink();
        var chime = new FakeChimePlayer();
        var client = FakeCoreClient.Transcribing("open Chrome");
        var coordinator = NewCoordinator(client, composer, chime, time, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal(1, chime.PlayCallCount);
        Assert.Equal("open Chrome", composer.Text);
        Assert.Equal(0, client.CallCount);          // never SendMessageAsync
        Assert.Equal(0, client.SynthesizeCallCount); // never TTS
        Assert.Equal(WakeWordUiState.Cooldown, coordinator.State);

        time.UtcNow = time.UtcNow.AddSeconds(2);
        await coordinator.WaitForCooldownAsync();
        Assert.Equal(WakeWordUiState.Armed, coordinator.State);
    }

    [Fact]
    public async Task Detection_ExistingDraftIsPreserved_TranscriptAppends()
    {
        var composer = new FakeComposerSink("typed draft");
        var coordinator = NewCoordinator(FakeCoreClient.Transcribing("and this too"), composer, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal("typed draft and this too", composer.Text);
    }

    [Theory]
    [InlineData(WakePhrase.HeyReva)]
    [InlineData(WakePhrase.YouUpReva)]
    [InlineData(WakePhrase.DaddysHome)]
    [InlineData(WakePhrase.RevaWakeUp)]
    public async Task Detection_EveryPhraseProducesIdenticalDownstreamBehavior(WakePhrase phrase)
    {
        var composer = new FakeComposerSink();
        var chime = new FakeChimePlayer();
        var coordinator = NewCoordinator(FakeCoreClient.Transcribing("hello"), composer, chime, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(phrase);
        await coordinator.WaitForTurnAsync();

        Assert.Equal("hello", composer.Text);
        Assert.Equal(1, chime.PlayCallCount);
    }

    [Fact]
    public async Task Detection_EmptyTranscript_IsAFailure_NotASilentSuccess()
    {
        var composer = new FakeComposerSink();
        var coordinator = NewCoordinator(FakeCoreClient.Transcribing("   "), composer, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Equal(string.Empty, composer.Text);
        Assert.NotNull(coordinator.ErrorMessage);
    }

    [Fact]
    public async Task DuplicateDetection_DuringATurn_IsDroppedAndCounted()
    {
        var coordinator = NewCoordinator(out var detector, out _, out _);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        detector.RaiseDetected(WakePhrase.HeyReva);   // arrives mid-turn

        // The state transition out of Armed happens synchronously inside the
        // event handler, before any await — otherwise this is a race and both
        // detections are accepted. v1's handler had no such guarantee.
        Assert.Equal(1, coordinator.DroppedDetectionCount);
        await coordinator.WaitForTurnAsync();
    }

    [Fact]
    public async Task Detection_TemporaryAudioIsDeletedAfterTheTurn()
    {
        var coordinator = NewCoordinator(out var detector, out _, out _);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.WaitForTurnAsync();

        Assert.Empty(coordinator.TemporaryFilesForTesting);
    }

    // --- Core disconnected ---

    [Fact]
    public async Task CoreDisconnected_DetectionSkipsChimeAndCapture_ThenReturnsToArmed()
    {
        // v1 left this state with no exit — one detection during a Core restart
        // stuck the UI on "STT Unavailable" until the app was restarted.
        var time = new ManualTimeProvider();
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var chime = new FakeChimePlayer();
        var client = new FakeCoreClient();   // any call throws
        var coordinator = NewCoordinator(client, chime, lifecycle, time, out var detector);
        await coordinator.EnableAsync(DefaultConfig());

        detector.RaiseDetected(WakePhrase.HeyReva);

        Assert.Equal(WakeWordUiState.SttUnavailable, coordinator.State);
        Assert.Equal(0, chime.PlayCallCount);
        Assert.Equal(0, client.TranscribeCallCount);

        lifecycle.State = CoreLifecycleState.Connected;
        lifecycle.RaiseStateChanged();
        time.UtcNow = time.UtcNow.AddSeconds(2);
        await coordinator.WaitForCooldownAsync();

        Assert.Equal(WakeWordUiState.Armed, coordinator.State);
    }

    // --- Hold-to-Talk hand-off ---

    [Fact]
    public async Task SuspendForHoldToTalk_StopsTheDetectorAndFullyReleasesTheMicrophone()
    {
        var coordinator = NewCoordinator(out var detector, out var arbiter, out _);
        await coordinator.EnableAsync(DefaultConfig());

        await coordinator.SuspendForHoldToTalkAsync();

        Assert.Equal(1, detector.StopCallCount);
        Assert.Null(arbiter.CurrentOwner);   // Hold-to-Talk can now acquire
        Assert.False(detector.IsRunning);
    }

    [Fact]
    public async Task ResumeAfterHoldToTalk_ReacquiresAndRestarts()
    {
        var coordinator = NewCoordinator(out var detector, out var arbiter, out _);
        await coordinator.EnableAsync(DefaultConfig());
        await coordinator.SuspendForHoldToTalkAsync();

        await coordinator.ResumeAfterHoldToTalkAsync();

        Assert.Equal(2, detector.StartCallCount);
        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
        Assert.Equal(WakeWordUiState.Armed, coordinator.State);
    }

    [Fact]
    public async Task ResumeAfterHoldToTalk_MicrophoneStillHeld_ReportsMicrophoneUnavailable_NotArmed()
    {
        // The v1 killer: ResumeAsync discarded the acquire result, so a failed
        // resume left the UI saying "Wake Word Armed" while the app was deaf.
        var arbiter = new MicrophoneArbiter(new FakeAudioSource());
        var coordinator = NewCoordinator(out var detector, arbiter);
        await coordinator.EnableAsync(DefaultConfig());
        await coordinator.SuspendForHoldToTalkAsync();
        await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);   // never released

        await coordinator.ResumeAfterHoldToTalkAsync();

        Assert.Equal(WakeWordUiState.MicrophoneUnavailable, coordinator.State);
        Assert.False(coordinator.IsArmed);
        Assert.False(detector.IsRunning);
    }

    [Fact]
    public async Task SuspendResume_WhileDisabled_IsANoOp()
    {
        var coordinator = NewCoordinator(out var detector, out _, out _);

        await coordinator.SuspendForHoldToTalkAsync();
        await coordinator.ResumeAfterHoldToTalkAsync();

        Assert.Equal(WakeWordUiState.Off, coordinator.State);
        Assert.Equal(0, detector.StartCallCount);
    }

    // --- Shutdown ---

    [Fact]
    public async Task DisposeAsync_StopsTheDetectorAndReleasesTheMicrophone()
    {
        var coordinator = NewCoordinator(out var detector, out var arbiter, out _);
        await coordinator.EnableAsync(DefaultConfig());

        await coordinator.DisposeAsync();

        Assert.Equal(1, detector.StopCallCount);
        Assert.Null(arbiter.CurrentOwner);
    }
}
```

`WaitForTurnAsync`/`WaitForCooldownAsync` are `internal` test seams (`[InternalsVisibleTo]`, per Task 0 Step 2.4) that await the coordinator's in-flight turn task — deterministic, unlike v1's `CompleteCaptureForTestingAsync`, which required the test to supply the WAV and therefore never exercised the coordinator's own capture-and-endpoint path. The capture itself comes from the fake lease.

- [ ] **Step 3: Run to verify they fail.**

- [ ] **Step 4: Implement**

The state machine:

- `EnableAsync`: `Off → Starting`; acquire a lease (null → `MicrophoneUnavailable`, stop); `detector.StartAsync(config, lease)` inside a `try` that catches `WakeWordConfigurationException` → `WakeWordError` **and disposes the lease** (v1 leaked it on this path); success → `Armed`.
- Detection handler: **synchronously** check `State == Armed` under a lock and flip to `Detected`, or `Interlocked.Increment(ref _droppedDetections)` and return. Only then queue the async turn.
- Turn: if Core is disconnected → `SttUnavailable`, no chime, no capture, fall through to cooldown. Otherwise start capture on the lease, play the chime concurrently, discard `ChimePlayer.CapturePrefixToDiscard` from the front, run the `Endpointer` per frame, stop on `SilenceReached`/`MaximumDurationReached`/wall-clock timeout, apply the 250ms floor to the post-discard audio, call `TranscribeSpeechAsync`, reject empty/whitespace transcripts, otherwise `_composerSink.AppendTranscription(text)`.
- `finally`: delete any temporary audio, `Cooldown`, then `Armed` after two seconds measured against the injected `TimeProvider`.
- `SuspendForHoldToTalkAsync`: `detector.StopAsync()` then dispose the lease. No-op when not armed.
- `ResumeAfterHoldToTalkAsync`: re-acquire; **null → `MicrophoneUnavailable`**; otherwise restart the detector and return to `Armed`.
- Every state write goes through `SetState`, which marshals to the captured `DispatcherQueue` when one exists and it doesn't already have thread access — Porcupine's loop is not the UI thread, and `PropertyChanged` from it throws `RPC_E_WRONG_THREAD`.
- Every transition logs `wakeword.state=<State>`; detections log `wakeword.detected phrase=<Phrase>`. Nothing else from the audio path is logged.

- [ ] **Step 5: Run to verify they pass. Step 6: Full suite. Step 7: Commit.**

```bash
git commit -m "feat(desktop): add WakeWordCoordinator state machine"
```

---

### Task 8: UI wiring

**Files:** `MainWindow.xaml`, `MainWindow.xaml.cs`, `App.xaml.cs`, `ViewModels/AssistantViewModel.cs`.

- [ ] **Step 1: Collapse the constructor explosion**

`AssistantViewModel` is at four optional dependencies and this slice needs the coordinator wired alongside it. Introduce a dependencies record before adding a fifth positional parameter:

```csharp
public sealed record AssistantViewModelDependencies(
    IRevaCoreClient CoreClient,
    IVoiceDevice? VoiceDevice = null,
    IRevaCoreLifecycle? Lifecycle = null,
    ICommandRouter? CommandRouter = null);
```

Keep the existing positional constructor as an overload that forwards, so no existing test changes.

- [ ] **Step 2: Resolve the construction cycle**

v1's Task 8 said to construct `WakeWordCoordinator` in `App.xaml.cs` "with the real `AssistantViewModel` (as its `IComposerSink`)" — but `AssistantViewModel` is constructed *inside* `MainWindow`'s constructor, so the coordinator cannot be built before the window it depends on. **Construct `AssistantViewModel` in `App.xaml.cs`**, pass it into both `MainWindow` and `WakeWordCoordinator`, and have `MainWindow` accept the already-built view models. One composition root, no cycle.

- [ ] **Step 3: Hold-to-Talk hand-off**

In `VoiceButton_PointerPressed`: `await WakeWord.SuspendForHoldToTalkAsync();` **before** `Assistant.StartVoiceInputAsync()`. Wrap the released/canceled/capture-lost handlers so `ResumeAfterHoldToTalkAsync()` runs in a `finally` regardless of outcome — the "a failed Hold-to-Talk turn must never leave wake word deaf" constraint. Because `WindowsVoiceDevice` now goes through the arbiter (Task 4), an ordering mistake here fails loudly (Hold-to-Talk can't get a lease) instead of silently double-capturing.

- [ ] **Step 4: Settings UI**

Master Wake Word toggle; per-phrase toggles and sensitivity for the three optional phrases; the persistent armed indicator required by the design's Privacy section, showing which phrases are live and readable without opening settings. A phrase with fewer than three syllables gets an inline warning — no such phrase ships today, and the warning is what stops one arriving quietly later.

- [ ] **Step 5: Build, full suite, commit.**

```bash
git commit -m "feat(desktop): wire wake word into the shell and composition root"
```

---

### Task 9: Calibration + physical acceptance

**Files:** possibly `Endpointer.cs` (threshold), `PorcupineWakeWordDetector.cs` (sensitivities).

- [ ] **Step 1: Full automated suite.** `dotnet test desktop/Reva.Desktop.sln` → PASS, 0 failures, before any hardware.

- [ ] **Step 2: Confirm the keyword assets and key are present.** Four `.ppn` files in `%LOCALAPPDATA%\REVA\wake-word\keywords\`, `REVA_PICOVOICE_ACCESS_KEY` set. Verify a missing file produces `Wake Word Error` naming the phrase, and that no error text anywhere contains a fragment of the key.

- [ ] **Step 3: Calibrate the RMS threshold against the real room.** With the app running, capture a few seconds of the room at rest and a few of normal speech; compute per-frame RMS for both. The threshold must sit clearly above the noise floor and clearly below speech. `Endpointer.DefaultRmsThreshold = 500` is a starting point, not a measurement — record the measured floor and the value chosen. A threshold below the noise floor means turns never end; above speech means turns end mid-sentence.

- [ ] **Step 4: Build Release and run it.**

- [ ] **Step 5: Recognition, per enabled phrase.** 20 deliberate activations, normal voice; ≥ 18/20; at ~1m and ~3m separately; activation within 500ms of the phrase ending. Tune per-phrase sensitivity if a phrase passes at 1m and collapses at 3m — and re-run Step 6 afterwards, because sensitivity trades directly against false accepts.

- [ ] **Step 6: Aggregate false-activation gate.** All enabled phrases armed, ≥ 1 hour of ordinary speech, music, video, and calls. ≤ 1 false activation for the hour, **for the set**. A second hour with only the high-risk phrases if any of 2-4 ship.

- [ ] **Step 7: Adversarial near-miss set.** Five utterances each from the design's table. Record every activation. Two to watch: **"daddy's not home"** (Porcupine matches the phrase, not the polarity) and bare **"wake up"** firing `reva-wake-up` — the latter would mean the phrase replacement bought nothing.

- [ ] **Step 8: Microphone hand-off.** With wake word armed: use Hold-to-Talk normally, confirm wake word resumes and still detects. Then force a Hold-to-Talk *failure* (unplug the mic mid-hold, or deny permission) and confirm wake word still resumes or reports `Microphone Unavailable` — **never "Wake Word Armed" while deaf.** This is the v1 defect made physical.

- [ ] **Step 9: Core restart.** With wake word armed, stop `reva_core`, say a wake phrase → `STT Unavailable`, no chime, no capture. Restart Core → within a cooldown, back to `Wake Word Armed` without restarting the app.

- [ ] **Step 10: The cross-slice safety check.** Open Notepad **with unsaved text**. Type `close Notepad` and wait for the confirmation prompt. Then say a wake phrase and speak the word "confirm". Press Send.

  **Notepad must not close.** The desktop log must show `command.state=ConfirmIgnored reason=transcribed_source`. Then type `confirm` and verify it does close. This is the single most important manual check across all three slices: it proves that an always-listening microphone cannot destroy work.

- [ ] **Step 11: Chime hygiene.** Confirm the chime is audible, is not startling, and **does not appear in the transcript** — say a phrase and then a short sentence, and check the composer contains only the sentence.

- [ ] **Step 12: Resource and shutdown hygiene.** CPU < 5% with the full enabled set armed. Close the app; confirm no microphone handle and no child process survive (PID/handle diff, per the Voice V1 precedent). Confirm no audio files remain after completed and aborted turns.

- [ ] **Step 13: Report.** Per-phrase activation rates at both distances; aggregate false-activation count; near-miss results with "daddy's not home" and "wake up" called out; the measured noise floor and chosen RMS threshold; hand-off results from Step 8; the Step 10 result verbatim; CPU; hygiene results; and explicit confirmation that no Assistant, TTS, or Windows action occurred before a manual Send.

- [ ] **Step 14: Commit any last-mile fixes.**

```bash
git status && git add -A && git commit -m "fix(desktop): address wake-word acceptance findings"
```

---

## Coverage table

| Required behavior (design doc) | Test / step | Task |
|---|---|---|
| Disabled by default; only HeyReva enabled | `Defaults_OnlyHeyRevaEnabledByDefault`, `InitialState_IsOff` | 2, 7 |
| No bare 2-syllable "wake up" phrase | `Defaults_NoBareTwoSyllableWakeUpPhrase` | 2 |
| Exact status strings | `WakeWordUiStateTests` (10 + coverage) | 2 |
| Enable starts the detector once | `EnableAsync_AcquiresTheMicrophone…` | 7 |
| Disable stops it and releases the mic | `DisableAsync_StopsTheDetector…` | 7 |
| Only enabled phrases are loaded | `Resolve_DisabledPhraseIsExcluded…` | 2 |
| Missing `.ppn` → error naming the phrase | `Resolve_MissingKeywordFile…`, `EnableAsync_DetectorConfigurationFails…`, Step 2 | 2, 7, 9 |
| Missing key → error, no key in the message | `EnableAsync_ErrorMessage_NeverContainsTheAccessKey`, Step 2 | 7, 9 |
| Sensitivity/path/phrase arrays stay in lockstep | `Resolve_ThreeParallelArrays…` | 2 |
| Index→phrase mapping correct | Step 5 (per-phrase activation) | 9 |
| No STT before detection | `FakeCoreClient` throws on any unexpected call; `EnableAsync_*` assert `TranscribeCallCount == 0` | 7 |
| Detection starts post-wake capture | `Detection_PopulatesComposer…` | 7 |
| Every phrase behaves identically | `Detection_EveryPhraseProducesIdenticalDownstreamBehavior` (4 cases) | 7 |
| Duplicate detection dropped and counted | `DuplicateDetection_DuringATurn…` | 7 |
| Silence stops capture | `EndpointerTests` (5 silence/hysteresis cases) | 3 |
| Maximum duration stops capture | `ProcessFrame_EightSecondMaximum…` | 3 |
| Silence timer resets, never accumulates | `ProcessFrame_SilenceTimerResetsAfterAPause` | 3 |
| Transcript populates the composer | `Detection_PopulatesComposer…` | 7 |
| Draft preserved (append, not overwrite) | `Detection_ExistingDraftIsPreserved…` | 7 |
| Empty transcript is a failure | `Detection_EmptyTranscript_IsAFailure…` | 7 |
| Transcript is not auto-sent | `client.CallCount == 0` in every turn test; Step 13 | 7, 9 |
| Command is not auto-executed | Step 10 | 9 |
| **Spoken "confirm" cannot close an app** | `AppendTranscription` marks Transcribed (Task 7 Step 1) + app-command routing's `RouteAsync_TranscribedConfirm…`; **Step 10** | 7, 9 |
| Hold-to-Talk suspends and resumes | `SuspendForHoldToTalk…`, `ResumeAfterHoldToTalk…`, Step 8 | 7, 9 |
| **Failed resume never reports "Armed"** | `ResumeAfterHoldToTalk_MicrophoneStillHeld…`, Step 8 | 7, 9 |
| Mic held elsewhere → safe state | `EnableAsync_MicrophoneAlreadyHeld…` | 7 |
| Core disconnect → STT Unavailable, and back | `CoreDisconnected_DetectionSkipsChime…`, Step 9 | 7, 9 |
| Only one component captures at a time | `MicrophoneArbiterTests` (8 cases, incl. concurrency) | 4 |
| A disposed lease cannot read frames | `DisposedLease_CannotStillReadFrames` | 4 |
| Cancellation releases mic resources | `DisposeAsync_StopsTheDetector…`, `DisposingALeaseTwice_IsSafe` | 4, 7 |
| App shutdown stops the detector | `DisposeAsync_…`, Step 12 | 7, 9 |
| No audio files remain after a turn | `Detection_TemporaryAudioIsDeleted…`, Step 12 | 7, 9 |
| Chime plays once, never via TTS | `Detection_…ChimesOnce…` (`SynthesizeCallCount == 0`) | 7 |
| Chime is not inside the recording | Step 11 | 9 |
| Recognition ≥18/20 at 1m and 3m | Step 5 | 9 |
| ≤1 false activation/hour for the set | Step 6 | 9 |
| Near-miss set produces no activations | Step 7 | 9 |
| CPU < 5% armed | Step 12 | 9 |

**Deliberately not unit-tested:** `PorcupineWakeWordDetector` and the arbiter's real capture graph (real OS/SDK dependencies — Steps 5-12 are their test), and the RMS threshold's real-world value (Step 3 measures it).
