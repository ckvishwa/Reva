# Wake-word slice — multi-phrase — design (BLOCKED, not started)

> **Status: spec captured, implementation blocked.** Supersedes the single-phrase "Hey Reva" spec. Do not start this slice until:
>
> 1. The Windows app-command routing slice exists, is complete, and is proven. Confirmed with user 2026-08-17: it does not exist anywhere in this repo yet. Do not merge this slice with that one when it happens.
> 2. The transcription-only voice slice is fully closed out (its Task 9 physical-microphone acceptance is still pending). This slice is independent scope and does not depend on Task 9 *passing*, but no new voice-path code lands until that slice's commit history is closed.
>
> Everything below is design, not permission to build.

**Change from the previous spec:** one wake phrase became four. That is not a four-line diff — a wake-word system's false-accept rate scales with the number of armed phrases, and two of the requested phrases are materially riskier than "Hey Reva". The phrase-set design section below is the part of this document that actually matters.

---

## Goal

While REVA Desktop is running, the user can enable local wake-word mode. Saying any *enabled* wake phrase activates speech capture without touching the mouse. The following speech is transcribed into `ComposerText` and is neither auto-sent nor executed.

---

## Wake phrase set

| # | Spoken phrase | Keyword slug | Syllables | Default | Default sensitivity | Risk |
|---|---|---|---|---|---|---|
| 1 | "Hey Reva" | `hey-reva` | 3 | **On** | 0.55 | Low — the reference phrase |
| 2 | "You up Reva" | `you-up-reva` | 4 | Off | 0.45 | Medium — leading function words are weak; "Reva" carries the detection |
| 3 | "Daddy's home" | `daddys-home` | 3 | Off | 0.45 | Medium — distinctive phonetics, but it is a sentence people actually say |
| 4 | "Wake up" | `wake-up` | 2 | Off | **0.30** | **High — see below** |

### Phrase design rules

**Every phrase is off by default except "Hey Reva".** Privacy defaults do not get diluted because the phrase list got longer. First launch arms nothing at all (wake word itself is off); first *enable* arms phrase 1 only.

**"Wake up" should probably not ship.** Two syllables, both extremely common, and it appears inside ordinary sentences ("I need to wake up earlier", "wake up call", and near-misses like "make up", "wake her up"). Porcupine's false-accept rate is roughly a function of phrase length and phonetic distinctiveness; a 2-syllable common phrase is the worst case on both axes. Options, in order of preference:

1. Drop it.
2. Ship it disabled, at sensitivity ≤ 0.30, with a settings-page warning naming the trade-off, and require it to pass the false-activation acceptance gate *on its own* before it can be enabled.
3. Replace it with "Reva wake up" (4 syllables, anchored by the name) — same intent, far better behavior.

Option 3 is the recommendation. The decision is the user's, but it must be made explicitly and recorded here before implementation, not discovered during acceptance.

**The false-accept budget is shared, not per-phrase.** The acceptance target is ≤ 1 false activation per hour *for the armed set*. With four phrases armed, each phrase's budget is ~0.25/hour. Measuring each phrase alone and declaring victory is the mistake this note exists to prevent — the aggregate run (all enabled phrases armed simultaneously) is the gate.

