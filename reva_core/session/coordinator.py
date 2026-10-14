"""VoiceSession and SessionCoordinator (AR-CORE-001/002/005, AR-VA-019/022).

* One active turn per session. `turn_epoch` increases on every barge-in or
  cancel; STT, model, tool and TTS results from an older epoch are dropped,
  even when the underlying task ignores cancellation.
* Each stage (STT, model, tool, TTS) has its own deadline. A timeout becomes
  a typed, recoverable error and a return to idle, never a hang.
* Per-stage timings are attached to every event as `payload.timings_ms`.
* `Listening` is entered only when the capture adapter reports the mic open,
  so the indicator reflects real capture state (AR-WIN-004).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from reva_core.session.events import (
    EventSubscription,
    SessionErrorCode,
    SessionEvent,
    SessionEventKind,
)
from reva_core.session.state import INTERRUPTIBLE, SessionState, can_transition
from reva_core.shared.errors import ValidationError
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger
from reva_core.shared.time import utc_now

logger = get_logger("session")

# (session id, turn_epoch): epochs are per session, so the hook says whose speech to stop.
StopSpeaking = Callable[[str, int], Awaitable[None]]

_HISTORY_SIZE = 64
_NEW_TURN_FROM = frozenset(
    {SessionState.ACQUIRING_PERMISSION, SessionState.SPEAKING, SessionState.RECOVERABLE_ERROR}
)


class Stage(StrEnum):
    STT = "stt"
    MODEL = "model"
    TOOL = "tool"
    TTS = "tts"


@dataclass(frozen=True)
class DeadlineConfig:
    """Per-stage deadlines in seconds (AR-CORE-002)."""

    stt: float = 10.0
    model: float = 30.0
    tool: float = 10.0
    tts: float = 15.0

    def for_stage(self, stage: Stage) -> float:
        return float(getattr(self, stage.value))

    def as_millis(self) -> dict[str, int]:
        return {s.value: int(self.for_stage(s) * 1000) for s in Stage}


@dataclass(frozen=True)
class StageResult[T]:
    applied: bool
    value: T | None = None
    reason: str = "ok"


class _TurnTimings:
    """Marks and stage durations for one turn, in ms since the turn began."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._origin = clock()
        self._marks: dict[str, int] = {}
        self._stage_started: dict[Stage, float] = {}

    def mark(self, name: str) -> None:
        self._marks[name] = round((self._clock() - self._origin) * 1000)

    def start(self, stage: Stage) -> None:
        self._stage_started[stage] = self._clock()

    def end(self, stage: Stage) -> None:
        started = self._stage_started.pop(stage, None)
        if started is not None:
            self._marks[f"{stage.value}_ms"] = round((self._clock() - started) * 1000)

    def snapshot(self) -> dict[str, int]:
        return dict(self._marks)


