# Wake-word provider selection — corrected finding (Slice 8A-R, Task 4)

Diagnose-only. No wake-word behavior changed by this document or its commit. Corrects the prior "Item C" conclusion (from the 8A follow-up handoff) against the physical log evidence in F2 of the Slice 8A-R spec.

## Step 1 — what is actually constructed, and what selects it

`App.xaml.cs:45-58`:

```csharp
var wakeWordOptions = WakeWordRuntimeOptions.FromEnvironment();
WakeWordProviderDiagnostics.Create(wakeWordOptions).Log();
...
IWakeWordDetector detector = wakeWordOptions.IsEnabled
    ? new PorcupineWakeWordDetector(
        wakeWordOptions.AccessKey,
        wakeWordOptions.KeywordDirectory,
        new RealFileSystemProbe(),
        wakeWordOptions.ModelManifest)
    : new NullWakeWordDetector();
```

Selection is `wakeWordOptions.IsEnabled`, sourced from `WakeWordRuntimeOptions.FromEnvironment()` → `WakeWordRuntimeOptions.Load()` (`WakeWordRuntimeOptions.cs:27-29`):

```csharp
var enabled = environment("REVA_WAKE_WORD_ENABLED") is { } enabledOverride
    ? IsTruthy(enabledOverride)
    : settings.IsEnabled;
```

`settings` comes from `JsonWakeWordSettingsStore.Load()` (`WakeWordLocalSettings.cs:29-55`): reads `<data-dir>/wake-word-settings.json`; **default is `WakeWordLocalSettings.Disabled` (`IsEnabled=false`) whenever that file is absent, malformed, or unreadable.**

## Step 2 — the discrepancy, resolved

