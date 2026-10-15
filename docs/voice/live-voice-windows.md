# Live voice on Windows (B1b)

The Talk page has a **Live voice** panel. It is separate from the older "Hold to Talk" button, which
still works; both share the microphone arbiter, so only one of them (or the wake word) can hold the
microphone at a time.

## How it behaves

- **Voice** switch: creates a Core voice session and installs the global hotkey. Nothing is recorded yet and
  the microphone is closed. Switching it off closes the session, the hotkey and the microphone.
- **Hold to talk**: the button, the keyboard (Space or Enter on the focused button) or **Ctrl+Space** from any
  app. The microphone opens when you press and closes shortly after you release. The green dot and the
  words "Listening…" show only while the device is really open.
- **Mute mic** never opens the microphone and cancels a running utterance. **Mute speaker** skips playback
  (the reply text is still shown) and still tells Core the reply finished. **Stop speaking** cuts the reply
  and interrupts the turn.
- Pressing the hotkey or the button while REVA is speaking cuts the sound at once on this PC, then
  interrupts the turn in Core.
- If the microphone is unplugged or Windows takes it away, the loop goes back to Ready and says so.
- The hotkey ignores keys that other programs inject, so a script cannot open the microphone for you.
- Audio goes only to Core on `127.0.0.1`. Nothing is written to disk by the app.

Settings used: microphone choice (default microphone unless you pick one). The speech model is the Core
setting `stt_model` (default `Systran/faster-whisper-small`, picked properly by the B1 STT benchmark).

## NEEDS_HARDWARE: run in this order

Prerequisites: Core running with STT and the Kokoro voice available (`REVA_KOKORO_PYTHON`, `REVA_ASSET_ROOT`,
the faster-whisper model cached), the app started, speakers on.

1. Switch **Voice** on. Expect "Hold Ctrl+Space or the button to talk." and a grey dot.
2. Hold the **Hold to talk** button and say "add twelve dollars for lunch", then release. Expect a green dot
   and the Windows microphone icon while held, and both gone after you release. Then "You: add twelve dollars for
   lunch", "REVA: Add $12.00 for lunch? Say yes to confirm." and the reply spoken.
3. Click into Notepad. Hold **Ctrl+Space**, say "make it fifteen", release. Expect no space typed in Notepad,
   "Changed to $15.00 for lunch." spoken.
4. While REVA is speaking a long reply (ask "tell me about the weather"), press the hotkey. Expect the sound to stop
   at once. Record how long it took (stopwatch video is enough); the budget is 300 ms p95.
5. Hold the hotkey and unplug the USB microphone. Expect "The microphone was disconnected." and no crash.
   Plug it back in and talk again.
6. Turn **Mute mic** on: the hotkey must not open the microphone. Turn **Mute speaker** on: you get text only.
7. Tell me the result of each step. I will flip the ledger rows (`AR-WIN-004-hardware`, `AR-WIN-010-hardware`,
   `AR-WIN-005-hardware`, `AR-WIN-015-device-loss`) from NEEDS_HARDWARE to PASS.
