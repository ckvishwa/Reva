"""The voice turn pipeline (MASTER-LOOP B1.2): audio in, a spoken answer out.

    PCM frames -> endpointing (or push-to-talk) -> speech-to-text -> router / assistant -> TTS

It drives a `VoiceSession` (the state machine and event stream); it adds no state of its own beyond
the audio buffer. Rules it keeps:

* Only a **final** transcript reaches the router; partials are display-only (AR-LANG-001).
* Audio is 16 kHz mono 16-bit PCM in bounded chunks. An utterance that grows past the cap is
  discarded whole, never transcribed in part, so a dropped buffer cannot run half a command
  (AR-VA-002).
* The temporary WAV handed to speech-to-text is deleted as soon as the stage ends, however it ends
  (AR-DATA-018). Raw audio is never logged or put in an event (AR-DATA-019).
* Every stage runs under the session's deadline and `turn_epoch`: a result that arrives after a
  barge-in or cancel is dropped and its audio file removed.
* What REVA says comes from the router's templates or the assistant; neither path can claim an
  action succeeded (no executor exists until S09).
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from reva_core.language.router import IntentRouter
from reva_core.models.stt import SpeechToTextProvider, TranscriptionInput, TranscriptionResult
from reva_core.models.tts import SynthesizedAudio
from reva_core.providers.cloud import AssistantReply
from reva_core.session.coordinator import Stage, VoiceSession
from reva_core.session.events import SessionEventKind
from reva_core.session.state import INTERRUPTIBLE, SessionState
from reva_core.session.turn_log import TurnRecord, TurnRecorder
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger
from reva_core.voice.endpointing import (
    BYTES_PER_SAMPLE,
    FRAME_MS,
    SAMPLE_RATE,
    EnergyVad,
    FrameVad,
    TurnSegmenter,
)

logger = get_logger("pipeline")

FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * BYTES_PER_SAMPLE
MAX_CHUNK_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE  # one second per message
MIN_UTTERANCE_MS = 200
PLAYBACK_GRACE_SECONDS = 5.0

REPLY_FAILED = "Sorry, I couldn't answer that."
REPLY_NO_SPEECH = ""


class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str, language: str) -> SynthesizedAudio: ...


Responder = Callable[[str, str], Awaitable[str | AssistantReply]]
"""(transcript, correlation_id) -> the assistant's reply (plain text or an AssistantReply)."""


@dataclass(frozen=True)
class PipelineConfig:
    max_utterance_ms: int = 30_000
    barge_in_by_voice: bool = False  # off: speakers would hear themselves and interrupt
    default_language: str = "en"


class AudioStore:
    """Synthesised replies waiting for the client to fetch them. Bounded; files are removed."""

    def __init__(self, max_items: int = 4) -> None:
        self._items: dict[str, SynthesizedAudio] = {}
        self._max = max_items

    def put(self, audio: SynthesizedAudio) -> str:
        audio_id = new_id()
        self._items[audio_id] = audio
        while len(self._items) > self._max:
            self._drop(next(iter(self._items)))
        return audio_id

    def path(self, audio_id: str) -> Path | None:
        item = self._items.get(audio_id)
        return item.path if item is not None else None

    def discard(self, audio_id: str) -> None:
        self._drop(audio_id)

    def clear(self) -> None:
        for audio_id in list(self._items):
            self._drop(audio_id)

    def _drop(self, audio_id: str) -> None:
        item = self._items.pop(audio_id, None)
        if item is not None:
            item.path.unlink(missing_ok=True)