Both conclusions were locally correct, for different machines. My earlier "Item C" check confirmed `NullWakeWordDetector` was in use — true, but only because no `wake-word-settings.json` exists on this development machine (re-checked for this report: still absent, `%LOCALAPPDATA%\Reva\wake-word\` directory doesn't exist at all here either). I stated that as an unconditional fact rather than an environment-dependent one — that was the error, not the code inspection itself.

The physical test machine that produced F2's log evidently has `wake-word-settings.json` with `IsEnabled=true` (or `REVA_WAKE_WORD_ENABLED` set) — most likely from the wake-word provisioning tool added in commit `d361832`. Nothing in the code changed between the two checks; the two machines' persisted state differs.

**Separately, and more important: the F2 log line itself is not evidence Porcupine initialized at runtime.** `WakeWordProviderDiagnostics.Create(...).Log()` (`App.xaml.cs:46`) runs **unconditionally on every launch**, before the `IsEnabled` branch that actually selects a detector. Its `porcupine=4.0.2` / `pvrecorder=1.2.13` fields are compile-time constants:

```csharp
// WakeWordProviderDiagnostics.cs:12-13
public const string PinnedPorcupineVersion = "4.0.2";
public const string PinnedPvRecorderVersion = "1.2.13";
```

This line is a build-version banner ("what package versions does this binary reference"), not a runtime-initialization signal. It says nothing about whether a `PorcupineWakeWordDetector` was constructed, whether `StartAsync` ever ran, or whether a microphone was touched. Reading it as "Porcupine initializes on every launch" was reading more into the line than it reports.

## Step 3 — what empty `keyword_version=`/`hey_reva_sha256=` mean

These two fields come from `wakeWordOptions.ModelManifest` (`WakeWordProviderDiagnostics.cs:19,24`), populated from the same settings file. Empty means no keyword-set version or expected hash is registered — consistent with no provisioning having run, same root cause as `IsEnabled=false` in most cases (they're set together by the provisioning tool).

Whether the detector can be **constructed** with an empty manifest and **still armed while unable to detect** depends on `IsEnabled`, which is a separate flag from the manifest's contents:

- If `IsEnabled=false`: `NullWakeWordDetector` is selected. Its `StartAsync` is a no-op returning `Task.CompletedTask` (`NullWakeWordDetector.cs:19-26`) — no engine, no recorder — and `App.xaml.cs:75-78` never calls `EnableAsync` at all in this case. Not armed, correctly.
- If `IsEnabled=true` but the manifest is empty or the phrase's expected hash is missing: `PorcupineWakeWordDetector.StartAsync` (`PorcupineWakeWordDetector.cs:70-87`) calls `WakeWordKeywordResolver.Resolve(...)` first. **Found a real gap here, not currently observed live but present in the code:** `WakeWordKeywordResolver.Resolve` (`WakeWordKeywordResolver.cs:75-83`) only checks a phrase's hash `if (manifest.ExpectedSha256.Count > 0)` — an **entirely empty manifest skips hash verification altogether** rather than failing closed. If the `.ppn` keyword file happens to exist on disk at the expected path with no registered hash for any phrase, resolution *succeeds unverified*, and `StartAsync` proceeds to construct a real Porcupine engine and start `PvRecorder` recording — an unverified keyword file, armed and listening. This is not "armed while deaf" (it would genuinely detect whatever the file matches), but it is armed against an integrity-unverified asset, which is the same failure family the F2 finding was worried about. On this development machine specifically, the keyword directory does not exist at all, so `MissingFile` fires first and this path is not reachable here — but the code-level gap exists independent of this machine's state. Not fixed — diagnose only, per this task's rule. Flagging for whichever slice owns keyword-file integrity (Slice 8B touches this exact resolver).
- If the manifest has *some* hashes but not the requested phrase's: `MissingExpectedHash` fires (`WakeWordKeywordResolver.cs:78-81`) → `WakeWordConfigurationException` → `WakeWordCoordinator.SetUnavailable(...)` (`WakeWordCoordinator.cs:185-189`) → UI state `Unavailable`. Correctly not armed.

So: **can it report armed while unable to detect?** Not via the `IsEnabled=false` path (confirmed no). Via `IsEnabled=true` with a *fully* empty manifest and a present-but-unregistered keyword file, it can become armed with an *unverified* asset — a narrower and different shape than "reports armed while the detector never started," but adjacent to the same concern class the rule about "armed while deaf" exists to prevent.

## Step 4 — microphone acquisition

`PorcupineWakeWordDetector`'s constructor (`PorcupineWakeWordDetector.cs:18-47`) does field assignment only — no engine, no recorder, no microphone touched at construction. The real Porcupine engine and `PvRecorder` are created only inside `StartAsync` (`PorcupineWakeWordDetector.cs:89-124`), and `recorder.Start()` (line 103) is the actual microphone acquisition. `StartAsync` is reached only via `WakeWordCoordinator.StartDetectorAsync`, which is only invoked from `EnableAsync`/`ResumeAfterHoldToTalkAsync`/recovery paths — and in `App.xaml.cs`, `EnableAsync` is called only `if (wakeWordOptions.IsEnabled)` (`App.xaml.cs:75-78`).

On this machine (`IsEnabled=false`): no engine constructed, no `PvRecorder` created, no microphone acquired, nothing capturing. Confirmed by code path — `EnableAsync` is never reached.

On a machine with `IsEnabled=true`: yes, `PvRecorder` acquires and captures from the microphone once `EnableAsync` completes successfully. Not verified live — this environment has wake word disabled.

## Step 5 — CPU cost and contribution to the ~11.4s linger

`WakeWordProviderDiagnostics.Create(...).Log()` (runs on every launch, both branches) is a synchronous string-format operation, no I/O, no native call — negligible, unmeasurable against noise.

Real engine/recorder construction cost was **not measured** — not reachable on this machine (`IsEnabled=false`, no keyword directory present). Cannot report a number without fabricating one.

On the shutdown side: the prior physical-timing instrumentation (Stopwatch added to `MainWindow_Closed`, since reverted) measured `WakeWord.DisposeAsync()` at 2ms end-to-end in this same disabled-wake-word environment. That measurement stands: in this environment, wake-word teardown is not the source of the ~11–30s linger — the linger occurs entirely after `Close()` returns, inside native WinUI/WindowsAppSDK teardown, outside any C#-visible await point. Whether a *live* Porcupine/PvRecorder session's teardown adds materially to that on a machine where it's actually running was not measured and cannot be inferred from this data.

## Corrected baseline for Slice 8B recon 0.4/0.5

- `PorcupineWakeWordDetector` exists, is complete (not stubbed), and the `Porcupine`/`PvRecorder` NuGet packages are referenced in `Reva.Desktop.csproj`.
- `NullWakeWordDetector` is selected whenever `wakeWordOptions.IsEnabled` is false — the default, absent a provisioned `wake-word-settings.json` or `REVA_WAKE_WORD_ENABLED=true`.
- The startup diagnostic log line (`wakeword.provider ...`) is not a reliable signal of runtime detector selection — it fires unconditionally with build-constant version strings. Slice 8B's own recon should read `App.xaml.cs`'s `IsEnabled` branch directly, not infer selection from this log line.
