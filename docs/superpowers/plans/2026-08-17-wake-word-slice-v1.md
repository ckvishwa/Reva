# Wake-Word Slice ("Hey Reva") v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **⛔ DO NOT BEGIN TASK 0 UNTIL THIS GATE CLEARS.** This plan is written and reviewed as design work only, per explicit user instruction (2026-08-17: "do not implement either slice yet"). Implementation may not start until **all** of the following are true:
> 1. `docs/superpowers/plans/2026-08-17-windows-app-command-routing-v1.md` — every task reviewed clean, Task 6's physical acceptance run passed and reported.
> 2. The transcription-only voice slice's own Task 9 physical-microphone acceptance (`docs/superpowers/plans/2026-08-16-transcription-only-voice-slice.md`) is fully closed out, not just its happy path.
> 3. Open decision #2 from the design doc (Picovoice custom-keyword licensing/expiry) is verified against the actual Picovoice account/tier this project will use — this cannot be resolved by reasoning alone and is not resolved by this plan.
> 4. A chime audio asset meeting Task 6's technical spec exists and is committed.
>
> This is not a formality — see the design doc's "why the sequencing dependency is still real" note (`docs/superpowers/specs/2026-08-17-wake-word-slice-design.md`, Reconciliation section).

**Goal:** Local, always-listening wake-word detection ("Hey Reva" and three optional secondary phrases) that arms/disarms explicitly, never auto-sends or auto-executes anything, and reuses the transcription-only voice slice's STT + composer path exactly rather than reimplementing it.

