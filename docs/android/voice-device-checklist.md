# Android voice: device checklist (C1)

Run on a physical phone with Android 13 or newer and an on-device speech model installed (Settings > System > Languages > Speech, or the Google app's offline speech), and on one Android 12 phone or emulator for the fallback. Result rows go in `tests/evidence/ledger.csv`; a row flips to PASS only with your result.

Prerequisites: debug APK from `python tools/android/build_apk.py` installed with `adb install -r`; for steps 1 to 8 the phone may be in airplane mode.

| # | Steps | Expected | Row |
|---|---|---|---|
| 1 | Fresh install. Open Talk. Type "hello" and tap Send. | A reply line appears ("I heard you, but I can't answer on the phone yet..."). No permission dialog was shown. | `C1-hw-no-dialog-before-tap` |
| 2 | Tap Speak. | The system microphone dialog appears only now. Choose "Don't allow". Status returns to Ready, a note says it was refused, typing still works. | `C1-hw-deny` |
| 3 | Tap Speak again, choose "Don't allow" a second time (Android 11+ treats this as don't ask again). | The dialog does not appear a third time; Talk shows "The microphone is blocked" and an Open app settings button that opens the app's settings page. | `C1-hw-deny-forever` |
| 4 | Allow the microphone in settings, return, tap Speak, say "what is my balance". | Notification "REVA is listening" with Stop appears; status says Listening, then Thinking; your words show as a You line; the mic indicator goes off right after you stop talking. | `C1-hw-listen-turn` |
| 5 | Tap Speak, wait for it to listen, press Home. | The mic indicator and the notification go away at once; on return Talk shows "Stopped listening because REVA left the screen." | `C1-hw-background` |
| 6 | Tap Speak, then in Settings > Apps > REVA > Permissions turn the microphone off while listening. | Android restarts or stops the app; on reopening, Talk shows the microphone as off and typing works; Speak asks again. | `C1-hw-revoke` |
| 7 | Tap Speak, say nothing. | After a few seconds "I didn't catch that."; mic indicator off. | `C1-hw-no-speech` |
| 8 | Tap Speak, then tap the notification's Stop. | Session ends, indicator off, status Ready. | `C1-hw-notification-stop` |
| 9 | On Android 12 (or an emulator without an on-device model) tap Speak. | No dialog, no listening; Talk says voice input is off and why and that nothing is sent to a server. | `C1-hw-no-on-device` |
| 10 | With an Android profiler or `adb shell dumpsys gfxinfo app.reva.android`, run steps 4 and 8 ten times. | Janky frames under 5%; no main-thread StrictMode violations in `adb logcat -s StrictMode` during voice use. | `AND-018-jank-hardware` |
| 11 | Run steps 4 and 8 ten times and look at Settings > Apps > REVA > Memory, or `adb shell dumpsys meminfo app.reva.android`. | Memory does not climb steadily across sessions. | `C1-hw-no-leak` |
