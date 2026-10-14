"""Session events (`contracts/session-event.schema.json`) and subscriptions.

Every event carries session, turn, epoch and correlation ids (AR-CORE-005).

Each subscriber has a bounded queue (AR-CORE-012). Saturation behavior:
when full, the oldest *droppable* event (a partial transcript or a text
delta, both display-only) is discarded to make room. State, error, action
and outcome events are never dropped; if the queue is full of those, the
subscriber is marked overrun and closed, and the client must reconnect and
resync from the replayed history.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class SessionEventKind(StrEnum):
    SESSION_STATE = "session.state"
    TRANSCRIPT_PARTIAL = "speech.transcript.partial"
    TRANSCRIPT_FINAL = "speech.transcript.final"
    ASSISTANT_TEXT_DELTA = "assistant.text.delta"
    ASSISTANT_TEXT_FINAL = "assistant.text.final"
    TTS_STARTED = "tts.started"
    TTS_STOPPED = "tts.stopped"
    ACTION_PROPOSED = "action.proposed"
    ACTION_APPROVAL_REQUIRED = "action.approval_required"
    ACTION_OUTCOME = "action.outcome"
    ERROR = "error"


_DROPPABLE = frozenset(
    {
        SessionEventKind.TRANSCRIPT_PARTIAL,
        SessionEventKind.ASSISTANT_TEXT_DELTA,
    }
)


class SessionErrorCode(StrEnum):
    STT_TIMEOUT = "STT_TIMEOUT"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TTS_TIMEOUT = "TTS_TIMEOUT"
    CAPTURE_LOST = "CAPTURE_LOST"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    BAD_CONTROL_MESSAGE = "BAD_CONTROL_MESSAGE"
    INTERNAL = "INTERNAL"


class SessionEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    event_id: str
    sequence: int
    timestamp: datetime
    device_id: str
    session_id: str
    turn_id: str
    turn_epoch: int
    correlation_id: str
    kind: SessionEventKind
    payload: dict[str, Any]


class EventSubscription:
    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._items: deque[SessionEvent] = deque()
        self._ready = asyncio.Event()
        self.closed = False
        self.overrun = False

    def put(self, event: SessionEvent) -> None:
        if self.closed:
            return
        if len(self._items) >= self._maxsize:
            victim = next((e for e in self._items if e.kind in _DROPPABLE), None)
            if victim is None:
                self.overrun = True
                self.close()
                return
            self._items.remove(victim)
        self._items.append(event)
        self._ready.set()

    def empty(self) -> bool:
        return not self._items

    async def get(self) -> SessionEvent | None:
        """Next event, or `None` once the subscription is closed and drained."""
        while not self._items:
            if self.closed:
                return None
            self._ready.clear()
            await self._ready.wait()
        return self._items.popleft()

    def close(self) -> None:
        self.closed = True
        self._ready.set()

    def __aiter__(self) -> EventSubscription:
        return self

    async def __anext__(self) -> SessionEvent:
        event = await self.get()
        if event is None:
            raise StopAsyncIteration
        return event
