# Transcription-only voice vertical slice — design

Status: approved (design questions resolved inline with user 2026-08-16).

## Problem

The existing Hold-to-Talk flow (`AssistantViewModel.FinishVoiceInputAsync`) does mic capture -> STT -> auto-send to Core -> auto-TTS-playback, all as one inseparable turn. This slice needs STT-only: capture, transcribe, populate the composer textbox, stop. No auto-send, no TTS.

Readiness is also currently tangled: "Voice Ready"/"Voice Unavailable" is driven purely by mic availability, but a Core-side STT failure (timeout, 503) overwrites the same string, and the generic `SendAsync` timeout path always returns "REVA Core did not respond in time." even for voice requests — producing the reported "Core Connected" + "Voice Unavailable" + wrong timeout message combination.

## Scope

STT only. No changes to TTS invocation sites (there's only one — the voice turn — and this slice removes that call, it does not touch `SynthesizeSpeechAsync`/`PlayAsync`/Chatterbox code itself). No ADK/assistant auto-invoke from voice. No memory changes. Desktop-only — no backend/`reva_core` changes (see Readiness Signal decision below).

## Readiness model (three independent axes)

1. **Core health** — existing `IRevaCoreLifecycle` / `ShellViewModel.IsCoreConnected`, unchanged.
2. **Microphone availability** — existing `IVoiceDevice.VerifyAvailabilityAsync`, unchanged mechanism, but result mapped to the new `VoiceUiState` enum (see below) instead of the old two-string model.
3. **STT endpoint availability** — **derived from Core health**, not probed separately. Core's `speech_to_text_provider` is built unconditionally at lifecycle startup (unlike TTS, which is gated by `tts_enabled`), so "Core connected" already implies "STT provider resolved." This avoids a backend contract change (`HealthStatus` is a versioned shared contract; adding a field means a schema bump with wider blast radius than an "STT only" slice justifies). If the provider is unexpectedly `None` server-side despite Core being healthy, the transcription call itself still returns 503 `voice_unavailable`, which is handled as a runtime `STT Unavailable` result (safety net, not the primary gate).

**TTS availability plays no role in any of this.** No code path in the new readiness logic reads `text_to_speech_provider`, Chatterbox state, or `tts_enabled`.

Hold-to-Talk (`VoiceButton`) is enabled iff: microphone state is `Ready` AND Core is connected. Never gated on TTS.

## UI states

Replace the two loose strings (`VoiceStatusText`, boolean `_isVoiceAvailable`) with an explicit enum surfaced as a computed status string, exact values required by spec:

```
CheckingMicrophone   -> "Checking Microphone"
ReadyToTalk           -> "Ready to Talk"
Listening             -> "Listening"
Transcribing          -> "Transcribing"
TranscriptionReady    -> "Transcription Ready"
PermissionDenied      -> "Permission Denied"
NoMicrophone          -> "No Microphone"
SttUnavailable        -> "STT Unavailable"
TranscriptionFailed   -> "Transcription Failed"
```

`VoiceErrorMessage` carries the human-readable detail (e.g. "Microphone permission is disabled. Enable it in Windows Settings.") separately from the state label, same as today's `VoiceErrorText` TextBlock.

## Flow (new `FinishVoiceInputAsync`)

Pointer press -> `StartVoiceInputAsync`: unchanged mechanics (capture pointer, start recording), status -> `Listening`.

Pointer release/cancel/capture-lost -> `FinishVoiceInputAsync`, all three routed through the same method (already true today) with an `IsMicrophoneActive` guard ensuring stop-once (already true today — verified by existing `if (!IsMicrophoneActive) return;` at entry). Sequence:

1. status -> `Transcribing`
2. stop recording, get WAV bytes
3. **new**: validate WAV — non-empty and duration >= 250ms (decoded from the WAV header the same way `reva_core`'s `_validate_wav_upload` does: `data` chunk byte length / (sample rate * channels * bytes-per-sample)). Under 250ms -> status `TranscriptionFailed`, safe message, return. Do not call Core.
4. `TranscribeSpeechAsync` (own timeout, see below)
5. success -> write `transcription.Text` into `ComposerText` (**and** the live `ComposerBox.Text` from code-behind, same `SyncComposerTextFromTextBox`-style gap as the existing Send path — x:Bind TwoWay only commits on LostFocus, so code-behind must set both), status -> `TranscriptionReady`. **No** `SendMessageCoreAsync` call, **no** `SynthesizeSpeechAsync`/`PlayAsync` call.
6. failure -> map `CoreErrorKind` to `SttUnavailable` (CoreUnavailable/CoreTimeout/503) or `TranscriptionFailed` (other errors), safe message from existing `CoreError.SafeMessage`.

## Capture format

`WindowsVoiceDevice.StartRecordingAsync` currently uses `MediaEncodingProfile.CreateWav(AudioEncodingQuality.High)`, which is 48kHz stereo — not mono/16kHz. Change: build the profile then override `profile.Audio = AudioEncodingProperties.CreatePcm(16000, 1, 16)` (16kHz, mono, 16-bit) before `PrepareLowLagRecordToStorageFileAsync`, so capture is mono 16kHz PCM WAV natively — no post-capture conversion step needed.

## Timeouts

- Readiness probe (`VerifyAvailabilityAsync`) — unchanged, already lightweight (`MediaCapture.InitializeAsync` only, no Core call, no Whisper load).
- Core health poll — unchanged.
- Transcription HTTP call — **new dedicated timeout**, longer than the 10s default used for chat/health (`DesktopConfiguration.RequestTimeout`). Add `DesktopConfiguration.SttRequestTimeout` (default 30s, env override `REVA_DESKTOP_STT_TIMEOUT_SECONDS`). Since one `HttpClient` has one hard `Timeout`, set `HttpClient.Timeout` to the max of the two (30s) and enforce the *shorter* 10s bound for non-voice calls via a per-call linked `CancellationTokenSource` in `RevaCoreClient.SendAsync`; `TranscribeSpeechAsync` uses its own linked CTS at 30s. Timeout failure on the transcription call must produce the voice-specific message ("REVA voice did not respond in time." — already correct for `SendBytesAsync`, currently *wrong* for `SendAsync`'s generic `TaskCanceledException` catch, which the voice call also happens to use; fix that catch to consult `voiceRequest` for its message too, matching the existing `SendBytesAsync`/`InterpretResponseAsync` behavior).
- Cancellation (app shutdown / explicit cancel) must restore `ReadyToTalk` (or the appropriate not-ready state), never leave state stuck in `Listening`/`Transcribing`.

## Permission handling

- `WindowsVoiceDevice` already catches `UnauthorizedAccessException` separately in both `VerifyAvailabilityAsync` and `StartRecordingAsync`, mapping to `VoiceDeviceAvailability.PermissionDenied()`. Change the message text to the required exact string: `"Microphone permission is disabled. Enable it in Windows Settings."`.
- App is unpackaged (`WindowsPackageType=None`, no `Package.appxmanifest` anywhere in the repo — confirmed absent). No manifest capability work needed now; this is purely the OS-level unpackaged consent path, already handled via the `UnauthorizedAccessException` catch + `MicrophoneSettingsButton` deep link to `ms-settings:privacy-microphone` (kept as-is).
- `NoMicrophoneFound` stays a distinct state (`No Microphone`) from `PermissionDenied`.

## Files touched

- `VoiceDeviceAvailability.cs` — message text update, still Ready/PermissionDenied/NoMicrophoneFound/RecordingFailed kinds underneath the new UI enum mapping.
- New `VoiceUiState.cs` (enum) in `Reva.Desktop.State` or `Services`.
- `AssistantViewModel.cs` — readiness wiring (add `IRevaCoreLifecycle` dependency for Core-connected gating), rewritten `FinishVoiceInputAsync` (drop auto-send/auto-speak, add WAV duration validation, new state mapping), `CanStartVoiceInput`/`CanUseVoiceButton` gate on mic + Core.
- `WindowsVoiceDevice.cs` — mono/16kHz `AudioEncodingProperties.CreatePcm` override.
- `RevaCoreClient.cs` — per-call timeout (10s default / 30s voice), fix `SendAsync`'s `TaskCanceledException` catch to use the voice-specific message when `voiceRequest: true`.
- `DesktopConfiguration.cs` — new `SttRequestTimeout` property + env var.
- `MainWindow.xaml` / `.xaml.cs` — no structural change to controls (button/textbox/labels already exist with the right `AutomationId`s); code-behind gets the "push transcription into live `ComposerBox.Text`" step alongside `Assistant.ComposerText`.
- New WAV duration helper (desktop-side, mirrors Core's own header-parsing logic) — small, private to `AssistantViewModel` or a tiny static helper, not a new service.

## Testing

xUnit, existing `AssistantViewModelTests.cs`/`RevaCoreClientTests.cs` pattern (fake `IRevaCoreClient`, fake `IVoiceDevice`, fake `IRevaCoreLifecycle`). Maps directly to the required test list in the task: press begins capture, release/cancel/capture-lost each stop exactly once, duplicate release ignored, empty/under-250ms recording rejected without a Core call, permission-denied message, STT timeout message (voice-specific, not generic Core one), successful transcript populates `ComposerText` and does not call `SendMessageAsync`/`SynthesizeSpeechAsync` (fake spies), TTS-unavailable-fake does not disable `CanStartVoiceInput`, typed chat (`SendMessageAsync`) still works unchanged.

Real-microphone acceptance run (Release build, physical hold-to-talk, spoken phrase) happens after unit tests pass, per the task's required acceptance steps — reported with capture duration, WAV size, STT latency, recognized text, and confirmation no assistant/TTS request fired, before any commit.
