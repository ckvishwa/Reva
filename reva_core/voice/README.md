Status: PLANNED
Target phase: Phase 2 — Voice loop
Responsibility: Voice lifecycle coordination — push-to-talk capture handoff, STT request/response, cancellation/interrupt, TTS playback handoff. Delegates actual speech processing to `models/stt.py` and `models/tts.py` provider interfaces; never talks to a vendor SDK directly and never persists raw audio by default (security invariant #7).
