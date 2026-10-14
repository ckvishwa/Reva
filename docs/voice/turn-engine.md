# S06 — turn engine

What S06 added on top of the VOICE-1 session coordinator. Spec: ARD-450 (turn engine, §3.4 dialogue
state), AR-CORE-002/003, AR-LANG-005.

## Pieces

| Piece | Where | Notes |
|---|---|---|
| Per-session turn epoch | `KokoroSpeechProvider.speak(..., scope=)`, `stop(turn_epoch, scope=)` | One speaker at a time; a stop cancels only its own session's speech. |
| Endpointing | `reva_core/voice/endpointing.py` | Ported from Corx (`D:\Projects\Ai\Corx` @ `bba38fa`, the newest git-tracked copy; `D:\Projects\Corx` is older). Energy VAD in CI, optional Silero (`vad` extra), 300 ms pre-roll, close 280 ms after speech, `follow_up` within 8 s. |
| Ack-first | `reva_core/session/ack.py`, `VoiceSession.run_stage_with_ack` | "One sec." / "Checking." after 0.7 s with no answer; skipped on the fast path; dropped if the answer or a barge-in arrives first. The text is a template, never model output. |
| Normalizer | `reva_core/language/normalizer.py`, `numbers.py` | Money in exact minor units, numbers, percent, dates/times against an aware `now`, ISO 8601 durations. Ambiguity is kept as ranked readings ("two fifty", "at 7", "next friday"); it is never silently resolved. Scan capped at 2000 characters; amounts of 10^12 and up are not values. |
| Dialogue state | `reva_core/language/dialogue.py` | Active intent and slots, pending clarification, last-referenced entities ("it", "that one", "the one before"), undo pointer, language, `turn_epoch`. Saved per device in `data/dialogue/<hash>.json` after each accepted proposal and each barge-in that cancels a question. Resume drops references older than 30 min, questions past their expiry and undo older than 24 h, and rewrites the file. |
| First-audio budget | `kokoro_worker.py`, `api/app.py`, `providers/tts.py` | Core warms the voice in the background at start (`tts_warm_on_start`, default on; never blocks startup; a failure only logs). The first chunk is the first clause of a long first sentence; Kokoro's leading near-silence is trimmed to 20 ms on the first chunk only. |
| Per-stage timings | `payload.timings_ms` on every session event | `stt_ms`, `model_ms`, `tool_ms`, `tts_ms`, `ack_ms`, plus marks. |

The dialogue tracker only remembers and resolves references. It does not authorize or commit; a model
proposes, the policy broker authorizes, executors act.

## First-audio budget: measured

Dev PC, Realtek WASAPI output (device 20), **output muted**, real Kokoro `af_heart`, 10 runs of the
same sentence, `tools/voice/kokoro_hardware_demo.py speak --sink speaker --gain 0 --device 20`.
Artifacts: `docs/voice/timing-s06/muted-wasapi/`.

| Measurement | VOICE-1 (before) | S06 (after) | Budget |
|---|---|---|---|
| first audible p50 | 726.6 ms (FAIL) | **430.4 ms** | 700 ms |
| first audible p95 | n/a | 613.0 ms | |
| first chunk generated p50 | ~477 ms | 407.0 ms | |
| chunk enqueued to first non-silent callback p50 | ~219 ms (measured on the VOICE-1 code with the decomposition added) | 15.0 ms | |
| output device latency p50 | 10 ms | 8.6 ms | |

Where the time went: about 219 ms of the old figure was Kokoro's own leading near-silence reaching the
device; trimming it removed that. Warming moves the ~9 s model load out of the first utterance (this
benchmark already used a warmed worker, so the warm-up is not what changed the figure).

Muted is a measurement of the callback clock plus the device's reported output latency. It is not a
person hearing sound. `NEEDS_HARDWARE`: speaker run, see the ledger.

## Not done in S06

* Dialogue state is not yet fed by an intent router (S07). Nothing calls `reference()` or
  `accept_proposal()` from a live turn yet; the tests drive it directly.
* Silero is verified by an opt-in test only; CI uses the energy VAD.
* The normalizer is English only.