**Apostrophes and punctuation don't survive training.** Picovoice Console takes lowercase words: train `daddys home`, not `Daddy's home`. Keep a display string (what the settings UI shows) separate from the training string (what produced the `.ppn`) so the two can never drift.

**Phrase identity is metadata, not behavior.** The detector reports *which* phrase fired, and that identity is logged as a fixed enum and shown in metrics. It does **not** change what happens next: same chime, same capture window, same composer population, same no-auto-send. Per-phrase behavior ("daddy's home" → run a routine) is app-command routing, which is the blocking slice. Building it here would fuse two slices that were deliberately separated.

---

## Required flow

1. User explicitly enables Wake Word, with at least one phrase enabled.
2. UI displays **Wake Word Armed** with a persistent microphone indicator listing which phrases are live.
3. The local detector continuously receives 16kHz mono PCM frames.
4. No STT call, no recording file, and no Assistant call occurs before detection.
5. Any enabled phrase is detected. The detector reports the phrase identity.
6. Play a short local activation chime — a bundled audio asset, never TTS.
7. State becomes **Listening**.
8. Capture the speech following the wake phrase.
9. Stop after 800ms of trailing silence, or at an 8-second hard maximum, whichever comes first.
10. Submit the captured audio through the existing STT path (`IRevaCoreClient.TranscribeSpeechAsync`, the same 250ms floor and the same WAV validation as the transcription slice).
11. Populate the existing composer, preserving any existing draft (append, don't overwrite — same rule as the transcription slice).
12. Do not auto-send. Do not execute local commands.
13. Return to **Wake Word Armed** after a two-second cooldown.

Steps 10 and 11 are *reuse*, not reimplementation. If this slice ends up with its own transcription or composer-population code, the design has gone wrong.

---

## Provider design

```csharp
public interface IWakeWordDetector : IAsyncDisposable
{
    bool IsRunning { get; }
    event EventHandler<WakeWordDetection>? Detected;
    Task StartAsync(WakeWordConfiguration configuration, CancellationToken cancellationToken = default);
    Task StopAsync(CancellationToken cancellationToken = default);
    Task SuspendAsync(CancellationToken cancellationToken = default);   // Hold-to-Talk takes the mic
    Task ResumeAsync(CancellationToken cancellationToken = default);
}

public sealed record WakeWordDetection(WakePhrase Phrase, DateTimeOffset DetectedAtUtc);

public enum WakePhrase { HeyReva, YouUpReva, DaddysHome, WakeUp }

public sealed record WakePhraseSetting(WakePhrase Phrase, bool Enabled, float Sensitivity);