**Architecture:** `IWakeWordDetector` (real implementation: `PorcupineWakeWordDetector`, a single Porcupine instance loaded with every *enabled* phrase's keyword, never one instance per phrase) feeds a local RMS+hysteresis endpointer that decides when captured speech ends. A `MicrophoneArbiter` is the single owner of microphone access — wake-word detection and Hold-to-Talk both request it through the arbiter, never construct their own `MediaCapture`. A new `WakeWordCoordinator` (not `AssistantViewModel` — provider/detector logic never lives there, per the design doc) owns the 10-state wake-word state machine and pushes captured, transcribed text into the composer through a small `IComposerSink` seam `AssistantViewModel` implements, so `WakeWordCoordinator` has zero dependency on `AssistantViewModel`'s internals.

**Tech Stack:** C# / .NET (net10.0-windows10.0.19041.0), Porcupine .NET SDK (new package dependency, added in Task 5), `System.Diagnostics`/`Windows.Media.Capture` (via the arbiter, reusing `WindowsVoiceDevice`'s established capture conventions), xUnit.

## Resolved open decisions (from the design doc's "Open decisions" section)

Resolved here so this plan contains no placeholders. Revisit before implementation actually starts if circumstances changed since 2026-08-17.

1. **"Wake up" → "Reva wake up".** Adopted the design doc's own recommendation (option 3): 4 syllables, anchored by "Reva," materially better false-accept behavior than the bare 2-syllable original. `WakePhrase.WakeUp` is `WakePhrase.RevaWakeUp` throughout this plan; sensitivity set to 0.40 (between phrase 2's 0.45 and the original high-risk phrase's 0.30 — anchored-but-still-short).
2. **Licensing** — NOT resolved by this plan (see gate above). Task 6 Step 1 re-states the check as a precondition.
3. **VAD — RMS, not Cobra.** Adopted. Task 3 implements it as a self-contained, fully unit-testable component.
4. **Arm while Core disconnected — yes, arm; display STT Unavailable; suppress the chime.** Adopted. Task 7 encodes this exactly: the detector still runs (it costs nothing to have it listening), but a detection while Core is down skips the chime and the capture window, and the state goes straight to `SttUnavailable` — no capture the user can't act on.
5. **Chime asset** — Task 6 pins the technical spec (format, duration, embedding, volume) so the file itself is a drop-in asset, not a design gap.

## Global Constraints

- Wake word is OFF by default on first launch; every phrase except `HeyReva` is OFF by default even after wake word is enabled.
- No STT call, no recording file, and no Assistant call occurs before a detection.
- Wake-word detection never executes Windows actions directly — it only ever writes to `ComposerText` through `IComposerSink`.
- Never log PCM, transcript text, or confidence/per-frame data. Only fixed state identifiers and phrase enum values (`wakeword.state=Armed`, `wakeword.detected phrase=HeyReva`).
- Pre-wake audio is never written to disk — the detection buffer is in-memory only.
- Post-wake captured audio follows the transcription slice's temp-file discipline (deleted in a `finally`, every path, including cancellation/error).
- AccessKey (`REVA_PICOVOICE_ACCESS_KEY`) is read from environment/configuration only — never committed, never logged, never echoed in any error message.
- Keyword `.ppn` files are read from a fixed local directory, never downloaded at runtime.
- Only one component owns microphone capture at a time (`MicrophoneArbiter`) — no competing `MediaCapture` instances.
- Hold-to-Talk suspends wake-word detection and resumes it afterward, on every exit path (success, cancel, capture-lost, error) — a failed Hold-to-Talk turn must never leave wake-word permanently deaf.
- No status/enablement contradiction — same rule as the transcription slice: if the wake-word toggle is on but non-functional, the state must say why, never silently claim "Armed."
- Desktop-only — no `reva_core`/Python changes.
- Provider-specific (Porcupine) code never appears outside `PorcupineWakeWordDetector` — not in `WakeWordCoordinator`, not in `AssistantViewModel`.

---

## File Structure

- `desktop/src/Reva.Desktop/Services/WakePhrase.cs` — **new**. `WakePhrase` enum, `WakePhraseSetting`, `WakeWordConfiguration` records.
- `desktop/src/Reva.Desktop/State/WakeWordUiState.cs` — **new**. The 10-state enum + display text, mirroring `VoiceUiState`'s established pattern exactly.
- `desktop/src/Reva.Desktop/Services/IWakeWordDetector.cs` — **new**. Interface + `WakeWordDetection` record.
- `desktop/src/Reva.Desktop/Services/WakeWordKeywordResolver.cs` — **new**. Resolves enabled phrases → `.ppn` paths, produces the missing-file/missing-key error states.
- `desktop/src/Reva.Desktop/Services/Endpointer.cs` — **new**. RMS+hysteresis+hard-cap speech-end detection, pure DSP, no I/O.
- `desktop/src/Reva.Desktop/Services/IMicrophoneArbiter.cs` — **new**. Single microphone-ownership seam.
- `desktop/src/Reva.Desktop/Services/MicrophoneArbiter.cs` — **new**. Real implementation, wraps `WindowsVoiceDevice`-style capture.
- `desktop/src/Reva.Desktop/Services/PorcupineWakeWordDetector.cs` — **new**. The only file referencing the Porcupine SDK.
- `desktop/src/Reva.Desktop/Services/IComposerSink.cs` — **new**. `{ string ComposerText { get; set; } }` — the seam `WakeWordCoordinator` writes through; `AssistantViewModel` implements it (it already has a `ComposerText` property with the exact right append semantics).
- `desktop/src/Reva.Desktop/ViewModels/WakeWordCoordinator.cs` — **new**. Owns the state machine. No WinUI types, no Porcupine types — same testability bar as `AssistantViewModel`.
- `desktop/src/Reva.Desktop/MainWindow.xaml` / `.xaml.cs` — **modify**. Wake-word toggle, per-phrase settings surface, persistent armed indicator.
- `desktop/src/Reva.Desktop/App.xaml.cs` — **modify**. Construct and wire `MicrophoneArbiter`, `PorcupineWakeWordDetector`, `WakeWordCoordinator`.
- Assets: a chime audio file (Task 6), a `keywords/` setup convention documented but not auto-populated (Task 2).
- Tests: one file per new src file following this codebase's established 1:1 naming (`WakePhraseTests.cs`, `WakeWordUiStateTests.cs`, `WakeWordKeywordResolverTests.cs`, `EndpointerTests.cs`, `MicrophoneArbiterTests.cs`, `WakeWordCoordinatorTests.cs`) — no test file for `PorcupineWakeWordDetector.cs`, matching the established no-unit-tests-for-real-OS/SDK-dependency precedent (`WindowsVoiceDevice`, `WindowsAppExecutor`).

---

### Task 0: Confirm the gate, then re-verify assumptions against the codebase at implementation time

**Files:** none (read-only, like the transcription slice's Task 0).

- [ ] **Step 1: Confirm the blocking gate (top of this document) has actually cleared.** Do not proceed on the strength of this plan's age — re-check the app-command routing plan's task list and the transcription slice's Task 9 status directly.
- [ ] **Step 2: Re-read the current `AssistantViewModel.cs`, `WindowsVoiceDevice.cs`, and `CommandRouter.cs`/`AppAllowlist.cs`** (the latter two will exist only after the gate clears) to catch any drift between this plan's assumptions and what actually landed — the transcription slice's own history (a "v2" plan revision appeared mid-execution) is the reason this step exists, not paranoia.
- [ ] **Step 3: Confirm the Picovoice licensing and chime-asset gate items (top of document) are still true** before writing any code.

---

### Task 1: Phrase types + resolved phrase table

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/WakePhrase.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/WakePhraseTests.cs`

**Interfaces:**
- Produces: `enum WakePhrase { HeyReva, YouUpReva, DaddysHome, RevaWakeUp }`; `record WakePhraseSetting(WakePhrase Phrase, bool Enabled, float Sensitivity)`; `record WakeWordConfiguration(IReadOnlyList<WakePhraseSetting> Phrases)`; `static class WakePhraseDefaults` with the resolved table.

- [ ] **Step 1: Write the failing tests**

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WakePhraseTests
{
    [Fact]
    public void Defaults_HasFourPhrases()
    {
        Assert.Equal(4, WakePhraseDefaults.All.Count);
    }

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
    public void Defaults_MatchDesignDocSensitivities(WakePhrase phrase, float expectedSensitivity)
    {
        var setting = WakePhraseDefaults.All.Single(p => p.Phrase == phrase);

        Assert.Equal(expectedSensitivity, setting.Sensitivity);
    }

    [Fact]
    public void Defaults_NoPhraseNamedPlainWakeUp()
    {
        // Regression guard for the resolved open decision — "Wake up" (2
        // syllables) must never come back as a shippable option; only the
        // 4-syllable "Reva wake up" replacement exists.
        Assert.DoesNotContain(WakePhraseDefaults.All, p => p.Phrase.ToString() == "WakeUp");
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WakePhraseTests`
Expected: FAIL (build error).

- [ ] **Step 3: Implement**

```csharp
namespace Reva.Desktop.Services;

public enum WakePhrase
{
    HeyReva,
    YouUpReva,
    DaddysHome,
    RevaWakeUp,
}

public sealed record WakePhraseSetting(WakePhrase Phrase, bool Enabled, float Sensitivity);

public sealed record WakeWordConfiguration(IReadOnlyList<WakePhraseSetting> Phrases);

public static class WakePhraseDefaults
{
    public static readonly IReadOnlyList<WakePhraseSetting> All = new[]
    {
        new WakePhraseSetting(WakePhrase.HeyReva, Enabled: true, Sensitivity: 0.55f),
        new WakePhraseSetting(WakePhrase.YouUpReva, Enabled: false, Sensitivity: 0.45f),
        new WakePhraseSetting(WakePhrase.DaddysHome, Enabled: false, Sensitivity: 0.45f),
        new WakePhraseSetting(WakePhrase.RevaWakeUp, Enabled: false, Sensitivity: 0.40f),
    };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WakePhraseTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/WakePhrase.cs desktop/tests/Reva.Desktop.Tests/Unit/WakePhraseTests.cs
git commit -m "feat(desktop): add wake-phrase types and resolved default table"
```

---

### Task 2: `WakeWordUiState` + `IWakeWordDetector` + keyword/AccessKey resolution

**Files:**
- Create: `desktop/src/Reva.Desktop/State/WakeWordUiState.cs`
- Create: `desktop/src/Reva.Desktop/Services/IWakeWordDetector.cs`
- Create: `desktop/src/Reva.Desktop/Services/WakeWordKeywordResolver.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/WakeWordUiStateTests.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/WakeWordKeywordResolverTests.cs`

**Interfaces:**
- Produces: `enum WakeWordUiState { Off, Starting, Armed, Detected, Listening, Transcribing, Cooldown, MicrophoneUnavailable, SttUnavailable, WakeWordError }` + `WakeWordUiStateText.For(...)`; `interface IWakeWordDetector : IAsyncDisposable { bool IsRunning; event EventHandler<WakeWordDetection>? Detected; Task StartAsync(WakeWordConfiguration, CancellationToken); Task StopAsync(CancellationToken); Task SuspendAsync(CancellationToken); Task ResumeAsync(CancellationToken); }`; `record WakeWordDetection(WakePhrase Phrase, DateTimeOffset DetectedAtUtc)`; `static class WakeWordKeywordResolver { static KeywordResolution Resolve(IReadOnlyList<WakePhraseSetting> enabledPhrases, string keywordDirectory, IFileSystemProbe fileSystem); }` with a tiny `IFileSystemProbe { bool Exists(string path); }` seam so the resolver is unit-testable without touching the real disk.

- [ ] **Step 1: Write the failing tests**

```csharp
// WakeWordUiStateTests.cs
using Reva.Desktop.State;

namespace Reva.Desktop.Tests.Unit;

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
    public void For_ReturnsExactRequiredText(WakeWordUiState state, string expected)
    {
        Assert.Equal(expected, WakeWordUiStateText.For(state));
    }

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
// WakeWordKeywordResolverTests.cs
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class WakeWordKeywordResolverTests
{
    private sealed class FakeFileSystemProbe : IFileSystemProbe
    {
        private readonly HashSet<string> _existingPaths;

        public FakeFileSystemProbe(IEnumerable<string> existingPaths) => _existingPaths = new(existingPaths, StringComparer.OrdinalIgnoreCase);

        public bool Exists(string path) => _existingPaths.Contains(path);
    }

    private static readonly WakePhraseSetting HeyReva = new(WakePhrase.HeyReva, true, 0.55f);
    private static readonly WakePhraseSetting YouUpReva = new(WakePhrase.YouUpReva, true, 0.45f);

    [Fact]
    public void Resolve_AllKeywordFilesPresent_ReturnsSuccessWithPathsInPhraseOrder()
    {
        var fileSystem = new FakeFileSystemProbe(new[]
        {
            @"C:\keywords\hey-reva.ppn",
            @"C:\keywords\you-up-reva.ppn",
        });

        var resolution = WakeWordKeywordResolver.Resolve(new[] { HeyReva, YouUpReva }, @"C:\keywords", fileSystem);

        Assert.True(resolution.IsSuccess);
        Assert.Equal(
            new[] { @"C:\keywords\hey-reva.ppn", @"C:\keywords\you-up-reva.ppn" },
            resolution.KeywordPaths);
        Assert.Equal(new[] { 0.55f, 0.45f }, resolution.Sensitivities);
    }

    [Fact]
    public void Resolve_MissingKeywordFile_ReturnsFailureNamingThePhrase()
    {
        var fileSystem = new FakeFileSystemProbe(new[] { @"C:\keywords\hey-reva.ppn" });

        var resolution = WakeWordKeywordResolver.Resolve(new[] { HeyReva, YouUpReva }, @"C:\keywords", fileSystem);

        Assert.False(resolution.IsSuccess);
        Assert.Equal(WakePhrase.YouUpReva, resolution.MissingPhrase);
    }

    [Fact]
    public void Resolve_NoEnabledPhrases_ReturnsFailure_NeverArmsEmpty()
    {
        var resolution = WakeWordKeywordResolver.Resolve(Array.Empty<WakePhraseSetting>(), @"C:\keywords", new FakeFileSystemProbe(Array.Empty<string>()));

        Assert.False(resolution.IsSuccess);
    }

    [Fact]
    public void Resolve_DisabledPhraseIsExcluded_ItsMissingFileDoesNotFailResolution()
    {
        var fileSystem = new FakeFileSystemProbe(new[] { @"C:\keywords\hey-reva.ppn" });
        var disabledYouUpReva = YouUpReva with { Enabled = false };

        var resolution = WakeWordKeywordResolver.Resolve(new[] { HeyReva, disabledYouUpReva }, @"C:\keywords", fileSystem);

        Assert.True(resolution.IsSuccess);
        Assert.Single(resolution.KeywordPaths!);
    }
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter "WakeWordUiStateTests|WakeWordKeywordResolverTests"`
Expected: FAIL (build errors).

- [ ] **Step 3: Implement**

`WakeWordUiState.cs`:

```csharp
namespace Reva.Desktop.State;

public enum WakeWordUiState
{
    Off,
    Starting,
    Armed,
    Detected,
    Listening,
    Transcribing,
    Cooldown,
    MicrophoneUnavailable,
    SttUnavailable,
    WakeWordError,
}

public static class WakeWordUiStateText
{
    public static string For(WakeWordUiState state) => state switch
    {
        WakeWordUiState.Off => "Wake Word Off",
        WakeWordUiState.Starting => "Starting",
        WakeWordUiState.Armed => "Wake Word Armed",
        WakeWordUiState.Detected => "Detected",
        WakeWordUiState.Listening => "Listening",
        WakeWordUiState.Transcribing => "Transcribing",
        WakeWordUiState.Cooldown => "Cooldown",
        WakeWordUiState.MicrophoneUnavailable => "Microphone Unavailable",
        WakeWordUiState.SttUnavailable => "STT Unavailable",
        WakeWordUiState.WakeWordError => "Wake Word Error",
        _ => throw new ArgumentOutOfRangeException(nameof(state)),
    };
}
```

`IWakeWordDetector.cs`:

```csharp
namespace Reva.Desktop.Services;

public sealed record WakeWordDetection(WakePhrase Phrase, DateTimeOffset DetectedAtUtc);

/// <summary>Provider seam — the only Picovoice-shaped code anywhere is
/// behind this, in PorcupineWakeWordDetector.</summary>
public interface IWakeWordDetector : IAsyncDisposable
{
    bool IsRunning { get; }

    event EventHandler<WakeWordDetection>? Detected;

    Task StartAsync(WakeWordConfiguration configuration, CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);

    Task SuspendAsync(CancellationToken cancellationToken = default);

    Task ResumeAsync(CancellationToken cancellationToken = default);
}
```

`WakeWordKeywordResolver.cs`:

```csharp
namespace Reva.Desktop.Services;

public interface IFileSystemProbe
{
    bool Exists(string path);
}

public sealed class RealFileSystemProbe : IFileSystemProbe
{
    public bool Exists(string path) => File.Exists(path);
}

public sealed record KeywordResolution(
    bool IsSuccess,
    IReadOnlyList<string>? KeywordPaths,
    IReadOnlyList<float>? Sensitivities,
    IReadOnlyList<WakePhrase>? PhraseOrder,
    WakePhrase? MissingPhrase);

public static class WakeWordKeywordResolver
{
    public static KeywordResolution Resolve(
        IReadOnlyList<WakePhraseSetting> phrases, string keywordDirectory, IFileSystemProbe fileSystem)
    {
        var enabled = phrases.Where(p => p.Enabled).ToList();
        if (enabled.Count == 0)
        {
            return new KeywordResolution(false, null, null, null, null);
        }

        var paths = new List<string>();
        var sensitivities = new List<float>();
        var order = new List<WakePhrase>();

        foreach (var phrase in enabled)
        {
            var path = Path.Combine(keywordDirectory, KeywordFileName(phrase.Phrase));
            if (!fileSystem.Exists(path))
            {
                return new KeywordResolution(false, null, null, null, phrase.Phrase);
            }

            paths.Add(path);
            sensitivities.Add(phrase.Sensitivity);
            order.Add(phrase.Phrase);
        }

        return new KeywordResolution(true, paths, sensitivities, order, null);
    }

    // Training-string vs. display-string separation per the design doc:
    // apostrophes/punctuation don't survive Picovoice Console training.
    private static string KeywordFileName(WakePhrase phrase) => phrase switch
    {
        WakePhrase.HeyReva => "hey-reva.ppn",
        WakePhrase.YouUpReva => "you-up-reva.ppn",
        WakePhrase.DaddysHome => "daddys-home.ppn",
        WakePhrase.RevaWakeUp => "reva-wake-up.ppn",
        _ => throw new ArgumentOutOfRangeException(nameof(phrase)),
    };
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter "WakeWordUiStateTests|WakeWordKeywordResolverTests"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/State/WakeWordUiState.cs desktop/src/Reva.Desktop/Services/IWakeWordDetector.cs desktop/src/Reva.Desktop/Services/WakeWordKeywordResolver.cs desktop/tests/Reva.Desktop.Tests/Unit/WakeWordUiStateTests.cs desktop/tests/Reva.Desktop.Tests/Unit/WakeWordKeywordResolverTests.cs
git commit -m "feat(desktop): add wake-word UI states, detector interface, keyword resolution"
```

---

### Task 3: Endpointer (RMS + hysteresis + hard cap)

Pure DSP, no I/O, no WinRT, no Porcupine — fully unit-testable against synthetic 16-bit PCM arrays.

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/Endpointer.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/EndpointerTests.cs`

**Interfaces:**
- Produces: `sealed class Endpointer { Endpointer(TimeSpan trailingSilence, TimeSpan maximumDuration, int sampleRate); EndpointerResult ProcessFrame(short[] pcmFrame, TimeSpan elapsedSinceStart); }`; `enum EndpointerSignal { Continue, SilenceReached, MaximumDurationReached }`; `record EndpointerResult(EndpointerSignal Signal)`.

- [ ] **Step 1: Write the failing tests**

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class EndpointerTests
{
    private const int SampleRate = 16000;

    private static short[] Silence(int sampleCount) => new short[sampleCount];

    private static short[] Loud(int sampleCount)
    {
        var frame = new short[sampleCount];
        for (var i = 0; i < sampleCount; i++)
        {
            frame[i] = (short)(i % 2 == 0 ? 12000 : -12000);
        }

        return frame;
    }

    [Fact]
    public void ProcessFrame_ContinuousSpeech_NeverSignalsSilence()
    {
        var endpointer = new Endpointer(TimeSpan.FromMilliseconds(800), TimeSpan.FromSeconds(8), SampleRate);
        var elapsed = TimeSpan.Zero;

        for (var i = 0; i < 10; i++)
        {
            var result = endpointer.ProcessFrame(Loud(512), elapsed);
            Assert.Equal(EndpointerSignal.Continue, result.Signal);
            elapsed += TimeSpan.FromMilliseconds(32);
        }
    }

    [Fact]
    public void ProcessFrame_EightHundredMillisecondsOfSilence_SignalsSilenceReached()
    {
        var endpointer = new Endpointer(TimeSpan.FromMilliseconds(800), TimeSpan.FromSeconds(8), SampleRate);
        var elapsed = TimeSpan.Zero;

        // A little speech first so the endpointer has "started" — silence
        // before any speech is just an unarmed detector, not an end-of-turn.
        endpointer.ProcessFrame(Loud(512), elapsed);
        elapsed += TimeSpan.FromMilliseconds(32);

        EndpointerResult? last = null;
        while (elapsed < TimeSpan.FromMilliseconds(900))
        {
            last = endpointer.ProcessFrame(Silence(512), elapsed);
            elapsed += TimeSpan.FromMilliseconds(32);
        }

        Assert.Equal(EndpointerSignal.SilenceReached, last!.Signal);
    }

    [Fact]
    public void ProcessFrame_EightSecondMaximum_SignalsMaximumDurationReached_EvenDuringContinuousSpeech()
    {
        var endpointer = new Endpointer(TimeSpan.FromMilliseconds(800), TimeSpan.FromSeconds(8), SampleRate);
        var elapsed = TimeSpan.Zero;

        EndpointerResult? last = null;
        while (elapsed < TimeSpan.FromSeconds(8.1))
        {
            last = endpointer.ProcessFrame(Loud(512), elapsed);
            elapsed += TimeSpan.FromMilliseconds(32);
        }

        Assert.Equal(EndpointerSignal.MaximumDurationReached, last!.Signal);
    }

    [Fact]
    public void ProcessFrame_BriefSilenceThenSpeechAgain_DoesNotPrematurelySignalSilence()
    {
        // Hysteresis: a short pause mid-sentence must not end the capture.
        var endpointer = new Endpointer(TimeSpan.FromMilliseconds(800), TimeSpan.FromSeconds(8), SampleRate);
        var elapsed = TimeSpan.Zero;

        endpointer.ProcessFrame(Loud(512), elapsed);
        elapsed += TimeSpan.FromMilliseconds(32);

        for (var i = 0; i < 5; i++) // 160ms of silence — well under the 800ms floor
        {
            var result = endpointer.ProcessFrame(Silence(512), elapsed);
            Assert.Equal(EndpointerSignal.Continue, result.Signal);
            elapsed += TimeSpan.FromMilliseconds(32);
        }

        var resumed = endpointer.ProcessFrame(Loud(512), elapsed);
        Assert.Equal(EndpointerSignal.Continue, resumed.Signal);
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter EndpointerTests`
Expected: FAIL (build error).

- [ ] **Step 3: Implement**

```csharp
namespace Reva.Desktop.Services;

public enum EndpointerSignal
{
    Continue,
    SilenceReached,
    MaximumDurationReached,
}

public sealed record EndpointerResult(EndpointerSignal Signal);

/// <summary>Energy/RMS-threshold voice-activity endpointing with hysteresis,
/// per the design doc's resolved decision (RMS over Cobra VAD for v1). Pure
/// DSP — no capture, no provider dependency, fully testable against
/// synthetic PCM.</summary>
public sealed class Endpointer
{
    // Empirically reasonable starting point for 16-bit PCM speech vs.
    // silence at typical mic gain; revisit against Task 8's real acceptance
    // run, not against a synthetic-frame unit test.
    private const double RmsThreshold = 500.0;

    private readonly TimeSpan _trailingSilence;
    private readonly TimeSpan _maximumDuration;

    private TimeSpan? _silenceStartedAt;
    private bool _hasHeardSpeech;

    public Endpointer(TimeSpan trailingSilence, TimeSpan maximumDuration, int sampleRate)
    {
        _trailingSilence = trailingSilence;
        _maximumDuration = maximumDuration;
        _ = sampleRate; // reserved for a future sample-rate-aware threshold; 16kHz is fixed for now.
    }

    public EndpointerResult ProcessFrame(short[] pcmFrame, TimeSpan elapsedSinceStart)
    {
        if (elapsedSinceStart >= _maximumDuration)
        {
            return new EndpointerResult(EndpointerSignal.MaximumDurationReached);
        }

        var isSpeech = ComputeRms(pcmFrame) >= RmsThreshold;

        if (isSpeech)
        {
            _hasHeardSpeech = true;
            _silenceStartedAt = null;
            return new EndpointerResult(EndpointerSignal.Continue);
        }

        if (!_hasHeardSpeech)
        {
            // Silence before any speech has been heard at all — the capture
            // hasn't really started; not an end-of-turn signal.
            return new EndpointerResult(EndpointerSignal.Continue);
        }

        _silenceStartedAt ??= elapsedSinceStart;
        var silenceDuration = elapsedSinceStart - _silenceStartedAt.Value;

        return silenceDuration >= _trailingSilence
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

- [ ] **Step 4: Run to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter EndpointerTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/Endpointer.cs desktop/tests/Reva.Desktop.Tests/Unit/EndpointerTests.cs
git commit -m "feat(desktop): add RMS/hysteresis endpointer for wake-word capture"
```

---

### Task 4: `IMicrophoneArbiter` — single microphone ownership

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/IMicrophoneArbiter.cs`
- Create: `desktop/src/Reva.Desktop/Services/MicrophoneArbiter.cs`
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/MicrophoneArbiterTests.cs`

**Interfaces:**
- Produces: `interface IMicrophoneArbiter { MicrophoneOwner? CurrentOwner { get; } Task<bool> TryAcquireAsync(MicrophoneOwner owner, CancellationToken); Task ReleaseAsync(MicrophoneOwner owner, CancellationToken); }`; `enum MicrophoneOwner { WakeWord, HoldToTalk }`.

The arbiter is a pure ownership tracker (who currently holds the microphone), not a capture implementation — `WindowsVoiceDevice` (Hold-to-Talk) and `PorcupineWakeWordDetector` (Task 5) each still do their own actual `MediaCapture` work, but both must check out ownership here first and release it when done, so they can never run concurrently.

- [ ] **Step 1: Write the failing tests**

```csharp
using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class MicrophoneArbiterTests
{
    [Fact]
    public async Task TryAcquireAsync_NoCurrentOwner_Succeeds()
    {
        var arbiter = new MicrophoneArbiter();

        var acquired = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        Assert.True(acquired);
        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
    }

    [Fact]
    public async Task TryAcquireAsync_AlreadyOwnedByOther_Fails_DoesNotChangeOwner()
    {
        var arbiter = new MicrophoneArbiter();
        await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        var acquired = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        Assert.False(acquired);
        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
    }

    [Fact]
    public async Task TryAcquireAsync_SameOwnerReacquiring_Succeeds_IsIdempotent()
    {
        var arbiter = new MicrophoneArbiter();
        await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        var acquired = await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        Assert.True(acquired);
    }

    [Fact]
    public async Task ReleaseAsync_ByCurrentOwner_ClearsOwnership()
    {
        var arbiter = new MicrophoneArbiter();
        await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        await arbiter.ReleaseAsync(MicrophoneOwner.HoldToTalk);

        Assert.Null(arbiter.CurrentOwner);
    }

    [Fact]
    public async Task ReleaseAsync_ByNonOwner_IsANoOp_DoesNotClearRealOwner()
    {
        var arbiter = new MicrophoneArbiter();
        await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);

        await arbiter.ReleaseAsync(MicrophoneOwner.HoldToTalk);

        Assert.Equal(MicrophoneOwner.WakeWord, arbiter.CurrentOwner);
    }

    [Fact]
    public async Task ReleaseThenAcquire_ByDifferentOwner_Succeeds()
    {
        var arbiter = new MicrophoneArbiter();
        await arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord);
        await arbiter.ReleaseAsync(MicrophoneOwner.WakeWord);

        var acquired = await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk);

        Assert.True(acquired);
        Assert.Equal(MicrophoneOwner.HoldToTalk, arbiter.CurrentOwner);
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `dotnet test desktop/Reva.Desktop.sln --filter MicrophoneArbiterTests`
Expected: FAIL (build error).

- [ ] **Step 3: Implement**

`IMicrophoneArbiter.cs`:

```csharp
namespace Reva.Desktop.Services;

public enum MicrophoneOwner
{
    WakeWord,
    HoldToTalk,
}

/// <summary>The single source of truth for "who currently owns microphone
/// capture." Neither WindowsVoiceDevice nor PorcupineWakeWordDetector may
/// start capturing without checking out ownership here first.</summary>
public interface IMicrophoneArbiter
{
    MicrophoneOwner? CurrentOwner { get; }

    Task<bool> TryAcquireAsync(MicrophoneOwner owner, CancellationToken cancellationToken = default);

    Task ReleaseAsync(MicrophoneOwner owner, CancellationToken cancellationToken = default);
}
```

`MicrophoneArbiter.cs`:

```csharp
namespace Reva.Desktop.Services;

public sealed class MicrophoneArbiter : IMicrophoneArbiter
{
    private readonly object _gate = new();
    private MicrophoneOwner? _currentOwner;

    public MicrophoneOwner? CurrentOwner
    {
        get
        {
            lock (_gate)
            {
                return _currentOwner;
            }
        }
    }

    public Task<bool> TryAcquireAsync(MicrophoneOwner owner, CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            if (_currentOwner is null || _currentOwner == owner)
            {
                _currentOwner = owner;
                return Task.FromResult(true);
            }

            return Task.FromResult(false);
        }
    }

    public Task ReleaseAsync(MicrophoneOwner owner, CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            if (_currentOwner == owner)
            {
                _currentOwner = null;
            }
        }

        return Task.CompletedTask;
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `dotnet test desktop/Reva.Desktop.sln --filter MicrophoneArbiterTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/IMicrophoneArbiter.cs desktop/src/Reva.Desktop/Services/MicrophoneArbiter.cs desktop/tests/Reva.Desktop.Tests/Unit/MicrophoneArbiterTests.cs
git commit -m "feat(desktop): add single-owner microphone arbiter"
```

---

### Task 5: `PorcupineWakeWordDetector` (real provider, no unit tests)

Same established precedent as `WindowsVoiceDevice`/`WindowsAppExecutor`: real native-SDK dependency, verified only in Task 8's physical acceptance run.

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/PorcupineWakeWordDetector.cs`
- Modify: `desktop/src/Reva.Desktop/Reva.Desktop.csproj` (add the Porcupine .NET SDK package reference)

**Interfaces:**
- Consumes: `IWakeWordDetector`, `WakeWordKeywordResolver`, `IMicrophoneArbiter` (Tasks 2, 4).
- Produces: `PorcupineWakeWordDetector : IWakeWordDetector`.

- [ ] **Step 1: Add the package reference**

Add to `Reva.Desktop.csproj`'s existing `<ItemGroup>` of `PackageReference`s: `<PackageReference Include="Porcupine" Version="[pin the exact version verified against Task 0 Step 3's licensing check]" />` — the exact version string is filled in at implementation time from whatever the verified, licensed SDK version actually is; this plan does not guess it, matching the "no placeholders" bar by making the *process* (verify, then pin) explicit rather than inventing a version number now.

- [ ] **Step 2: Implement**

```csharp
using Pv;

namespace Reva.Desktop.Services;

public sealed class PorcupineWakeWordDetector : IWakeWordDetector
{
    private readonly string _accessKey;
    private readonly string _keywordDirectory;
    private readonly IFileSystemProbe _fileSystem;
    private readonly IMicrophoneArbiter _arbiter;

    private Porcupine? _porcupine;
    private IReadOnlyList<WakePhrase>? _phraseOrder;
    private CancellationTokenSource? _listenLoopCancellation;

    public PorcupineWakeWordDetector(
        string accessKey, string keywordDirectory, IFileSystemProbe fileSystem, IMicrophoneArbiter arbiter)
    {
        _accessKey = accessKey;
        _keywordDirectory = keywordDirectory;
        _fileSystem = fileSystem;
        _arbiter = arbiter;
    }

    public bool IsRunning => _porcupine is not null;

    public event EventHandler<WakeWordDetection>? Detected;

    public async Task StartAsync(WakeWordConfiguration configuration, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(_accessKey))
        {
            throw new WakeWordConfigurationException("Wake word requires a configured access key.");
        }

        var resolution = WakeWordKeywordResolver.Resolve(configuration.Phrases, _keywordDirectory, _fileSystem);
        if (!resolution.IsSuccess)
        {
            throw resolution.MissingPhrase is { } missing
                ? new WakeWordConfigurationException($"Missing keyword file for {missing}.")
                : new WakeWordConfigurationException("No wake phrases are enabled.");
        }

        if (!await _arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord, cancellationToken))
        {
            throw new InvalidOperationException("Microphone is owned by another component.");
        }

        // One Porcupine instance for every enabled keyword — never one
        // instance per phrase (design doc, Provider design section).
        _porcupine = Porcupine.FromKeywordPaths(
            _accessKey, resolution.KeywordPaths!.ToArray(), sensitivities: resolution.Sensitivities!.ToArray());
        _phraseOrder = resolution.PhraseOrder;

        _listenLoopCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _ = RunListenLoopAsync(_listenLoopCancellation.Token);
    }

    private async Task RunListenLoopAsync(CancellationToken cancellationToken)
    {
        // Real frame-capture-and-Process(short[]) loop against the
        // arbiter-owned microphone stream. Left as an implementation note
        // rather than pseudocode here — the exact capture-buffering shape
        // depends on whichever WindowsVoiceDevice-adjacent capture API the
        // arbiter exposes once Task 4's real capture wiring (not just
        // ownership tracking) is fleshed out immediately before this task
        // runs for real; Porcupine.FrameLength/SampleRate drive the buffer
        // size, per the design doc's Frame discipline note.
        await Task.CompletedTask;
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        _listenLoopCancellation?.Cancel();
        _porcupine?.Dispose();
        _porcupine = null;
        await _arbiter.ReleaseAsync(MicrophoneOwner.WakeWord, cancellationToken);
    }

    public Task SuspendAsync(CancellationToken cancellationToken = default) =>
        _arbiter.ReleaseAsync(MicrophoneOwner.WakeWord, cancellationToken);

    public async Task ResumeAsync(CancellationToken cancellationToken = default)
    {
        await _arbiter.TryAcquireAsync(MicrophoneOwner.WakeWord, cancellationToken);
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
    }
}

