# C1b Android speech and avatar review

Reviewed on the C1b integration branch rebased by cherry-pick onto merged C1a (`origin/main` `f1ff301`). The Android TTS path synthesizes to a cache WAV, decodes PCM16, and reports RMS only for windows reached by `AudioTrack.playbackHeadPosition`. `VoiceController` rejects stale epochs, cancels the turn and stops audio on interruption. The WebView serves packaged assets through `WebViewAssetLoader`, blocks network loads and navigation, and has a narrow ready/error JavaScript bridge. The generated mood fixture compares Android behavior with Python's shared rules.

Finding fixed: the JavaScript bridge runs on a WebView worker thread. Its callback changed Compose state, risking thread violations. The bridge now dispatches valid reports to the Android main looper; blocked main-frame resource errors do the same. `AvatarBridgeThreadTest` failed on an API 36 emulator before the fix (`the bridge delivered off the UI thread`) and passed afterward.

Fresh local checks after the fix: Android JVM `testDebugUnitTest` passed (206 tests, 0 failures/skips); targeted instrumented bridge test passed (1); avatar unit 36/36 and browser 9/9 passed; mood fixture Python 2/2 and contracts 9 schemas passed. The physical phone speech, interruption, airplane-mode WebView, leakage and performance checks remain `NEEDS_HARDWARE` under `docs/android/voice-device-checklist.md`. Emulator results do not close those rows.

The optional paired-PC Kokoro playback belongs to the later paired request route; C1b speaks only with an installed offline Android TTS voice. No claim of physical speaker latency or battery performance is made here.
