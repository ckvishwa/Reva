# Wake-word slice — multi-phrase — v3 design (BLOCKED, not started)

> **Status: spec captured, implementation blocked.** Supersedes v2 (2026-08-17). Do not start this slice until:
>
> 1. The Windows app-command routing slice (`…-windows-app-command-routing-v2.md`) has every task reviewed clean **and** its Task 7 physical acceptance passed — including Step 7, the spoken-confirm check, which is the step this slice's safety story depends on.
> 2. The transcription-only voice slice is fully closed out (its Task 9 physical-microphone acceptance).
> 3. Picovoice custom-keyword licensing is verified against the actual account/tier (open decision #2 — cannot be resolved by reasoning).
>
> The chime asset is **not** a gate item in v3 — v2 listed it as a precondition while its own Task 6 produced it, which is a gate that can never clear. It is now an ordinary task inside the plan.

## What changed from v2, and why

A cross-document review found four defects that only appear when the wake-word design, the app-command design, and the transcription slice's actual shipped code are read together:

1. **`IComposerSink` had no append semantics.** v2 defined it as `{ string ComposerText { get; set; } }` and claimed `AssistantViewModel` "already has exactly the right append semantics." It does not — the append lives *inside* `FinishVoiceInputAsync`, not in the `ComposerText` setter. Writing through the v2 sink would have overwritten the user's draft, and the plan's own draft-preservation test could not have passed. The seam is now `AppendTranscription(string)`.
2. **The microphone arbiter was advisory.** v2's arbiter tracked a flag that nothing forced anyone to check, `SuspendAsync` released the flag without stopping the capture loop, and `ResumeAsync` discarded the acquire result. The failure mode is exactly the one this slice is supposed to prevent: wake word says "Armed" while the microphone belongs to something else. The arbiter now **owns the audio stream and issues leases** — there is no way to get a frame without holding one.
3. **Nobody owned frame delivery.** v2's Task 4 deferred real capture to Task 5, Task 5 stubbed its listen loop and deferred to Task 8, and Task 8 assumed both existed. Audio capture is now built once, in the arbiter, with its own tests.
4. **Detection events cross threads.** Porcupine's frame loop is not the UI thread. v2's coordinator raised state changes directly from the detection callback — the identical bug the transcription slice's v2 had to fix for lifecycle events. Marshalling is now specified.

Plus: the state machine had a hole (`SttUnavailable` never returned to `Armed`), the chime could be recorded by the capture it precedes, and the plan's `MicrophoneUnavailable` test passed for the wrong reason.

---

## Goal

While REVA Desktop is running, the user can enable local wake-word mode. Saying any *enabled* wake phrase activates speech capture without touching the mouse. The following speech is transcribed, stripped only of the leading wake phrase when present, and then sent through the same deterministic `ICommandRouter`/`AssistantViewModel` Send path as composer text.

The behavior is intentionally asymmetric: safe allowlisted Open commands may execute automatically after wake-word capture, Close requests may only create the existing confirmation prompt, and spoken `confirm` can never approve a close. Ordinary non-command speech is not sent to Core/ADK/LLM; it is left editable in `ComposerText`.

---

## Wake phrase set

| # | Spoken phrase | Keyword slug | Syllables | Default | Sensitivity | Risk |
|---|---|---|---|---|---|---|
| 1 | "Hey Reva" | `hey-reva` | 3 | **On** | 0.55 | Low — the reference phrase |
| 2 | "You up Reva" | `you-up-reva` | 4 | Off | 0.45 | Medium — leading function words are weak; "Reva" carries it |
| 3 | "Daddy's home" | `daddys-home` | 3 | Off | 0.45 | Medium — distinctive, but a sentence people actually say |
| 4 | "Reva wake up" | `reva-wake-up` | 4 | Off | 0.40 | Medium — replaces the bare 2-syllable "wake up" |

**"Wake up" was replaced, not shipped.** Two syllables, both extremely common, appearing inside ordinary sentences ("I need to wake up earlier", "wake up call") and near-missing on "make up" / "break up". Porcupine's false-accept rate tracks phrase length and phonetic distinctiveness; a 2-syllable common phrase is worst-case on both. "Reva wake up" keeps the intent, anchored by the name. This decision is now **resolved**, and the plan carries a regression test that a plain `WakeUp` phrase never returns.

**Every phrase is off by default except "Hey Reva".** First launch arms nothing (wake word itself is off); first *enable* arms phrase 1 only.

**The false-accept budget is shared, not per-phrase.** The target is ≤ 1 false activation per hour *for the armed set*. With four phrases armed that is ~0.25/hour each. Measuring each phrase alone and declaring victory is the mistake to avoid — the aggregate run is the gate.

**Apostrophes don't survive training.** Picovoice Console takes lowercase words: train `daddys home`, not `Daddy's home`. The display string (settings UI) and the training string (what produced the `.ppn`) are separate values so they cannot drift.

**Phrase identity is metadata, not behavior.** The detector reports which phrase fired; that identity is logged and shown in metrics. It does **not** change what happens next — same chime, same capture window, same composer append, same no-auto-send. Per-phrase behavior ("daddy's home" → run a routine) is app-command routing's territory.

---

## Required flow

1. User explicitly enables Wake Word with at least one phrase enabled.
2. UI shows **Wake Word Armed** with a persistent microphone indicator listing the live phrases.
3. The detector continuously receives 16kHz mono PCM frames **from the arbiter's lease**.
4. No STT call, no recording file, and no Assistant call occurs before detection.
5. An enabled phrase is detected; the detector reports its identity.
6. **Capture begins and the chime plays — in that order** (see below).
7. State becomes **Listening**.
8. Speech following the wake phrase is captured.
9. Capture stops at 800ms of trailing silence or an 8-second hard maximum.
10. The audio goes through the existing STT path (`IRevaCoreClient.TranscribeSpeechAsync`, same 250ms floor, same WAV validation).
11. Strip only the leading wake phrase from the transcript, preserving the remainder exactly enough for deterministic routing.
12. Submit the remaining text through `AssistantViewModel`'s existing Send path with `CommandSource.Transcribed`.
13. If the router recognizes a safe Open command, it may execute automatically and the assistant pipeline is skipped.
14. If the router recognizes a Close command, it may create the existing confirmation state and prompt. A spoken `confirm` remains `Transcribed`, is ignored by the router, and must not close anything.
15. If the text is not a command, restore it to `ComposerText` as transcribed text and do not call Core/ADK/LLM.
16. Return to **Wake Word Armed** after a two-second cooldown.

Steps 10-15 are *reuse*, not reimplementation. If this slice grows another allowlist, another executor, fuzzy command matching, or a second send/router pipeline, the design has gone wrong.

### Chime ordering (v2 defect)

v2 said "play the chime, then state becomes Listening," and asserted that the `Detected` state existed "so the chime can't overlap capture" — but nothing enforced waiting for playback to finish. The chime plays through the speakers while the microphone is live, so **the chime lands in the recording** and may transcribe as a spurious token.

Two workable orderings; v3 picks the second:

- *Await chime completion, then start capture.* Costs the user 300-500ms of speech — they will already be talking.
- **Start capture immediately, play the chime concurrently, and discard the first N milliseconds of captured audio** where N is the chime's duration plus a small margin. The chime is a fixed asset of known length, so N is a constant, not a guess. The user's speech after the chime is preserved intact.

The discarded prefix must be accounted for in the 250ms minimum: the *post-discard* audio is what gets length-checked.

---

## Microphone ownership — the arbiter owns the stream

This was v2's largest defect and is the section that matters most.

v2's arbiter was "a pure ownership tracker (who currently holds the microphone), not a capture implementation" — while `WindowsVoiceDevice` and `PorcupineWakeWordDetector` each still did their own `MediaCapture` work. That is an honor system. Nothing prevented a component from capturing without asking, and v2's own `SuspendAsync` did exactly that: it released the flag and left the Porcupine loop running against a device it no longer owned.

**v3: the arbiter owns the audio input and hands out leases. There is no other way to get audio.**

```csharp
public enum MicrophoneOwner { WakeWord, HoldToTalk }

public interface IMicrophoneArbiter
{
    MicrophoneOwner? CurrentOwner { get; }

    /// <summary>Returns null if another owner holds the microphone. The lease
    /// IS the capture stream — a component that doesn't hold one cannot read
    /// a single frame.</summary>
    Task<IMicrophoneLease?> TryAcquireAsync(
        MicrophoneOwner owner, CancellationToken cancellationToken = default);
}

public interface IMicrophoneLease : IAsyncDisposable
{
    MicrophoneOwner Owner { get; }
    bool IsActive { get; }

    /// <summary>16kHz mono 16-bit PCM, delivered in exactly frameLength-sample
    /// chunks. Completes when the lease is disposed or capture fails.</summary>
    IAsyncEnumerable<short[]> ReadFramesAsync(int frameLength, CancellationToken cancellationToken);

    /// <summary>Buffers frames into a WAV for the STT path — the same format
    /// WindowsVoiceDevice already produces.</summary>
    Task<byte[]> RecordUntilAsync(Func<short[], bool> stopWhen, CancellationToken cancellationToken);
}
```

Consequences, each of which fixes a v2 failure:

- **Suspend is release.** `SuspendForHoldToTalkAsync` disposes the wake-word lease, which stops the frame enumerable, which ends the Porcupine loop. There is no "released the flag but kept reading" state, because the flag *is* the stream.
- **Resume can fail, and failure is visible.** `ResumeAfterHoldToTalkAsync` re-acquires; a null lease means the microphone is genuinely gone and the state becomes **Microphone Unavailable**, not a silent lie. v2 discarded the acquire result and would have reported **Armed** while deaf.
- **Only one owner can exist.** The arbiter holds one `MediaCapture`; a second `TryAcquireAsync` from a different owner returns null while a lease is live.
- **Frame delivery has exactly one implementation.** No Task-to-Task deferral chain.

Remaining ownership rules:

- Hold-to-Talk always wins: the coordinator suspends wake word *before* Hold-to-Talk requests its lease, and resumes in a `finally` covering success, cancel, capture-lost, and error. A failed Hold-to-Talk turn that leaves wake word deaf is the specific regression to test for.
- Wake detection cannot re-activate while in Detected, Listening, Transcribing, or Cooldown. Duplicate detections in that window are dropped and counted.
- Windows lock, sleep, session switch, and audio-device change dispose the lease; recovery re-acquires only when the device is genuinely available, never optimistically.
- App shutdown disposes the lease and stops the detector deterministically. Given the Voice V1 orphaned-`powershell.exe` history, acceptance does a real handle/PID check rather than assuming.

---

## Threading

The Porcupine frame loop runs on a background thread. Detection therefore arrives off the UI thread, and every state transition it causes raises `PropertyChanged` on properties bound to the armed indicator. Raising those off-thread throws `RPC_E_WRONG_THREAD` in WinUI.

`WakeWordCoordinator` captures a `DispatcherQueue` at construction (null under xUnit) and marshals every state transition through it, exactly as `AssistantViewModel` does for `IRevaCoreLifecycle.StateChanged` after the transcription slice's v2. The state field itself is written only on the dispatcher, so the state machine needs no lock; `DroppedDetectionCount` is incremented with `Interlocked` because it is touched from the detection thread before marshalling.

**Detection must transition state synchronously on arrival**, before any `await`. v2's duplicate-detection test raised two events back to back and expected the second to be dropped — with an async-void handler the first may not have left `Armed` yet, and both would be accepted. The handler flips `Armed → Detected` under a lock the instant the event fires, then queues the rest of the work.

---

## Provider design

```csharp
public sealed record WakeWordDetection(WakePhrase Phrase, DateTimeOffset DetectedAtUtc);

public enum WakePhrase { HeyReva, YouUpReva, DaddysHome, RevaWakeUp }

public sealed record WakePhraseSetting(WakePhrase Phrase, bool Enabled, float Sensitivity);

public sealed record WakeWordConfiguration(IReadOnlyList<WakePhraseSetting> Phrases);

public interface IWakeWordDetector : IAsyncDisposable
{
    bool IsRunning { get; }
    event EventHandler<WakeWordDetection>? Detected;

    /// <summary>The lease is supplied by the caller — the detector never
    /// acquires the microphone itself. One acquisition point, one owner.</summary>
    Task StartAsync(
        WakeWordConfiguration configuration,
        IMicrophoneLease lease,
        CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);
}
```

`SuspendAsync`/`ResumeAsync` are **gone** from the interface. They existed in v2 only to toggle the advisory flag; with leases, suspend is "stop the detector and dispose the lease" and resume is "acquire a lease and start the detector" — the same two methods that already exist. Fewer states, fewer ways to be half-suspended.

- **First provider: Porcupine .NET for Windows.** All Picovoice-shaped code lives in `PorcupineWakeWordDetector`; nothing else references the SDK.
- **One instance, N keywords.** `Porcupine.FromKeywordPaths(accessKey, keywordPaths, sensitivities)`; `Process(short[])` returns the index of the detected keyword or -1. Map the index back through the same ordered list used to build the instance. Never one detector per phrase — that multiplies CPU and creates four components racing for frames.
- **Reconfiguration means rebuild.** Enabling, disabling, or retuning a phrase stops the detector, disposes the instance, and constructs a new one. Live mutation is not supported by the library.
- **Frame discipline.** Porcupine requires exactly `FrameLength` samples of 16-bit mono PCM at `SampleRate`. The lease delivers exactly that size; `PorcupineWakeWordDetector` passes `Porcupine.FrameLength` to `ReadFramesAsync` and never sees a partial frame. Assert at startup that `Porcupine.SampleRate == 16000`, the format the capture path already produces.
- **Keyword assets are shipped, never fetched.** `.ppn` files live in `%LOCALAPPDATA%\REVA\wake-word\keywords\`, placed by an explicit setup step. A missing or unreadable file for an *enabled* phrase is **Wake Word Error** naming the phrase — never a silent skip that arms a subset.
- **AccessKey** from `REVA_PICOVOICE_ACCESS_KEY` only. Never committed, logged, or echoed in an error message. Missing or invalid → **Wake Word Error** with a message that says a key is required and contains no fragment of one.
- **Licensing is unresolved.** Custom `.ppn` files are generated in Picovoice Console under account- and platform-specific terms. Confirm the tier permits four custom Windows keywords and that the files carry no expiry that would silently brick wake-word mode months later. This is a gate item; it cannot be reasoned out.

---

## Endpointing

The 800ms-silence rule needs a voice-activity decision — a real component, not a constant.

- **RMS energy threshold with hysteresis** over the same 16kHz frames. No new dependency, fully local, unit-testable against synthetic PCM. Picovoice Cobra VAD is the fallback only if acceptance fails on RMS, since it is a second licensed component.
- The 8-second maximum is enforced by elapsed time independent of the VAD, so a stuck-open threshold can never hold the microphone indefinitely. It is also enforced by a **wall-clock timeout in the coordinator**, not only by the frame loop — if frames stop arriving entirely (device yanked), the capture must still terminate.
- Trailing silence is trimmed from the submitted audio, and the chime prefix is discarded, but the 250ms minimum applies to what remains: a wake phrase followed by nothing fails the same way a too-short hold does.
- **The RMS threshold is a calibration value, not a constant to guess once.** The plan carries a calibration step against real room audio during acceptance; a threshold tuned only against synthetic square waves will not survive contact with a real microphone's noise floor.

---

## Required states

**Wake Word Off, Starting, Armed, Detected, Listening, Transcribing, Cooldown, Microphone Unavailable, STT Unavailable, Wake Word Error.**

Ten states — adding phrases does not add states. Rules:

- **Detected** is brief but distinct, so capture start, chime, and the transition are ordered rather than racing.
- **STT Unavailable** covers Core disconnected. Per the resolved decision, wake word still arms while Core is down (the detector costs nothing to run), but a detection in that state **skips the chime and the capture window** and reports `STT Unavailable` — the user is never told a capture began that cannot complete.
  **v3 fix:** that state is transient. After the same two-second cooldown as any other turn, the coordinator returns to `Armed` (or stays in `SttUnavailable` only while Core is still down, re-evaluated on the lifecycle event). v2 had no transition out — one detection during a Core restart left wake word visually stuck forever.
- **Microphone Unavailable** is entered whenever a lease acquisition returns null, including on resume after Hold-to-Talk.
- **Wake Word Error** carries a safe category (missing key, missing keyword file, detector init failure) and, where relevant, the phrase — never the key, never PCM, never a stack trace.
- No status/enablement contradiction: if the toggle is on and the feature is non-functional, the state says why. Never "Armed" while deaf.
- Every transition logs a fixed identifier (`wakeword.state=Armed`, `wakeword.detected phrase=HeyReva`). Phrase identity is a fixed enum member and safe to log; nothing else from the audio path is.

---

## Composer integration

```csharp
public interface IComposerSink
{
    /// <summary>Appends transcribed text to the composer, preserving any
    /// existing draft, and marks the composer as machine-authored so that
    /// app-command routing will not let a spoken "confirm" resolve a pending
    /// destructive action.</summary>
    void AppendTranscription(string text);
}
```

`AssistantViewModel` implements this by calling the **same private helper** `FinishVoiceInputAsync` already uses (`AppendTranscribedText`, introduced by the app-command routing slice's Task 4). One append implementation, one source-marking implementation, two callers.

Wake-word command handling uses a companion `SubmitTranscriptionAsync` entry point on `AssistantViewModel`: it marks the text as `Transcribed`, invokes the same `SendMessageCoreAsync` path that typed Send uses, and restores non-command text to `ComposerText` when the router returns `NotACommand`. `WakeWordCoordinator` contains no app-command matching, no allowlist, no process execution, and no Core chat call logic of its own.

This is also the seam that makes the safety story hold end to end: a wake-word transcript is marked `Transcribed`, so `CommandRouter` refuses to let it confirm a close. Hands-free "confirm" cannot destroy unsaved work.

---

## What wake word makes reachable, stated plainly

Wake word can now execute only the safe half of app-command routing automatically. It does not run an app itself; it submits transcribed text to the same deterministic router used by typed Send. The honest description of the combined system is:

> **Speech → wake capture → deterministic router → safe Open may execute; Close may only prompt; ordinary speech stays editable.**

That is the intended product, and the typed confirmation gate is the destructive-action safety argument. Therefore:

- **No wake path may auto-send ordinary speech to Core/ADK/LLM.** `NotACommand` text is restored to the composer.
- **Safe Open commands may auto-execute only through the existing deterministic router and allowlist.**
- **Close commands may auto-prompt only.** The actual close still requires typed `confirm`.
- **Destructive confirmations are typing-only** (enforced by app-command routing's `CommandSource`).
- The persistent armed indicator is not decoration; it is the user's only cue that an always-listening path to their applications is live.

---

## Privacy and safety

- Wake word is **off by default** on first launch; phrases 2-4 stay off even after enabling.
- A permanent, visible armed indicator, readable without opening settings, showing which phrases are live.
- All wake-word audio is processed locally. Nothing leaves the machine before a detection.
- Pre-wake audio is never written to disk. The detection buffer is in-memory and continuously overwritten.
- Post-wake audio follows the transcription slice's temp-file discipline: deleted in a `finally` on every path including cancellation and error. **The wake path's cleanup is the coordinator's responsibility and is tested** — v2 named the rule but assigned it to nobody.
- Never log PCM, transcripts, confidence values, or per-frame data.
- Persist only: wake-word enabled/disabled, per-phrase enabled/disabled, per-phrase sensitivity.
- An immediate **Wake Word Off** control that takes effect without confirmation and disposes the lease synchronously.

---

## Real acceptance

Automated tests cannot establish that a wake word works. These are manual, on the target machine, in the room it will be used in.

**Recognition, per enabled phrase:** 20 deliberate activations in the user's normal voice; ≥ 18/20; at ~1m and again at ~3m, recorded separately; activation within 500ms of the phrase ending.

**False activations — the aggregate gate:** all enabled phrases armed, ≥ 1 hour of ordinary speech/music/video/calls, ≤ 1 false activation per hour for the set. A second hour with only the high-risk phrases armed if any of 2-4 ship, to attribute failures.

**Adversarial near-miss set** (5 utterances each, zero activations expected):

| Target | Near misses |
|---|---|
| Hey Reva | "hey Rita", "hey Reba", "hey Ava", "hey there" |
| You up Reva | "you up?", "your uber", "you okay Reva" (*may* fire — record it) |
| Daddy's home | "dad is home", "daddy's phone", "that is home", **"daddy's not home"** |
| Reva wake up | "wake up", "wake up early", "Reva woke up", "make up" |

**"Daddy's not home" is the one to watch.** Porcupine matches the phrase, not the sentence's polarity, and this slice's privacy story depends on it not activating during ordinary household conversation. "Wake up" alone firing `reva-wake-up` would mean the replacement decision bought nothing — record it explicitly.

**Ownership and hygiene:** Hold-to-Talk during armed wake word suspends and resumes cleanly, including when the Hold-to-Talk turn *fails*; CPU < 5% with the full enabled set armed; no microphone handle or child process survives shutdown (PID/handle diff); no audio files remain after a completed or aborted turn.

**Behavioral confirmation:** safe spoken Open commands route through `ICommandRouter` and never Core; spoken Close commands create only the existing prompt; ordinary spoken text stays editable in the composer with no Assistant, TTS, or Windows action; and — the cross-slice check — a wake-word-spoken "confirm" against a pending close **does not close the app**.

---

## Open decisions

1. ~~"Wake up" phrasing~~ — **resolved:** replaced with "Reva wake up" at 0.40.
2. **Picovoice custom-keyword licensing and expiry** — unresolved, gate item, requires the real account.
3. ~~Cobra vs RMS~~ — **resolved:** RMS with hysteresis; Cobra only if acceptance fails.
4. ~~Arm while Core disconnected~~ — **resolved:** arm, report `STT Unavailable` on detection, skip chime and capture, return to `Armed` after cooldown.
5. ~~Chime asset~~ — **resolved:** spec'd in the plan as an ordinary task (format, duration, level, delivery), removed from the gate.
6. **New:** the chime-prefix discard length. A constant derived from the asset's actual duration; pin it when the asset exists.

---

## Reconciliation with app-command routing (v2)

**No code-level coupling, by construction.** `CommandRouter` is invoked from one place — `AssistantViewModel.SendMessageCoreAsync`, on whatever text is in the composer when Send is pressed. It has no awareness of how the text arrived. Typed input, a Hold-to-Talk transcript, and a wake-word transcript are all subject to routing identically, with zero wake-word-specific integration code.

**One deliberate coupling exists, and it is the safety-critical one.** `IComposerSink.AppendTranscription` marks the composer as `Transcribed`, which is what makes app-command routing refuse a spoken confirmation. That is not an accident of layering — it is the mechanism, and it must survive any future refactor of either slice. A test in each slice pins it.

**The sequencing dependency is real even without coupling.** Both slices add a voice-adjacent local-execution surface. App-command routing is the narrower one (deterministic matching, a 7-entry allowlist, a typed-only confirmation gate) and is already scoped in detail. Proving it end to end first — including its spoken-confirm acceptance step — validates the pattern once before a continuously-listening detector with a provider dependency, a licensing question, and an endpointing subsystem is layered onto the same Send pipeline.
