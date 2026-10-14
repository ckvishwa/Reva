"""Session states and the legal transitions between them (ARD-300 §3).

    Idle -> AcquiringPermission -> Listening -> Endpointing -> Transcribing
         -> Reasoning -> [ApprovalPending -> Executing] -> Speaking
         -> Listening | Idle

Any live state may also go to Cancelling (then Idle), RecoverableError or
FatalError. A barge-in is not a transition in this table: it bumps the turn
epoch and re-enters Listening, handled by `VoiceSession.interrupt`.
"""

from __future__ import annotations

from enum import StrEnum


class SessionState(StrEnum):
    IDLE = "idle"
    ACQUIRING_PERMISSION = "acquiring_permission"
    LISTENING = "listening"
    ENDPOINTING = "endpointing"
    TRANSCRIBING = "transcribing"
    REASONING = "reasoning"
    APPROVAL_PENDING = "approval_pending"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    CANCELLING = "cancelling"
    RECOVERABLE_ERROR = "recoverable_error"
    FATAL_ERROR = "fatal_error"


_S = SessionState

_FORWARD: dict[SessionState, frozenset[SessionState]] = {
    _S.IDLE: frozenset({_S.ACQUIRING_PERMISSION}),
    _S.ACQUIRING_PERMISSION: frozenset({_S.LISTENING}),
    _S.LISTENING: frozenset({_S.ENDPOINTING}),
    _S.ENDPOINTING: frozenset({_S.TRANSCRIBING, _S.LISTENING}),
    _S.TRANSCRIBING: frozenset({_S.REASONING, _S.LISTENING}),
    _S.REASONING: frozenset({_S.APPROVAL_PENDING, _S.EXECUTING, _S.SPEAKING}),
    _S.APPROVAL_PENDING: frozenset({_S.EXECUTING, _S.SPEAKING}),
    _S.EXECUTING: frozenset({_S.SPEAKING}),
    _S.SPEAKING: frozenset({_S.LISTENING, _S.IDLE}),
    _S.CANCELLING: frozenset({_S.IDLE}),
    _S.RECOVERABLE_ERROR: frozenset({_S.IDLE, _S.LISTENING}),
    _S.FATAL_ERROR: frozenset(),
}

_ANY_LIVE_STATE_MAY_GO = frozenset({_S.CANCELLING, _S.RECOVERABLE_ERROR, _S.FATAL_ERROR})
_NOT_LIVE = frozenset({_S.IDLE, _S.FATAL_ERROR})

# States in which a barge-in has something to cancel.
INTERRUPTIBLE = frozenset(
    {
        _S.TRANSCRIBING,
        _S.REASONING,
        _S.APPROVAL_PENDING,
        _S.EXECUTING,
        _S.SPEAKING,
    }
)


def can_transition(current: SessionState, target: SessionState) -> bool:
    if target in _FORWARD[current]:
        return True
    return current not in _NOT_LIVE and target in _ANY_LIVE_STATE_MAY_GO