class TurnPipeline:
    def __init__(
        self,
        session: VoiceSession,
        *,
        stt: SpeechToTextProvider | None,
        tts: SpeechSynthesizer | None,
        respond: Responder,
        router: IntentRouter,
        recorder: TurnRecorder,
        scratch_dir: Path | None = None,
        config: PipelineConfig | None = None,
        vad_factory: Callable[[], FrameVad] = EnergyVad,
        now: Callable[[], datetime] = lambda: datetime.now(UTC).astimezone(),
    ) -> None:
        self.session = session
        self.audio = AudioStore()
        self.mic_muted = False
        self._stt = stt
        self._tts = tts
        self._respond = respond
        self._router = router
        self._recorder = recorder
        self._scratch = scratch_dir
        self._config = config or PipelineConfig()
        self._segmenter = TurnSegmenter(vad_factory())
        self._now = now
        self._carry = b""
        self._ptt: bytearray | None = None
        self._discarding = False
        self._speech_ms = 0
        self._turn_tasks: set[asyncio.Task[None]] = set()
        self._watchdog: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ inputs

    async def on_audio(self, chunk: bytes) -> None:
        """Binary frames from the client. Dropped when muted or when nothing is listening."""
        if self.mic_muted:
            return
        if len(chunk) == 0 or len(chunk) > MAX_CHUNK_BYTES or len(chunk) % BYTES_PER_SAMPLE:
            self.session.emit(
                SessionEventKind.ERROR,
                {"code": "BAD_AUDIO", "recoverable": True, "stage": None},
            )
            return
        state = self.session.state
        if self._ptt is not None:
            self._append_ptt(chunk)
            return
        if state == SessionState.SPEAKING and not self._config.barge_in_by_voice:
            return
        if state not in (SessionState.LISTENING, SessionState.SPEAKING):
            return
        self._carry += chunk
        while len(self._carry) >= FRAME_BYTES:
            frame, self._carry = self._carry[:FRAME_BYTES], self._carry[FRAME_BYTES:]
            turns = self._segmenter.feed(frame)
            if self._segmenter.in_speech:
                self._speech_ms += FRAME_MS
                if self._speech_ms > self._config.max_utterance_ms:
                    self._discard_open_speech()  # never transcribe half of an endless utterance
                    continue
            else:
                self._speech_ms = 0
            if self._segmenter.in_speech and self.session.state in INTERRUPTIBLE:
                await self.session.interrupt()  # voice barge-in (only when enabled)
            for turn in turns:
                if self.session.state == SessionState.LISTENING:
                    self._spawn(self._run_turn(turn.audio))

    async def on_ptt_down(self) -> None:
        """Push-to-talk pressed: interrupt whatever is happening and record until released."""
        if self.mic_muted:
            return
        if self.session.state in INTERRUPTIBLE:
            await self.session.interrupt()
        if self.session.state != SessionState.LISTENING:
            return
        self._ptt = bytearray()
        self._discarding = False
        self._segmenter.reset()
        self._carry = b""

    async def on_ptt_up(self) -> None:
        buffer, self._ptt = self._ptt, None
        if buffer is None or self._discarding:
            self._discarding = False
            return
        if len(buffer) * 1000 // (SAMPLE_RATE * BYTES_PER_SAMPLE) < MIN_UTTERANCE_MS:
            return  # a tap, not speech
        if self.session.state == SessionState.LISTENING:
            self._spawn(self._run_turn(bytes(buffer)))

    async def on_ptt_cancel(self) -> None:
        """The client dropped the utterance (audio could not keep up, or the mic was muted)."""
        self._ptt = None
        self._discarding = False

    def set_muted(self, muted: bool) -> None:
        self.mic_muted = muted
        if muted:
            self._segmenter.reset()
            self._carry = b""
            self._ptt = None

    async def on_playback_finished(self, turn_epoch: int | None = None) -> None:
        """The client finished playing the reply (or its last sample was flushed)."""
        session = self.session
        if session.state != SessionState.SPEAKING:
            return
        if turn_epoch is not None and turn_epoch != session.turn_epoch:
            return  # an older reply finished late
        self._cancel_watchdog()
        session.emit(SessionEventKind.TTS_STOPPED, {"reason": "completed"})
        await session.transition(SessionState.LISTENING, reason="playback_finished")

    async def close(self) -> None:
        self._cancel_watchdog()
        for task in list(self._turn_tasks):
            task.cancel()
        for task in list(self._turn_tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.audio.clear()

    async def wait_idle(self) -> None:
        """Wait for turns in flight (tests)."""
        while self._turn_tasks:
            await asyncio.gather(*list(self._turn_tasks), return_exceptions=True)

    # ------------------------------------------------------------------- turns

    def _append_ptt(self, chunk: bytes) -> None:
        assert self._ptt is not None
        if self._discarding:
            return
        limit = self._config.max_utterance_ms * SAMPLE_RATE * BYTES_PER_SAMPLE // 1000
        if len(self._ptt) + len(chunk) > limit:
            self._discarding = True
            self._ptt.clear()
            self.session.emit(
                SessionEventKind.ERROR,
                {"code": "UTTERANCE_TOO_LONG", "recoverable": True, "stage": None},
            )
            return
        self._ptt.extend(chunk)

    def _discard_open_speech(self) -> None:
        self._segmenter.reset()
        self._speech_ms = 0
        self._carry = b""
        self.session.emit(
            SessionEventKind.ERROR,
            {"code": "UTTERANCE_TOO_LONG", "recoverable": True, "stage": None},
        )

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.get_running_loop().create_task(_guard(coro))
        self._turn_tasks.add(task)
        task.add_done_callback(self._turn_tasks.discard)

    async def _run_turn(self, pcm: bytes) -> None:
        session = self.session
        epoch = session.turn_epoch
        turn_id = session.turn_id

        def record(
            outcome: str,
            *,
            transcript: str = "",
            route: str | None = None,
            language: str | None = None,
        ) -> None:
            self._recorder.record(
                TurnRecord(
                    turn_id=turn_id,
                    session_id=session.id,
                    device_id=session.device_id,
                    turn_epoch=epoch,
                    outcome=outcome,
                    route=route,
                    transcript=transcript,
                    language=language,
                    timings_ms=session.timings_snapshot(),
                )
            )

        if self._stt is None:
            session.emit(
                SessionEventKind.ERROR,
                {"code": "STT_UNAVAILABLE", "recoverable": True, "stage": "stt"},
            )
            record("stt_unavailable")
            return
        session.mark("speech_end")
        await session.transition(SessionState.ENDPOINTING)
        await session.transition(SessionState.TRANSCRIBING)

        transcript = await self._transcribe(pcm)
        if transcript is None:
            if session.turn_epoch == epoch and session.state == SessionState.TRANSCRIBING:
                await session.transition(SessionState.LISTENING, reason="no_speech")
                record("stt_empty")
            else:
                record("superseded")
            return
        if isinstance(transcript, ProviderError):
            if session.turn_epoch == epoch and session.state == SessionState.TRANSCRIBING:
                code = (
                    "STT_UNAVAILABLE"
                    if transcript.kind != ProviderErrorKind.INVALID_RESPONSE
                    else "STT_NO_TRANSCRIPT"
                )
                session.emit(
                    SessionEventKind.ERROR, {"code": code, "recoverable": True, "stage": "stt"}
                )
                await session.transition(SessionState.LISTENING, reason="stt_error")
                record("stt_empty" if code == "STT_NO_TRANSCRIPT" else "stt_unavailable")
            else:
                record("superseded")
            return

        session.mark("stt_final")
        session.emit(
            SessionEventKind.TRANSCRIPT_FINAL,
            {
                "text": transcript.text,
                "language": transcript.language,
                "provider": transcript.provider,
                "duration_ms": transcript.duration_ms,
            },
        )
        await session.transition(SessionState.REASONING)
        routed = self._router.route(transcript.text, now=self._now())
        if routed.kind == "chat":
            answer = await self._ask_assistant(transcript.text, epoch)
            if answer is None:
                if session.turn_epoch != epoch:
                    record("superseded", transcript=transcript.text, route="chat")
                    return
                reply, source, outcome = REPLY_FAILED, "template", "model_failed"
                provider, notice = "template", None
            else:
                reply, source, outcome = answer.text, "model", "ok"
                provider, notice = answer.provider, answer.notice
        else:
            reply, source, outcome = routed.reply or "", "template", "ok"
            provider, notice = "template", None
        if session.turn_epoch != epoch:
            record("superseded", transcript=transcript.text, route=routed.kind)
            return
        record(
            outcome,
            transcript=transcript.text,
            route=routed.kind,
            language=transcript.language,
        )
        final: dict[str, object] = {"text": reply, "source": source, "provider": provider}
        if notice is not None:
            final["notice"] = notice
        session.emit(SessionEventKind.ASSISTANT_TEXT_FINAL, final)
        await self._speak(reply, transcript.language, epoch)

    async def _transcribe(self, pcm: bytes) -> TranscriptionResult | ProviderError | None:
        assert self._stt is not None
        stt = self._stt
        path = self._write_wav(pcm)

        async def call() -> TranscriptionResult | ProviderError:
            try:
                return await stt.transcribe(TranscriptionInput(path=path, media_type="audio/wav"))
            except ProviderError as exc:
                return exc

        try:
            result = await self.session.run_stage(Stage.STT, call)
        finally:
            path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        if not result.applied:
            return None
        return result.value

    def _write_wav(self, pcm: bytes) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="reva-turn-", dir=self._scratch))
        path = directory / "turn.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(BYTES_PER_SAMPLE)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(pcm)
        return path

    async def _ask_assistant(self, text: str, epoch: int) -> AssistantReply | None:
        session = self.session

        async def call() -> AssistantReply | None:
            try:
                answer = await self._respond(text, session.correlation_id)
                return answer if isinstance(answer, AssistantReply) else AssistantReply(answer)
            except Exception:
                logger.warning("assistant reply failed", exc_info=True)
                return None

        result = await session.run_stage_with_ack(call)
        if not result.applied or session.turn_epoch != epoch:
            return None
        return result.value

    async def _speak(self, text: str, language: str, epoch: int) -> None:
        session = self.session
        await session.transition(SessionState.SPEAKING)
        if self._tts is None or not text:
            await self._finish_silently("tts_unavailable" if text else "nothing_to_say")
            return
        tts = self._tts

        async def call() -> SynthesizedAudio | None:
            try:
                return await tts.synthesize(text, language)
            except Exception:
                logger.warning("speech synthesis failed", exc_info=True)
                return None

        result = await session.run_stage(Stage.TTS, call)
        audio = result.value if result.applied else None
        if audio is not None and session.turn_epoch != epoch:
            audio.path.unlink(missing_ok=True)  # a barge-in happened while it was being made
            return
        if audio is None:
            if result.applied and session.turn_epoch == epoch:
                session.emit(
                    SessionEventKind.ERROR,
                    {"code": "TTS_UNAVAILABLE", "recoverable": True, "stage": "tts"},
                )
                await self._finish_silently("tts_failed")
            return
        audio_id = self.audio.put(audio)
        session.mark("tts_ready")
        session.emit(
            SessionEventKind.TTS_STARTED,
            {
                "purpose": "reply",
                "audio_id": audio_id,
                "audio_path": f"/v1/voice/sessions/{session.id}/audio/{audio_id}",
                "duration_ms": audio.duration_ms,
                "sample_rate": audio.sample_rate,
            },
        )
        self._watchdog = asyncio.get_running_loop().create_task(
            self._playback_watchdog(epoch, audio.duration_ms / 1000 + PLAYBACK_GRACE_SECONDS)
        )

    async def _finish_silently(self, reason: str) -> None:
        if self.session.state == SessionState.SPEAKING:
            await self.session.transition(SessionState.LISTENING, reason=reason)

    async def _playback_watchdog(self, epoch: int, seconds: float) -> None:
        """If the client never says playback finished, listening resumes anyway."""
        await asyncio.sleep(seconds)
        if self.session.turn_epoch == epoch:
            await self.on_playback_finished(epoch)

    def _cancel_watchdog(self) -> None:
        if self._watchdog is not None and not self._watchdog.done():
            self._watchdog.cancel()
        self._watchdog = None


async def _guard(coro: Awaitable[None]) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("voice turn failed", exc_info=True)