class VoiceSession:
    def __init__(
        self,
        *,
        session_id: str,
        device_id: str,
        deadlines: DeadlineConfig,
        stop_speaking: StopSpeaking | None,
        clock: Callable[[], float],
    ) -> None:
        self.id = session_id
        self.device_id = device_id
        self.correlation_id = new_id()
        self.deadlines = deadlines
        self.state = SessionState.IDLE
        self.turn_epoch = 0
        self.turn_id = new_id()
        self.late_results_dropped = 0
        self._stop_speaking = stop_speaking
        self._clock = clock
        self._timings = _TurnTimings(clock)
        self._sequence = 0
        self._history: deque[SessionEvent] = deque(maxlen=_HISTORY_SIZE)
        self._subscribers: list[EventSubscription] = []
        self._epoch_changed: asyncio.Future[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._emit_state(previous=None, reason=None)

    # ------------------------------------------------------------ subscriptions

    def subscribe(self, maxsize: int = 256, *, replay: bool = True) -> EventSubscription:
        subscription = EventSubscription(maxsize)
        if replay:
            for event in self._history:
                subscription.put(event)
        self._subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        subscription.close()
        with contextlib.suppress(ValueError):
            self._subscribers.remove(subscription)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Begin acquiring the microphone. Listening waits for `capture_opened`."""
        await self.transition(SessionState.ACQUIRING_PERMISSION)

    async def capture_opened(self) -> None:
        await self.transition(SessionState.LISTENING)

    async def capture_denied(self) -> None:
        if self.state == SessionState.ACQUIRING_PERMISSION:
            await self._fail(SessionErrorCode.PERMISSION_DENIED)

    async def capture_lost(self) -> None:
        """Mic unplugged or permission revoked: stop audio and return to safe idle."""
        if self.state not in (SessionState.IDLE, SessionState.FATAL_ERROR):
            await self._fail(SessionErrorCode.CAPTURE_LOST)

    async def transition(self, target: SessionState, *, reason: str | None = None) -> None:
        if not can_transition(self.state, target):
            raise ValidationError(
                f"illegal session transition {self.state.value} -> {target.value}"
            )
        self._enter(target, reason)

    async def interrupt(self) -> None:
        """Barge-in: new epoch, stop playback, drop older results, listen again."""
        if self.state not in INTERRUPTIBLE:
            return
        was_speaking = self.state == SessionState.SPEAKING
        self._bump_epoch()
        await self._silence()
        if was_speaking:
            self._emit(SessionEventKind.TTS_STOPPED, {"reason": "interrupt"})
        self._enter(SessionState.LISTENING, "interrupt", new_turn=True)

    async def cancel(self) -> None:
        if self.state in (SessionState.IDLE, SessionState.FATAL_ERROR):
            return
        self._bump_epoch()
        self._enter(SessionState.CANCELLING, "cancel")
        await self._silence()
        self._enter(SessionState.IDLE, "cancel")

    async def close(self) -> None:
        await self.cancel()
        for task in list(self._tasks):
            task.cancel()
        for subscription in list(self._subscribers):
            subscription.close()
        self._subscribers.clear()

    # --------------------------------------------------------------------- stages

    def mark(self, name: str) -> None:
        self._timings.mark(name)

    async def run_stage[T](self, stage: Stage, fn: Callable[[], Awaitable[T]]) -> StageResult[T]:
        epoch = self.turn_epoch
        changed = self._epoch_future()
        self._timings.start(stage)
        task: asyncio.Task[T] = asyncio.get_running_loop().create_task(_call(fn))
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._stage_finished(t, epoch))
        waiters: set[asyncio.Future[Any]] = {task, changed}
        done, _ = await asyncio.wait(
            waiters,
            timeout=self.deadlines.for_stage(stage),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if self.turn_epoch != epoch:
            task.cancel()
            return StageResult(applied=False, reason="superseded")
        if task in done:
            self._timings.end(stage)
            return StageResult(applied=True, value=task.result())
        task.cancel()
        await self._fail(SessionErrorCode(f"{stage.value.upper()}_TIMEOUT"))
        return StageResult(applied=False, reason="timeout")

    async def emit_partial_transcript(self, text: str) -> None:
        """Display-only. A partial never reaches NLU or triggers an action."""
        if self.state in (
            SessionState.LISTENING,
            SessionState.ENDPOINTING,
            SessionState.TRANSCRIBING,
        ):
            self._emit(SessionEventKind.TRANSCRIPT_PARTIAL, {"text": text})

    def emit(self, kind: SessionEventKind, payload: dict[str, Any]) -> None:
        self._emit(kind, payload)

    # ------------------------------------------------------------------ internals

    def _stage_finished(self, task: asyncio.Task[Any], epoch: int) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        task.exception()  # mark retrieved; a stale failure must not surface
        if epoch != self.turn_epoch:
            self.late_results_dropped += 1
            logger.info("dropped a late stage result from epoch %s", epoch)

    def _epoch_future(self) -> asyncio.Future[None]:
        if self._epoch_changed is None or self._epoch_changed.done():
            self._epoch_changed = asyncio.get_running_loop().create_future()
        return self._epoch_changed

    def _bump_epoch(self) -> None:
        self.turn_epoch += 1
        if self._epoch_changed is not None and not self._epoch_changed.done():
            self._epoch_changed.set_result(None)
        self._epoch_changed = None

    async def _silence(self) -> None:
        if self._stop_speaking is not None:
            try:
                await self._stop_speaking(self.id, self.turn_epoch)
            except Exception:
                logger.warning("stop-speaking hook failed", exc_info=True)

    async def _fail(self, code: SessionErrorCode, *, recoverable: bool = True) -> None:
        self._bump_epoch()
        stage = (
            code.value.removesuffix("_TIMEOUT").lower() if code.value.endswith("_TIMEOUT") else None
        )
        self._enter(
            SessionState.RECOVERABLE_ERROR if recoverable else SessionState.FATAL_ERROR,
            code.value,
        )
        self._emit(
            SessionEventKind.ERROR,
            {"code": code.value, "recoverable": recoverable, "stage": stage},
        )
        await self._silence()
        if recoverable:
            self._enter(SessionState.IDLE, code.value)

    def _enter(self, target: SessionState, reason: str | None, *, new_turn: bool = False) -> None:
        previous = self.state
        self.state = target
        if target == SessionState.LISTENING and (new_turn or previous in _NEW_TURN_FROM):
            self.turn_id = new_id()
            self._timings = _TurnTimings(self._clock)
        self._emit_state(previous=previous, reason=reason)

    def _emit_state(self, *, previous: SessionState | None, reason: str | None) -> None:
        payload: dict[str, Any] = {"state": self.state.value}
        if previous is not None:
            payload["previous"] = previous.value
        if reason is not None:
            payload["reason"] = reason
        self._emit(SessionEventKind.SESSION_STATE, payload)

    def _emit(self, kind: SessionEventKind, payload: dict[str, Any]) -> None:
        event = SessionEvent(
            event_id=new_id(),
            sequence=self._sequence,
            timestamp=utc_now(),
            device_id=self.device_id,
            session_id=self.id,
            turn_id=self.turn_id,
            turn_epoch=self.turn_epoch,
            correlation_id=self.correlation_id,
            kind=kind,
            payload={**payload, "timings_ms": self._timings.snapshot()},
        )
        self._sequence += 1
        self._history.append(event)
        for subscription in list(self._subscribers):
            subscription.put(event)
            if subscription.closed:
                self._subscribers.remove(subscription)


async def _call[T](fn: Callable[[], Awaitable[T]]) -> T:
    return await fn()


class SessionCoordinator:
    """Owns open sessions. Bounded: saturation raises instead of queueing."""

    def __init__(
        self,
        *,
        max_sessions: int = 4,
        deadlines: DeadlineConfig | None = None,
        stop_speaking: StopSpeaking | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_sessions = max_sessions
        self._deadlines = deadlines or DeadlineConfig()
        self._stop_speaking = stop_speaking
        self._clock = clock
        self._sessions: dict[str, VoiceSession] = {}

    @property
    def deadlines(self) -> DeadlineConfig:
        return self._deadlines

    def open(self, device_id: str) -> VoiceSession:
        if len(self._sessions) >= self._max_sessions:
            raise ValidationError("too many open voice sessions")
        session = VoiceSession(
            session_id=new_id(),
            device_id=device_id,
            deadlines=self._deadlines,
            stop_speaking=self._stop_speaking,
            clock=self._clock,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> VoiceSession | None:
        return self._sessions.get(session_id)

    async def close(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await session.close()
        return True

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            await self.close(session_id)
