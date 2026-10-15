# Voice turn pipeline (B1a)

`reva_core/session/pipeline.py` drives one `VoiceSession`: PCM in, spoken reply out.

Client contract (WebSocket `/v1/voice/sessions/{id}/events`, Bearer header):

| Direction | Message |
|---|---|
| client -> Core, binary | 16 kHz mono 16-bit LE PCM, 1 to 32000 bytes per message |
| client -> Core, JSON | `capture.requested`, `capture.open`, `capture.denied`, `capture.lost`, `ptt.down`, `ptt.up`, `ptt.cancel` (drop the utterance), `mic.mute`, `mic.unmute`, `playback.finished` (`turn_epoch` optional), `interrupt`, `cancel`, `ping` |
| Core -> client | session events; `tts.started` carries `audio_path` (GET with the same Bearer token), `duration_ms`, `sample_rate` |

Flow: `listening` -> (push-to-talk buffer or energy-VAD endpointing) -> `endpointing` -> `transcribing` (faster-whisper with a words-only vocabulary prompt) -> `speech.transcript.final` -> `reasoning` (router rule, else the assistant) -> `assistant.text.final` -> `speaking` (`tts.started`) -> `playback.finished` -> `listening`. If the client never reports playback the session resumes listening after the reply length plus 5 s.

Limits: utterance 30 s (discarded whole, `UTTERANCE_TOO_LONG`), chunk 1 s, push-to-talk tap under 200 ms ignored. Temporary WAV is deleted when the STT stage ends; reply audio is deleted on session close; `data/tmp/voice` is swept at start.

Recording: `data/turns/turns-YYYYMMDD-N.jsonl`, one redacted line per turn, no audio (`turn_recording_enabled=false` turns it off). `TurnRecorder.export_failed_fixtures(dir)` writes failed turns as fixtures.

Router (`reva_core/language/router.py`) drafts expenses only ("add twelve dollars for lunch", "make it fifteen", "yes"/"never mind"). It never commits: accepting a draft calls `accept_proposal` and says nothing is saved. S09 replaces it.
