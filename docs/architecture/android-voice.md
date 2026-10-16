# Android voice (C1)

Status: C1a shipped the voice session, the permission flow, the on-device recognizer rule, the microphone service and the Talk screen. C1b adds speech out, the avatar and the mood engine. C1c ports the registry, rule fast path and `authorize()`.

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

## Speech out, avatar, mood (C1b)

| File | What it does |
|---|---|
| `voice/AndroidTtsSpeaker.kt` | Android TTS writes the sentence to a WAV file (offline voices only), `AudioTrack` plays it, and the loudness of what the track has actually played is reported about 60 times a second |
| `voice/Playback.kt` | WAV decoding and the level meter (same 60 windows a second as the Windows meter) |
| `avatar/AvatarProtocol.kt` | The only way to build a host-to-page message; invalid input returns null. Golden messages in `avatar/test/fixtures/host-messages.json` are validated by the page tests and compared by `AvatarTest` |
| `avatar/AvatarDriver.kt` | Maps the session's true state to avatar messages: listening only while the microphone is open, mouth only while speaking for the current epoch |
| `avatar/AvatarHostBridge.kt` | The page's only way back: `ready` or `error`, parsed strictly, everything else ignored |
| `ui/talk/AvatarView.kt` | WebView serving the page and model from the APK through `WebViewAssetLoader`; every other request is blocked; no file access; destroyed when Talk is left |
| `mood/MoodEngine.kt`, `MoodFlags.kt`, `EngineMood.kt` | The mood engine ported from Python, reading the same `contracts/mood-rules.v1.json` (copied into the APK at build time). `tests/fixtures/mood-cases.json` (written by the Python engine) is replayed by `MoodEngineTest` |

Gradle copies `avatar/dist` and the mood rules into the APK (`stageRevaAssets`). Build the page first (`cd avatar; npm ci; npm run build`); without it the APK still runs and Talk shows no avatar. In debug builds WebView DevTools is on (`chrome://inspect`).

Checked on an API 36 emulator (not a phone): the page loads offline from the APK and draws; Speak shows the system dialog only after the tap; the second refusal shows the blocked card; after granting, the voice service runs with the OS microphone indicator and Home stops it. The emulator run found two real bugs (a zero-height canvas inside the WebView, and avatar messages lost before the page loaded), both fixed.

Speech is only spoken for a voice turn, not for typed text. If the phone has no offline voice the reply stays on screen.

## Same policy as the PC (C1c)

| File | What it does |
|---|---|
| `policy/Registry.kt` | Loads the same `contracts/capability-registry.v2.json` (copied into the APK); refuses forbidden capabilities and unsupported schema keywords; the strict schema validator |
| `policy/Authorize.kt` | `authorize()` with the same nine checks in the same order, `args_hash` over the same canonical JSON |
| `language/Rules.kt` | The rule fast path: refusals, stop/repeat/undo, today, spending, remember, recall. The app open/close rules are Windows-only |
| `language/Outcomes.kt` | The refusal templates |
| `language/PolicyReplies.kt` | Rules, then `authorize()`, then a template: refusals say no, anything the phone cannot do yet says nothing was changed |

`tests/fixtures/authorize-cases.json` (1006 cases) and `rules-cases.json` are written by `tools/ci/make_policy_cases.py` from the Python code and replayed by `AuthorizeParityTest` and `RulesTest`; `tests/unit/test_policy_cases_fixture.py` fails when Python changes without the fixtures. Known edges of the port: float formatting in `args_hash` matches Python for ordinary numbers (whole numbers keep `.0`) but not for exponent forms such as `1e-07`; ISO date-time validation accepts the common spellings, not every one `fromisoformat` does.

## What is not here yet

- Nothing answers a question: `UnavailableReplies` says so. The PC route is C2, the local brain C3.
- Streaming Kokoro audio from the PC needs a gateway route that does not exist; it is part of C2.
- Mic-level jank and battery profiling need a device (see `docs/android/voice-device-checklist.md`).