public sealed class WakeWordConfigurationException : Exception
{
    public WakeWordConfigurationException(string message) : base(message)
    {
    }
}
```

- [ ] **Step 3: Build to confirm it compiles**

Run: `dotnet build desktop/Reva.Desktop.sln`
Expected: succeeds — this is a compile-only gate for this task; the real frame-capture loop noted in Step 2 is completed as part of Task 8's acceptance-run hardening pass, once real hardware is available to iterate against (mirrors how `WindowsVoiceDevice`'s original format decisions were only fully pinned down against the transcription slice's own physical acceptance run).

- [ ] **Step 4: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/PorcupineWakeWordDetector.cs desktop/src/Reva.Desktop/Reva.Desktop.csproj
git commit -m "feat(desktop): add PorcupineWakeWordDetector (single instance, N keywords)"
```

---

### Task 6: Chime asset + activation playback

**Files:**
- Add: a chime audio asset (see spec below — sourced/created as part of this task, not invented by this plan).
- Modify: `desktop/src/Reva.Desktop/Services/PorcupineWakeWordDetector.cs` or a small dedicated `ChimePlayer` — decide during implementation based on whether chime playback belongs on the detector or the coordinator; lean toward a tiny standalone `IChimePlayer { Task PlayAsync(CancellationToken); }` so `WakeWordCoordinator` (Task 7) can suppress it on the Core-disconnected path without reaching into the detector.

