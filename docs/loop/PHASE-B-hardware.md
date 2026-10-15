# Phase B: NEEDS_HARDWARE checklist (run in this order)

Rows live in `tests/evidence/ledger.csv`. Tell me the result of each step and I flip the row to PASS and push the pending tags in order. B3 and B4 will add rows; this list covers B1 and B2 so far.

Prerequisites: Core running with the faster-whisper model cached, Kokoro installed (`REVA_KOKORO_PYTHON`, `REVA_ASSET_ROOT`), app built with the avatar (`cd avatar; npm ci; npm run build`, Git LFS pulled), Ollama running with `OLLAMA_MODELS=F:\AI\Ollama\models`.

1. **Voice loop on the real mic** (`docs/voice/live-voice-windows.md` steps 1 to 7): Voice on; hold the button and say "add twelve dollars for lunch"; hold Ctrl+Space in Notepad and say "make it fifteen"; interrupt a long answer; unplug the mic while talking; mute mic and speaker. Rows: `AR-WIN-004-hardware`, `AR-WIN-010-hardware`, `AR-WIN-005-hardware` (stopwatch video, 300 ms p95), `AR-WIN-015-device-loss`.
2. **Three recorded turns** (budget question, expense that shows the confirm line, barge-in): screen-record each.
3. **Speaker first-audio** (S06 row `S06-first-audio-speaker`): `python tools\voice\kokoro_hardware_demo.py speak --runs 10 --device 20` with `REVA_KOKORO_PYTHON` and `REVA_ASSET_ROOT` set.
4. **STT benchmark** (`docs/voice/measuring-on-your-pc.md`): record 50 sentences, score tiny/base/small. Rows `B1-stt-benchmark`, `AR-VA-021-stt-cer-benchmark`.
5. **Wake word** (same doc): 1 h of non-wake audio and 50 phrases; Porcupine and, once you have a model, openWakeWord. Row `B1-wake-word-eval`. You pick.
6. **One real cloud turn** (`docs/voice/cloud-reasoning.md` steps 1 to 4): store key, ask a question, repeat offline, remove key. Row `B1-cloud-real-turn`.
7. **Avatar** (`docs/avatar/hardware-checklist.md`): 10-minute GPU profile (`B2-gpu-profile`), lip-sync offset on speakers (`B2-lipsync-offset`), a screenshot of each pose on your GPU (`B2-pose-screenshots`).
8. **Older rows still open:** SYNC-1e on the phone, Narrator pass of Finance, screenshots of Home/Finance, AND-1 phone install, the Kokoro speaker confirmation.