public sealed record WakeWordConfiguration(IReadOnlyList<WakePhraseSetting> Phrases);
```

- **First provider: Porcupine .NET for Windows.** All provider-specific code sits behind `IWakeWordDetector`; nothing Picovoice-shaped appears in `AssistantViewModel`.
- **One detector instance, N keywords.** Porcupine's `FromKeywordPaths(accessKey, keywordPaths, modelPath, sensitivities)` takes an array of `.ppn` paths and per-keyword sensitivities, and `Process(short[] pcm)` returns the *index* of the detected keyword (or -1). Map that index back to `WakePhrase` through the same ordered list used to build the instance. Do **not** instantiate one detector per phrase — that multiplies CPU and creates four components racing for the same audio frames.
- **Reconfiguration means rebuild.** Enabling, disabling, or retuning a phrase disposes the instance and constructs a new one from the current enabled set. Detector construction is cheap relative to how rarely settings change; live mutation is not supported by the library and inventing it invites frame-boundary bugs.
- **Frame discipline.** Porcupine requires exactly `FrameLength` samples of 16-bit mono PCM at `SampleRate` per `Process` call. Buffer and slice; never pass partial frames. This is the same 16kHz mono format the capture path already produces after the transcription slice's Task 5, which is the reason those two decisions belong to the same lineage.
- **Keyword assets are shipped, never fetched.** `.ppn` files live under a known local directory (`%LOCALAPPDATA%\REVA\wake-word\keywords\`), placed there by an explicit setup step. Nothing downloads a model at runtime. A missing or unreadable `.ppn` for an enabled phrase is a **Wake Word Error** state naming the phrase, not a silent skip.
- **AccessKey** comes from local environment/configuration (`REVA_PICOVOICE_ACCESS_KEY`). Never committed, never logged, never included in an error message or a state string. On a missing/invalid key: **Wake Word Error**, with a safe message that says a key is required and does not echo any part of it.
- **Custom keyword licensing is an open item.** Custom `.ppn` files are generated in Picovoice Console and are tied to platform and account terms. Confirm before implementation that the free tier permits the four custom keywords for this use, and that the generated files don't carry an expiry that would silently brick wake-word mode months later. Record the finding here.

---

## Endpointing (steps 8-9)

The 800ms-silence rule needs a voice-activity decision, and that is a real subsystem, not a constant.

- **Preferred:** an energy/RMS threshold with hysteresis over the same 16kHz frames — no new dependency, fully local, easy to unit-test with synthetic PCM.
- **Alternative:** Picovoice Cobra VAD. Better accuracy, but it is a second licensed component with its own key terms. Only take it if the RMS approach demonstrably fails acceptance.
- The 8-second maximum is a hard stop enforced by a timer independent of the VAD, so a stuck-open threshold can never hold the microphone indefinitely.
- Trailing silence is *trimmed* from the submitted audio but the 250ms minimum still applies: a wake phrase followed by nothing must fail the same way a too-short hold does, with the same safe message.

---

## Required states

**Wake Word Off, Starting, Armed, Detected, Listening, Transcribing, Cooldown, Microphone Unavailable, STT Unavailable, Wake Word Error.**

Ten states, unchanged from the previous spec — adding phrases must not add states. Notes:

- **Detected** is brief (chime + transition) but must exist as its own state so the chime can't overlap capture.
- **STT Unavailable** covers Core disconnected, exactly as in the transcription slice. The same rule applies: the displayed state must never claim readiness while the feature is non-functional. If Core is down, wake-word mode reports **STT Unavailable** while armed — or, preferably, refuses to arm at all and says so.
- **Wake Word Error** carries a safe message identifying the *category* (missing key, missing keyword file, detector init failure) and, where relevant, the phrase — never the key, never PCM, never a stack trace in the UI.
- Every state transition is logged as a fixed identifier (`wakeword.state=Armed`, `wakeword.detected phrase=HeyReva`). Phrase identity is a fixed enum member and is safe to log; nothing else from the audio path is.

---

## Microphone ownership

One component owns capture at a time. This is the single largest source of latent bugs in this slice.

- An explicit arbiter owns the `MediaCapture`/audio-input handle. Wake-word detection and Hold-to-Talk both request it; neither constructs its own.
- Hold-to-Talk **suspends** detection (`SuspendAsync`), takes the microphone, and detection **resumes** on completion — including on the cancel, capture-lost, and error paths. A failed Hold-to-Talk turn that leaves wake-word permanently deaf is the specific failure mode to test for.
- Wake detection cannot re-activate while in Detected, Listening, Transcribing, or Cooldown. Duplicate detections in that window are dropped, counted, and not acted on.
- Windows lock, sleep, session switch, and audio-device change all stop or safely suspend detection, and it resumes only when the device is genuinely available again — not optimistically.
- App shutdown stops the detector and releases the microphone deterministically, with no orphaned handles. Given the REVA history with orphaned `powershell.exe` processes during the Voice V1 close-out, this gets a real PID/handle check in acceptance, not an assumption.

---

## Privacy and safety

- Wake word is **off by default** on first launch; phrases 2-4 are off by default even after wake word is enabled.
- A permanent, visible indicator whenever the microphone is armed — visible without opening settings, and showing which phrases are live.
- All wake-word audio is processed locally. Nothing leaves the machine before a detection.
- Pre-wake audio is never written to disk. The rolling detection buffer is in memory only and is overwritten continuously.
- Post-wake captured audio follows the transcription slice's temp-file discipline: written only if the capture path requires a file, deleted in a `finally` on every path including cancellation and error.
- Never log PCM, transcripts, confidence values, or per-frame data. Fixed operational metrics only.
- Persist only: wake-word enabled/disabled, per-phrase enabled/disabled, per-phrase sensitivity. No audio, no history of what was heard.
- An immediate **Wake Word Off** control that takes effect without confirmation and releases the microphone synchronously.
- **Wake-word detection never executes Windows actions.** It populates a text box. That boundary is the reason app-command routing is a separate, blocking slice.

---

## Required tests

Carried over from the previous spec: disabled by default; enable starts detector once; disable stops detector and releases microphone; no STT before detection; detection starts post-wake capture; duplicate detection ignored; silence stops capture; maximum duration stops capture; transcript populates composer; transcript is not auto-sent; command is not auto-executed; Hold-to-Talk suspends and resumes detector; Core disconnect maps to STT unavailable; microphone failure exposes a safe state; cancellation releases all microphone resources; app shutdown stops detector; no audio files remain after the turn.

Added for the multi-phrase design:

- Only enabled phrases are passed to the detector — a disabled phrase's `.ppn` is never loaded.
- Enabling a second phrase rebuilds the detector exactly once, and the old instance is disposed.
- The reported `WakePhrase` matches the keyword index that fired, for every phrase in the set (index-mapping regression — an off-by-one here silently mislabels every detection).
- Detection of any enabled phrase produces byte-identical downstream behavior: same chime, same capture window, same composer population, same absence of auto-send.
- A missing `.ppn` for one enabled phrase yields Wake Word Error naming that phrase, and does not arm the remaining phrases in a half-broken state.
- A missing or invalid AccessKey yields Wake Word Error, and the safe message contains no fragment of the key.
- Per-phrase sensitivity reaches the provider in the same order as the keyword paths (paired-array regression — mismatched ordering silently applies the wrong sensitivity to every phrase).
- Detections arriving during Detected/Listening/Transcribing/Cooldown are dropped and counted, for each phrase.
- A Hold-to-Talk turn that *fails* still resumes detection.
- Composer draft preservation: a wake-word transcript appends to existing composer text rather than replacing it.
- Empty transcript from a wake-triggered capture is a failure state, not a silent success.

---

## Real acceptance

Automated tests cannot establish that a wake word works. These are manual and must be run on the target machine, in the room it will actually be used in.

**Recognition, per enabled phrase:**
- 20 deliberate activations in the user's normal speaking voice and accent.
- ≥ 18/20 must activate.
- Run at ~1 metre and again at ~3 metres; record both rates separately. A phrase that passes at 1m and collapses at 3m is a sensitivity-tuning finding, not a pass.
- Activation within 500ms of the phrase ending.

**False activations — the aggregate gate:**
- All enabled phrases armed simultaneously.
- ≥ 1 hour of ordinary speech, music, video, and calls.
- ≤ 1 false activation per hour **for the set**.
- Run a second hour with only the high-risk phrases armed if any of phrases 2-4 ship, to attribute any failures.

**Adversarial near-miss set** (say each 5 times; each should produce zero activations):

| Target phrase | Near misses |
|---|---|
| Hey Reva | "hey Rita", "hey Reba", "hey Ava", "hey there" |
| You up Reva | "you up?", "your uber", "you okay Reva" (this one *may* fire — record it) |
| Daddy's home | "dad is home", "daddy's phone", "that is home", "daddy's not home" |
| Wake up | "wake up early", "make up", "she woke up", "wake up call", "break up" |

"Daddy's not home" firing the detector is the failure worth watching for — Porcupine matches the phrase, not the sentence's polarity, and this slice's own privacy story depends on it not activating during ordinary household conversation.

**Resource and hygiene:**
- Wake-word processing averages < 5% CPU with the full enabled set armed. Measure with all phrases on, not one.
- No microphone handle or child process survives app shutdown (PID/handle diff, per the Voice V1 precedent).
- No audio files remain on disk after a completed turn or an aborted one.

**Behavioral confirmation:**
- The spoken command remains editable in the composer.
- No Assistant (`/v1/messages`), no TTS (`/v1/voice/speech`), and no Windows action occurs before the user presses Send — cross-checked against `reva_core`'s audit log for the run's correlation window.

---

## Implementation outline (do not start)

Ordered for whenever the blockers clear. Each is a task, TDD-shaped, in the same style as the transcription slice.

1. `WakePhrase` / `WakePhraseSetting` / `WakeWordConfiguration` / `WakeWordUiState` types with exact display strings.
2. Keyword asset resolution + AccessKey configuration, with the error states for missing key and missing `.ppn`.
3. `IWakeWordDetector` and a `FakeWakeWordDetector` seam (everything downstream is testable without a microphone or a Picovoice key).
4. The microphone-ownership arbiter, and Hold-to-Talk suspend/resume through it — including the failure paths.
5. Endpointing (RMS + hysteresis + hard 8s cap) against synthetic PCM.
6. `PorcupineWakeWordDetector`: single instance, N keywords, index→phrase mapping, sensitivity pairing, rebuild-on-config-change.
7. ViewModel wiring: states, indicator, cooldown, reuse of the existing STT + composer path.
8. Settings UI: master toggle, per-phrase toggles, per-phrase sensitivity, the warning on any 2-syllable phrase.
9. Real acceptance run per the section above.

---

## Open decisions — resolve before implementation

1. **"Wake up": drop, ship disabled at 0.30, or replace with "Reva wake up"?** Recommendation: replace. Needs an explicit answer.
2. **Custom keyword licensing** — does the Picovoice tier in use permit four custom Windows `.ppn` files, and do they expire? Verify and record.
3. **Cobra VAD or hand-rolled RMS** for endpointing? Default to RMS; revisit only if acceptance fails on it.
4. **Does wake-word mode arm at all while Core is disconnected?** Refusing to arm is more honest than arming into a guaranteed STT failure, but it means the feature appears broken when Core is merely slow to start. Recommendation: arm, but display STT Unavailable, and suppress the chime so the user isn't told a capture began that cannot complete.
5. **Chime asset** — bundled file, format, and volume relative to system audio. Must not route through TTS or the voice host.

---

## Reconciliation with the verified app-command routing architecture (2026-08-17)

Cross-checked against `docs/superpowers/specs/2026-08-17-windows-app-command-routing-design.md` and `docs/superpowers/plans/2026-08-17-windows-app-command-routing-v1.md` (design + plan both written and self-reviewed 2026-08-17; app-command routing itself is not yet implemented).

**No code-level coupling exists, and none is needed.** `CommandRouter` is invoked from exactly one place: `AssistantViewModel.SendMessageCoreAsync`, on whatever text is in `ComposerText` at the moment the user presses Send (or hits Enter) — it has no awareness of *how* that text got there. Typed input, a Hold-to-Talk transcript, and a future wake-word transcript all populate `ComposerText` through the same mechanism (direct assignment / append, per the transcription slice's draft-preservation rule) and are therefore all subject to command routing identically, automatically, the moment app-command routing ships — with zero wake-word-specific integration code required. This confirms this spec's own §Required flow steps 10-11 ("reuse, not reimplementation") and its Privacy/Microphone-ownership statement that wake-word "never executes Windows actions... it populates a text box" are both architecturally accurate as written, not just aspirational.

**The STT-path reuse claim is verified against the actual current code**, not just asserted: `AssistantViewModel.FinishVoiceInputAsync` (the code this slice's step 10-11 reuses) calls `WavAudio.TryGetDurationMs` against a `MinimumRecordingMs = 250` constant before any Core call, and on success does `ComposerText = string.IsNullOrWhiteSpace(ComposerText) ? text : $"{ComposerText.TrimEnd()} {text}";` — exactly the 250ms floor and append-don't-overwrite behavior this spec's flow section and required-tests section describe. Wake-word's own captured-speech submission should call the same `IRevaCoreClient.TranscribeSpeechAsync` path and land through the same composer-append logic, not a parallel copy.

**Why the sequencing dependency is still real, even without code coupling.** Both slices independently add a new voice-triggered local-execution surface. App-command routing is the first and narrower one (deterministic text matching, a 7-entry allowlist, a confirm/cancel gate) and is the one already scoped in detail; proving it end-to-end first — including its physical acceptance run — validates the "local automation surface can be built safely in this codebase" pattern once before a second, more complex surface (a continuously-listening microphone detector with its own provider dependency, licensing question, and endpointing subsystem) is layered on top of the same Send pipeline. This is a risk-sequencing decision, not an architectural requirement discovered during reconciliation — recorded here because the reconciliation step specifically went looking for a hidden coupling and found none; the dependency user set stands as originally instructed.

**Formal gate for the plan below:** the wake-word implementation plan's Task 0 does not begin until the app-command routing plan (`docs/superpowers/plans/2026-08-17-windows-app-command-routing-v1.md`) has all tasks reviewed clean and its Task 6 physical acceptance run has passed and been reported back — the same bar the transcription-only voice slice was held to before this slice's own spec was allowed to be written.