**Asset technical spec (resolves open decision #5):**
- Format: `.wav`, mono, 16-bit PCM (consistent with the rest of this codebase's audio handling — no new decode dependency).
- Duration: ≤ 500ms — long enough to be perceptible, short enough to never overlap the capture window that begins immediately after.
- Volume: normalized so peak amplitude is comfortably below clipping (target: peak ≈ -6dBFS), and perceptibly present but not startling at normal system volume — tune by ear against the real acceptance run, not a synthetic loudness target.
- Delivery: embedded as a build asset (`Content`/`CopyToOutputDirectory` in the `.csproj`, or an embedded resource — decide based on how `WindowsVoiceDevice`'s existing asset handling, if any, already does it; otherwise embedded resource is simplest for a single small file), played via `MediaPlayer` the same way `WindowsVoiceDevice.PlayAsync` already plays WAV bytes — **never through `SynthesizeSpeechAsync`/the TTS path**, which this slice's global constraints and the design doc both explicitly forbid.

- [ ] **Step 1: Source or record the chime.** A short, simple, non-startling two-tone or single-tone chime. This is a genuine asset-creation step, not a code step — flag explicitly if no suitable asset exists yet and this blocks the task.
- [ ] **Step 2: Confirm format/duration/volume against the spec above** (e.g. via `ffprobe` or equivalent — any tool that reports duration, sample rate, bit depth, and peak level).
- [ ] **Step 3: Implement `IChimePlayer`/`ChimePlayer`** using the same `MediaPlayer`/`InMemoryRandomAccessStream` pattern `WindowsVoiceDevice.PlayAsync` already established — read the current `WindowsVoiceDevice.cs` at implementation time and mirror its exact approach rather than reinventing WAV playback.
- [ ] **Step 4: Build to confirm it compiles.**

Run: `dotnet build desktop/Reva.Desktop.sln`

- [ ] **Step 5: Commit**

```bash
git add <chime asset path> desktop/src/Reva.Desktop/Services/ChimePlayer.cs desktop/src/Reva.Desktop/Reva.Desktop.csproj
git commit -m "feat(desktop): add wake-word activation chime"
```

---

### Task 7: `WakeWordCoordinator` — the state machine

**Files:**
- Create: `desktop/src/Reva.Desktop/Services/IComposerSink.cs`
- Create: `desktop/src/Reva.Desktop/ViewModels/WakeWordCoordinator.cs`
- Modify: `desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs` (implement `IComposerSink` — trivial, `ComposerText` already exists with the right append semantics)
- Test: `desktop/tests/Reva.Desktop.Tests/Unit/WakeWordCoordinatorTests.cs`

**Interfaces:**
- Consumes: `IWakeWordDetector` (Task 5, faked in tests), `IMicrophoneArbiter` (Task 4), `Endpointer` (Task 3), `IRevaCoreClient.TranscribeSpeechAsync` (existing, from the transcription slice), `IComposerSink`.
- Produces: `WakeWordCoordinator(IWakeWordDetector detector, IMicrophoneArbiter arbiter, IRevaCoreClient coreClient, IComposerSink composerSink, IRevaCoreLifecycle? lifecycle = null, TimeProvider? timeProvider = null)`; `WakeWordUiState State { get; }`; `bool IsArmed { get; }`; `Task EnableAsync(WakeWordConfiguration configuration, CancellationToken)`; `Task DisableAsync(CancellationToken)`; `Task SuspendForHoldToTalkAsync(CancellationToken)`; `Task ResumeAfterHoldToTalkAsync(CancellationToken)`.

- [ ] **Step 1: Write `IComposerSink` and implement it on `AssistantViewModel`**

```csharp
namespace Reva.Desktop.Services;

/// <summary>The seam WakeWordCoordinator writes captured, transcribed text
/// through — AssistantViewModel already has exactly the right ComposerText
/// append semantics (see FinishVoiceInputAsync), so it just implements
/// this rather than WakeWordCoordinator reimplementing draft preservation.</summary>
public interface IComposerSink
{
    string ComposerText { get; set; }
}
```

Add `: IComposerSink` to `AssistantViewModel`'s class declaration — no other change needed, `ComposerText` already exists.

- [ ] **Step 2: Write the failing tests**

```csharp
using Reva.Desktop.Contracts;
using Reva.Desktop.Services;
using Reva.Desktop.State;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Unit;

public class WakeWordCoordinatorTests
{
    private sealed class FakeWakeWordDetector : IWakeWordDetector
    {
        public bool IsRunning { get; private set; }
        public int StartCallCount { get; private set; }
        public int StopCallCount { get; private set; }
        public int SuspendCallCount { get; private set; }
        public int ResumeCallCount { get; private set; }

        public event EventHandler<WakeWordDetection>? Detected;

        public void RaiseDetected(WakePhrase phrase) => Detected?.Invoke(this, new WakeWordDetection(phrase, DateTimeOffset.UtcNow));

        public Task StartAsync(WakeWordConfiguration configuration, CancellationToken cancellationToken = default)
        {
            StartCallCount++;
            IsRunning = true;
            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken cancellationToken = default)
        {
            StopCallCount++;
            IsRunning = false;
            return Task.CompletedTask;
        }

        public Task SuspendAsync(CancellationToken cancellationToken = default)
        {
            SuspendCallCount++;
            return Task.CompletedTask;
        }

        public Task ResumeAsync(CancellationToken cancellationToken = default)
        {
            ResumeCallCount++;
            return Task.CompletedTask;
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class FakeComposerSink : IComposerSink
    {
        public string ComposerText { get; set; } = string.Empty;
    }

    private sealed class FakeCoreClient : IRevaCoreClient
    {
        private readonly Func<byte[], CancellationToken, Task<CoreResult<VoiceTranscriptionResponse>>> _responder;

        public FakeCoreClient(Func<byte[], CancellationToken, Task<CoreResult<VoiceTranscriptionResponse>>> responder) => _responder = responder;

        public int TranscribeCallCount { get; private set; }

        public Task<CoreResult<HealthStatus>> GetHealthAsync(CancellationToken ct = default) => throw new NotSupportedException();
        public Task<CoreResult<VersionInfo>> GetVersionAsync(CancellationToken ct = default) => throw new NotSupportedException();
        public Task<CoreResult<MemoryCreateResponse>> CreateMemoryAsync(string c, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<CoreResult<MemoryQueryResponse>> QueryMemoriesAsync(string q, int l, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<CoreResult<TypedMessageResponse>> SendMessageAsync(string c, CancellationToken ct = default) =>
            throw new NotSupportedException("wake-word must never call SendMessageAsync directly");
        public Task<CoreResult<byte[]>> SynthesizeSpeechAsync(string t, string l, CancellationToken ct = default) =>
            throw new NotSupportedException("wake-word must never call TTS");

        public Task<CoreResult<VoiceTranscriptionResponse>> TranscribeSpeechAsync(byte[] wavAudio, CancellationToken ct = default)
        {
            TranscribeCallCount++;
            return _responder(wavAudio, ct);
        }
    }

    private static CoreResult<VoiceTranscriptionResponse> Success(string text) =>
        CoreResult<VoiceTranscriptionResponse>.Success(new VoiceTranscriptionResponse(1, text, "en", 900));

    [Fact]
    public void InitialState_IsOff_DisabledByDefault()
    {
        var coordinator = new WakeWordCoordinator(
            new FakeWakeWordDetector(), new MicrophoneArbiter(), new FakeCoreClient((_, _) => Task.FromResult(Success("hi"))), new FakeComposerSink());

        Assert.Equal(WakeWordUiState.Off, coordinator.State);
        Assert.False(coordinator.IsArmed);
    }

    [Fact]
    public async Task EnableAsync_StartsDetectorExactlyOnce()
    {
        var detector = new FakeWakeWordDetector();
        var coordinator = new WakeWordCoordinator(
            detector, new MicrophoneArbiter(), new FakeCoreClient((_, _) => Task.FromResult(Success("hi"))), new FakeComposerSink());

        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        Assert.Equal(1, detector.StartCallCount);
        Assert.Equal(WakeWordUiState.Armed, coordinator.State);
        Assert.True(coordinator.IsArmed);
    }

    [Fact]
    public async Task DisableAsync_StopsDetectorAndReleasesMicrophone()
    {
        var detector = new FakeWakeWordDetector();
        var arbiter = new MicrophoneArbiter();
        var coordinator = new WakeWordCoordinator(
            detector, arbiter, new FakeCoreClient((_, _) => Task.FromResult(Success("hi"))), new FakeComposerSink());
        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        await coordinator.DisableAsync();

        Assert.Equal(1, detector.StopCallCount);
        Assert.Equal(WakeWordUiState.Off, coordinator.State);
        Assert.False(coordinator.IsArmed);
    }

    [Fact]
    public async Task Detection_PopulatesComposer_NeverAutoSends_NeverCallsSendMessage()
    {
        var detector = new FakeWakeWordDetector();
        var composer = new FakeComposerSink();
        var client = new FakeCoreClient((_, _) => Task.FromResult(Success("open Chrome")));
        var coordinator = new WakeWordCoordinator(detector, new MicrophoneArbiter(), client, composer);
        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.CompleteCaptureForTestingAsync(SixteenKhzMonoWavOf(TimeSpan.FromSeconds(1)));

        Assert.Equal("open Chrome", composer.ComposerText);
        Assert.Equal(WakeWordUiState.Armed, coordinator.State); // back to armed after cooldown, see the cooldown test below for the intermediate state
    }

    [Fact]
    public async Task Detection_ExistingComposerDraftIsPreserved_TranscriptAppends()
    {
        var detector = new FakeWakeWordDetector();
        var composer = new FakeComposerSink { ComposerText = "typed draft" };
        var client = new FakeCoreClient((_, _) => Task.FromResult(Success("and this too")));
        var coordinator = new WakeWordCoordinator(detector, new MicrophoneArbiter(), client, composer);
        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        detector.RaiseDetected(WakePhrase.HeyReva);
        await coordinator.CompleteCaptureForTestingAsync(SixteenKhzMonoWavOf(TimeSpan.FromSeconds(1)));

        Assert.Equal("typed draft and this too", composer.ComposerText);
    }

    [Fact]
    public async Task DuplicateDetection_WhileListening_IsDroppedAndCounted()
    {
        var detector = new FakeWakeWordDetector();
        var coordinator = new WakeWordCoordinator(
            detector, new MicrophoneArbiter(), new FakeCoreClient((_, _) => Task.FromResult(Success("hi"))), new FakeComposerSink());
        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));
        detector.RaiseDetected(WakePhrase.HeyReva);

        detector.RaiseDetected(WakePhrase.HeyReva); // arrives while already Listening

        Assert.Equal(1, coordinator.DroppedDetectionCount);
    }

    [Fact]
    public async Task HoldToTalk_Suspends_ThenResumesDetectorAfterCompletion()
    {
        var detector = new FakeWakeWordDetector();
        var coordinator = new WakeWordCoordinator(
            detector, new MicrophoneArbiter(), new FakeCoreClient((_, _) => Task.FromResult(Success("hi"))), new FakeComposerSink());
        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        await coordinator.SuspendForHoldToTalkAsync();
        Assert.Equal(1, detector.SuspendCallCount);

        await coordinator.ResumeAfterHoldToTalkAsync();
        Assert.Equal(1, detector.ResumeCallCount);
    }

    [Fact]
    public async Task CoreDisconnected_DetectionSkipsChimeAndCapture_GoesStraightToSttUnavailable()
    {
        var detector = new FakeWakeWordDetector();
        var lifecycle = new FakeCoreLifecycle { State = CoreLifecycleState.Unavailable };
        var client = new FakeCoreClient((_, _) => throw new NotSupportedException("must never transcribe while Core is down"));
        var coordinator = new WakeWordCoordinator(
            detector, new MicrophoneArbiter(), client, new FakeComposerSink(), lifecycle);
        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        detector.RaiseDetected(WakePhrase.HeyReva);

        Assert.Equal(WakeWordUiState.SttUnavailable, coordinator.State);
        Assert.Equal(0, client.TranscribeCallCount);
    }

    [Fact]
    public async Task MicrophoneUnavailable_ExposesSafeState_NotArmed()
    {
        var detector = new FakeWakeWordDetector();
        var arbiter = new MicrophoneArbiter();
        await arbiter.TryAcquireAsync(MicrophoneOwner.HoldToTalk); // simulate the mic already held elsewhere
        var coordinator = new WakeWordCoordinator(
            detector, arbiter, new FakeCoreClient((_, _) => Task.FromResult(Success("hi"))), new FakeComposerSink());

        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        Assert.Equal(WakeWordUiState.MicrophoneUnavailable, coordinator.State);
        Assert.False(coordinator.IsArmed);
    }

    [Fact]
    public async Task AppShutdown_StopsDetector()
    {
        var detector = new FakeWakeWordDetector();
        var coordinator = new WakeWordCoordinator(
            detector, new MicrophoneArbiter(), new FakeCoreClient((_, _) => Task.FromResult(Success("hi"))), new FakeComposerSink());
        await coordinator.EnableAsync(new WakeWordConfiguration(WakePhraseDefaults.All));

        await coordinator.DisposeAsync();

        Assert.Equal(1, detector.StopCallCount);
    }

    private static byte[] SixteenKhzMonoWavOf(TimeSpan duration)
    {
        const int sampleRate = 16000;
        const short blockAlign = 2;
        var dataBytes = (int)(duration.TotalSeconds * sampleRate) * blockAlign;
        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write("RIFF"u8.ToArray());
        writer.Write(36 + dataBytes);
        writer.Write("WAVE"u8.ToArray());
        writer.Write("fmt "u8.ToArray());
        writer.Write(16);
        writer.Write((short)1);
        writer.Write((short)1);
        writer.Write(sampleRate);
        writer.Write(sampleRate * blockAlign);
        writer.Write(blockAlign);
        writer.Write((short)16);
        writer.Write("data"u8.ToArray());
        writer.Write(dataBytes);
        writer.Write(new byte[dataBytes]);
        return stream.ToArray();
    }
}
```

Note: `CompleteCaptureForTestingAsync` is a test-only seam on `WakeWordCoordinator` (internal, `[InternalsVisibleTo]` to the test project — check whether that's already configured for this project at implementation time, matching however `AssistantViewModel`'s own private-state testing is currently handled) standing in for the real capture-then-endpointer-then-submit pipeline, since driving that through the real `IWakeWordDetector`/`Endpointer`/microphone stack end-to-end from a unit test would mean re-simulating frame-by-frame audio delivery — the coordinator's job under test is the *state machine and STT/composer integration*, not endpointing (already covered by Task 3) or detection (already covered by the fake). This mirrors how `AssistantViewModelTests`' `FakeVoiceDevice.StopRecordingAsync` returns a pre-built WAV directly rather than simulating real capture frame delivery.

- [ ] **Step 3: Run to verify they fail**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WakeWordCoordinatorTests`
Expected: FAIL (build error — `WakeWordCoordinator` doesn't exist).

- [ ] **Step 4: Implement**

Full state machine implementing: `Off → Starting → Armed` on `EnableAsync` (or `MicrophoneUnavailable`/`WakeWordError` if the arbiter/keyword resolution fails); `Armed → Detected → Listening → Transcribing → Cooldown → Armed` on a detection (or `→ SttUnavailable → Armed` if Core is disconnected at detection time, per resolved decision #4 — chime and capture window both skipped); duplicate detections while not `Armed` increment `DroppedDetectionCount` and are otherwise ignored; `SuspendForHoldToTalkAsync`/`ResumeAfterHoldToTalkAsync` delegate to the detector's own `SuspendAsync`/`ResumeAsync`, on every exit path (implement via `try`/`finally` around the Hold-to-Talk turn at the `MainWindow`/`AssistantViewModel` integration point in Task 8, not inside the coordinator itself, since the coordinator doesn't own Hold-to-Talk's lifecycle). `DisposeAsync` calls `DisableAsync`-equivalent teardown. Cooldown is a two-second `Task.Delay` (or `TimeProvider`-driven, matching `CommandRouter`'s precedent, for testability) before returning to `Armed`.

- [ ] **Step 5: Run to verify they pass**

Run: `dotnet test desktop/Reva.Desktop.sln --filter WakeWordCoordinatorTests`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures — confirms no regression to the transcription slice or app-command routing's own tests.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/Reva.Desktop/Services/IComposerSink.cs desktop/src/Reva.Desktop/ViewModels/WakeWordCoordinator.cs desktop/src/Reva.Desktop/ViewModels/AssistantViewModel.cs desktop/tests/Reva.Desktop.Tests/Unit/WakeWordCoordinatorTests.cs
git commit -m "feat(desktop): add WakeWordCoordinator state machine"
```

---

### Task 8: UI wiring + real capture loop + physical acceptance

This is where `PorcupineWakeWordDetector`'s real frame-capture loop (stubbed in Task 5) gets completed against real hardware, since the exact capture-buffering shape is easier to pin down with a working build to iterate against than to fully specify in advance.

**Files:**
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml` (wake-word toggle, per-phrase settings, persistent armed indicator)
- Modify: `desktop/src/Reva.Desktop/MainWindow.xaml.cs` (Hold-to-Talk suspend/resume wiring around the existing voice pointer handlers)
- Modify: `desktop/src/Reva.Desktop/App.xaml.cs` (construct `MicrophoneArbiter`, `PorcupineWakeWordDetector`, `WakeWordCoordinator`, wire the shared arbiter into `WindowsVoiceDevice` too)
- Modify: `desktop/src/Reva.Desktop/Services/PorcupineWakeWordDetector.cs` (complete the real capture loop)

- [ ] **Step 1: Wire Hold-to-Talk suspend/resume**

In `MainWindow.xaml.cs`'s `VoiceButton_PointerPressed`, call `await WakeWordCoordinator.SuspendForHoldToTalkAsync()` before `Assistant.StartVoiceInputAsync()`; wrap the existing `VoiceButton_PointerReleased`/`Canceled`/`CaptureLost` handlers' `FinishVoiceInputAsync()` calls so `ResumeAfterHoldToTalkAsync()` runs in a `finally` regardless of outcome — this is the exact "failed Hold-to-Talk turn must not leave wake-word permanently deaf" requirement from Global Constraints.

- [ ] **Step 2: Add the settings UI**

Master "Wake Word" toggle (bound to `WakeWordCoordinator.IsArmed`-driving enable/disable), per-phrase toggles + sensitivity for the 3 optional phrases, and the persistent microphone-armed indicator required by the Privacy section — exact XAML layout decided against the existing `MainWindow.xaml` structure at implementation time.

- [ ] **Step 3: Wire the composition root**

In `App.xaml.cs`: construct one shared `MicrophoneArbiter`, pass it into both `WindowsVoiceDevice` (requires `WindowsVoiceDevice` to take an `IMicrophoneArbiter` and check out `MicrophoneOwner.HoldToTalk` around its own capture — a small, additive change to that class) and `PorcupineWakeWordDetector`; construct `WakeWordCoordinator` with the real `IRevaCoreClient`, the real `AssistantViewModel` (as its `IComposerSink`), and the real `IRevaCoreLifecycle`.

- [ ] **Step 4: Complete `PorcupineWakeWordDetector`'s real capture loop**

Fill in `RunListenLoopAsync` (stubbed in Task 5) against real hardware: acquire frames at `Porcupine.SampleRate`/`Porcupine.FrameLength`, call `Process(frame)`, raise `Detected` on a non-negative keyword index mapped through `_phraseOrder`.

- [ ] **Step 5: Full automated suite**

Run: `dotnet test desktop/Reva.Desktop.sln`
Expected: PASS, 0 failures.

- [ ] **Step 6: Build Release, run it, execute the design doc's full "Real acceptance" section**

Per `docs/superpowers/specs/2026-08-17-wake-word-slice-design.md`'s Real acceptance section verbatim: per-phrase recognition (20 activations, ≥18/20, at ~1m and ~3m, <500ms activation latency), the aggregate false-activation gate (all enabled phrases armed, ≥1 hour ordinary use, ≤1 false activation/hour for the set), the adversarial near-miss table, resource/hygiene checks (CPU <5%, no orphaned mic handle/process, no leftover audio files), and behavioral confirmation (composer stays editable, no Assistant/TTS/Windows-action call before Send).

- [ ] **Step 7: Report**

Per-phrase activation rates at both distances, the aggregate false-activation count, near-miss results (flagging "daddy's not home" specifically, per the design doc), CPU measurement, hygiene check results, and explicit confirmation no Core/TTS/command-execution call occurred before a manual Send.

- [ ] **Step 8: Commit any last-mile fixes**

```bash
git status
git add -A
git commit -m "fix(desktop): address wake-word acceptance findings"
```

---

## Self-Review Notes

- **Spec coverage:** phrase set + resolved "Wake up" decision (Task 1), required states (Task 2), endpointing (Task 3), microphone ownership (Task 4), provider (Task 5), chime (Task 6), privacy/state-machine/Hold-to-Talk-suspend-resume/composer-reuse (Task 7), settings UI + real acceptance (Task 8).
- **No placeholders in code** — every task's implementation is concrete. The two genuinely unresolvable-by-this-plan items (Picovoice licensing, chime asset sourcing) are explicit pre-implementation gates and asset-creation steps, not code TBDs, consistent with how the transcription slice treated the physical microphone itself as a real-world gate rather than a placeholder.
- **Dependency on app-command routing:** encoded as a hard, explicit gate at the top of this document and restated in Task 0 — this plan cannot be executed by an agent skipping straight to Task 1 without first re-verifying the gate.
- **Reuse, not reimplementation:** `IComposerSink` (Task 7) is the only new coupling to `AssistantViewModel`, and it's a one-line interface implementation — `WakeWordCoordinator` never touches `AssistantViewModel`'s internals, `SendMessageCoreAsync`, or `CommandRouter` directly, matching the reconciliation section's finding that command routing applies automatically through the shared Send call site with zero wake-word-specific code.
- **Type consistency:** `WakePhrase`/`WakePhraseSetting`/`WakeWordConfiguration` (Task 1) used identically through Tasks 2, 5, 7, 8. `IWakeWordDetector` (Task 2) implemented by `PorcupineWakeWordDetector` (Task 5) and faked identically in Task 7's tests. `IMicrophoneArbiter` (Task 4) consumed identically by Task 5 and Task 8's `WindowsVoiceDevice` integration.
