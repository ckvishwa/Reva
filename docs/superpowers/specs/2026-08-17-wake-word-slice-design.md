# Wake-word slice — "Hey Reva" — design (BLOCKED, not started)

Status: **spec captured, implementation blocked.** Do not start this slice until the Windows app-command routing slice exists, is complete, and is proven. Confirmed with user 2026-08-17: app-command routing does not exist anywhere in this repo yet — it is a separate, not-yet-scoped slice that must be built and proven first. Do not merge this implementation with that slice when it happens.

Also blocked behind: the transcription-only voice slice's Task 9 (physical microphone acceptance) is still pending user confirmation as of this spec's capture. This wake-word slice is unrelated new scope and doesn't depend on Task 9 passing, but no new voice-path code should land until that slice is fully closed out (commit history stays clean per-slice).

## Goal

While REVA Desktop is running, the user can enable local wake-word mode. Saying "Hey Reva" activates speech capture without touching the mouse. The following speech is transcribed into `ComposerText` but is not automatically sent or executed.

## Required flow

1. User explicitly enables "Wake Word".
2. UI displays "Wake Word Armed" with a persistent microphone indicator.
3. Local detector continuously receives 16kHz mono PCM frames.
4. No STT, recording file, or Assistant call occurs before detection.
5. Detect "Hey Reva".
6. Play a short local activation chime — never TTS.
7. Change state to "Listening".
8. Capture speech following the wake word.
9. Stop after 800ms of silence or an 8-second maximum.
10. Submit captured speech through the existing STT path.
11. Populate the existing composer.
12. Do not auto-send and do not execute local commands.
13. Return to "Wake Word Armed" after a two-second cooldown.

## Provider design

- Add `IWakeWordDetector`.
- First provider: Porcupine .NET for Windows.
- Keep all provider-specific code behind the interface.
- Read the Picovoice AccessKey from local environment/configuration.
- Never commit or log the AccessKey.
- Never download models at runtime without explicit setup.
- Never put provider logic inside `AssistantViewModel`.

## Required states

Wake Word Off, Starting, Armed, Detected, Listening, Transcribing, Cooldown, Microphone Unavailable, STT Unavailable, Wake Word Error.

## Privacy and safety

- Wake word is OFF by default on first launch.
- Show a permanent visible indicator whenever the microphone is armed.
- Process wake-word audio locally.
- Do not save pre-wake audio to disk.
- Do not log PCM, transcript, or confidence-frame data.
- Store only enabled/disabled preference and fixed operational metrics.
- Stop listening when REVA exits.
- Stop or safely suspend during Windows lock/sleep.
- Provide an immediate "Wake Word Off" control.
- Wake-word detection must never execute Windows actions directly.

## Microphone ownership

- Only one component may own microphone capture.
- Hold-to-Talk temporarily suspends wake-word detection.
- After Hold-to-Talk finishes, wake-word detection resumes.
- Wake detection cannot activate twice while recording/transcribing/cooldown.
- Do not create competing `MediaCapture` instances.

## Required tests

disabled by default; enable starts detector once; disable stops detector and releases microphone; no STT before detection; detection starts post-wake capture; duplicate detection ignored; silence stops capture; maximum duration stops capture; transcript populates composer; transcript is not auto-sent; command is not auto-executed; Hold-to-Talk suspends and resumes detector; Core disconnect maps to STT unavailable; microphone failure exposes a safe state; cancellation releases all microphone resources; app shutdown stops detector; no audio files remain after the turn.

## Real acceptance

- Test 20 deliberate "Hey Reva" activations using Vishva's normal accent.
- At least 18/20 must activate.
- Test at approximately 1 metre and 3 metres.
- Run ordinary speech/music for at least one hour.
- Target no more than one false activation per hour.
- Activation should occur in under 500ms after the phrase ends.
- Wake-word processing should average under 5% CPU.
- Confirm the spoken command remains editable in the composer.
- Confirm no Assistant, Windows action, or TTS call occurs before Send.

## Open dependency

This slice reuses the existing STT path (composer population, no-auto-send, mic-ownership discipline) built in the transcription-only voice slice (`docs/superpowers/plans/2026-08-16-transcription-only-voice-slice.md`). It should integrate with — not duplicate — that slice's `IVoiceDevice`/`AssistantViewModel` seams once both this slice and the app-command routing slice are ready to be scoped in detail (brainstorming → design → plan, same process as the transcription-only slice).
