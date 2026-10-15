# Android voice (C1)

Status: C1a (this file's first slice) ships the voice session, the permission flow, the on-device recognizer rule, the microphone service and the Talk screen. Speech out and the avatar are C1b; the shared registry, rules and `authorize()` port is C1c.

## Parts (`android/app/src/main/java/app/reva/voice/`)

| File | What it does |
|---|---|
| `VoiceSession.kt` | Session states and legal moves, identical to the Core's table; a turn epoch that makes late results stale |
| `VoicePorts.kt` | Interfaces: permission gate, recognizer, reply source, speaker, service launcher; the on-device rule (`RecognizerPolicy`) |
| `VoiceController.kt` | The whole session as a plain Kotlin class: tap, permission, recognizer, reply, release. Fully JVM-tested with fakes |
| `AndroidSpeech.kt` | The Android pieces: permission gate, `createOnDeviceSpeechRecognizer`, availability check |
| `VoiceService.kt` | Foreground service of type `microphone`, started only from the mic tap, with a Stop action |
| `Replies.kt` | The reply source until C2 (paired PC) and C3 (local brain): says it cannot answer yet |

## Rules the code and tests enforce

- The microphone dialog is shown only after a tap on the mic button (AR-AND-001). Typing never depends on the permission, the recognizer or the service.
- Deny, deny-forever (no second dialog, a button to the app settings) and revoke while listening all end in Idle with the recognizer released.
- Voice input uses `createOnDeviceSpeechRecognizer` only (AR-AND-003). Android 13 or newer is required to *check* that it exists; on Android 12 and when no on-device model is installed, voice is off, the screen says why, and nothing is sent to a server.
- The microphone closes the moment the utterance is final, before the reply is made. `micOpen` is true exactly while the recognizer is open, and is what the avatar's listening pose will follow.
- Leaving the screen while a session runs ends it (no microphone behind the screen). Coming back re-reads the permission.
- Every result carries the epoch of the turn that asked for it. After an interrupt, stop or new typed sentence the old results (a transcript, a reply, a finished sentence) are dropped (`VoiceControllerTest`).
- Recognizer, service and speaker are released on every way a session can end (AR-AND-004).
- The shared transition table is `tests/fixtures/session-transitions.json`, checked by `tests/unit/test_session_transitions_fixture.py` and `VoiceSessionTest.kt`.

## Permissions added

`RECORD_AUDIO`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MICROPHONE`. `POST_NOTIFICATIONS` is not requested: Android still lists a running foreground service in its task manager and shows the microphone indicator. `ManifestTest` pins the exact set, the private microphone service, no boot receiver, no `QUERY_ALL_PACKAGES` and no accessibility service.

## What is not here yet

- Replies are not spoken and no avatar is shown (C1b).
- Nothing answers a question: `UnavailableReplies` says so. The PC route is C2, the local brain C3.
- Streaming Kokoro audio from the PC needs a gateway route that does not exist; it is part of C2.
- Mic-level jank and battery profiling need a device (see `docs/android/voice-device-checklist.md`).
