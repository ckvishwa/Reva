"""AR-CORE-001/002/005, AR-VA-019/022: session state machine, epochs, deadlines, timings."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from reva_core.session.coordinator import (
    DeadlineConfig,
    SessionCoordinator,
    Stage,
    VoiceSession,
)
from reva_core.session.state import SessionState
from reva_core.shared.errors import ValidationError

_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "session-event.schema.json").read_text(
        encoding="utf-8"
    )
)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _session(**kwargs) -> tuple[VoiceSession, list[int], _Clock]:
    stops: list[int] = []

    async def stop_speaking(session_id: str, epoch: int) -> None:
        stops.append(epoch)
        kwargs.get("scopes", []).append(session_id)

    clock = _Clock()
    coordinator = SessionCoordinator(
        deadlines=kwargs.pop("deadlines", DeadlineConfig(stt=1.0, model=1.0, tool=1.0, tts=1.0)),
        stop_speaking=stop_speaking,
        clock=clock,
    )
    session = coordinator.open("device-0001")
    return session, stops, clock


async def _drain(subscription, count: int | None = None) -> list[dict]:
    events: list[dict] = []
    while not subscription.empty():
        events.append((await subscription.get()).model_dump(mode="json"))
        if count is not None and len(events) >= count:
            break
    return events


async def _to_listening(session: VoiceSession) -> None:
    await session.start()
    await session.capture_opened()


async def _to_speaking(session: VoiceSession) -> None:
    await _to_listening(session)
    for state in (
        SessionState.ENDPOINTING,
        SessionState.TRANSCRIBING,
        SessionState.REASONING,
        SessionState.SPEAKING,
    ):
        await session.transition(state)


async def test_new_session_is_idle_at_epoch_zero_and_announces_itself():
    session, _, _ = _session()
    subscription = session.subscribe()

    events = await _drain(subscription)

    assert session.state == SessionState.IDLE
    assert session.turn_epoch == 0
    assert events[0]["kind"] == "session.state"
    assert events[0]["payload"]["state"] == "idle"
    assert events[0]["sequence"] == 0


async def test_listening_is_reached_only_when_capture_reports_the_mic_open():
    session, _, _ = _session()

    await session.start()
    assert session.state == SessionState.ACQUIRING_PERMISSION

    await session.capture_opened()
    assert session.state == SessionState.LISTENING


async def test_full_turn_walks_the_documented_states_and_returns_to_listening():
    session, _, _ = _session()
    subscription = session.subscribe()
    await _to_speaking(session)
    await session.transition(SessionState.LISTENING)

    states = [
        e["payload"]["state"] for e in await _drain(subscription) if e["kind"] == "session.state"
    ]

    assert states == [
        "idle",
        "acquiring_permission",
        "listening",
        "endpointing",
        "transcribing",
        "reasoning",
        "speaking",
        "listening",
    ]


async def test_approval_path_is_reachable_for_t2_actions():
    session, _, _ = _session()
    await _to_listening(session)
    for state in (
        SessionState.ENDPOINTING,
        SessionState.TRANSCRIBING,
        SessionState.REASONING,
        SessionState.APPROVAL_PENDING,
        SessionState.EXECUTING,
        SessionState.SPEAKING,
    ):
        await session.transition(state)

    assert session.state == SessionState.SPEAKING


@pytest.mark.parametrize(
    ("start_from", "target"),
    [
        (SessionState.IDLE, SessionState.SPEAKING),
        (SessionState.IDLE, SessionState.LISTENING),
        (SessionState.LISTENING, SessionState.REASONING),
        (SessionState.LISTENING, SessionState.EXECUTING),
        (SessionState.REASONING, SessionState.LISTENING),
    ],
)
async def test_invalid_transitions_are_rejected_and_leave_state_unchanged(start_from, target):
    session, _, _ = _session()
    path = {
        SessionState.IDLE: [],
        SessionState.LISTENING: ["start", "open"],
        SessionState.REASONING: ["start", "open", "ep", "tr", "re"],
    }[start_from]
    for step in path:
        if step == "start":
            await session.start()
        elif step == "open":
            await session.capture_opened()
        else:
            await session.transition(
                {
                    "ep": SessionState.ENDPOINTING,
                    "tr": SessionState.TRANSCRIBING,
                    "re": SessionState.REASONING,
                }[step]
            )

    with pytest.raises(ValidationError):
        await session.transition(target)

    assert session.state == start_from


async def test_only_one_turn_can_be_active_per_session():
    session, _, _ = _session()
    await _to_listening(session)

    with pytest.raises(ValidationError):
        await session.start()


async def test_events_carry_session_turn_epoch_and_validate_against_the_contract():
    session, _, _ = _session()
    subscription = session.subscribe()
    await _to_speaking(session)

    events = await _drain(subscription)

    assert len(events) >= 6
    for event in events:
        jsonschema.validate(event, _SCHEMA)
        assert event["session_id"] == session.id
        assert event["device_id"] == "device-0001"
        assert event["turn_epoch"] == 0
    sequences = [e["sequence"] for e in events]
    assert sequences == sorted(set(sequences))


async def test_interrupt_while_speaking_bumps_epoch_stops_audio_and_relistens():
    session, stops, _ = _session()
    await _to_speaking(session)
    first_turn = session.turn_id
    subscription = session.subscribe()
    await _drain(subscription)

    await session.interrupt()

    assert session.turn_epoch == 1
    assert stops == [1]
    assert session.state == SessionState.LISTENING
    assert session.turn_id != first_turn
    kinds = [e["kind"] for e in await _drain(subscription)]
    assert "tts.stopped" in kinds
    new_epoch_events = [e for e in await _drain(subscription)]
    assert new_epoch_events == []


async def test_interrupt_while_idle_is_a_no_op():
    session, stops, _ = _session()

    await session.interrupt()

    assert session.turn_epoch == 0
    assert stops == []
    assert session.state == SessionState.IDLE


async def test_cancel_goes_through_cancelling_to_idle_and_invalidates_the_turn():
    session, stops, _ = _session()
    subscription = session.subscribe()
    await _to_speaking(session)

    await session.cancel()

    states = [
        e["payload"]["state"] for e in await _drain(subscription) if e["kind"] == "session.state"
    ]
    assert states[-2:] == ["cancelling", "idle"]
    assert session.turn_epoch == 1
    assert stops == [1]


async def test_late_response_after_interrupt_is_never_applied():
    """AR-CORE-001: an older epoch's STT/model/tool/TTS result must be dropped."""
    session, _, _ = _session()
    await _to_listening(session)
    for state in (SessionState.ENDPOINTING, SessionState.TRANSCRIBING, SessionState.REASONING):
        await session.transition(state)
    release = asyncio.Event()

    async def stubborn_model() -> str:
        # Ignores cancellation, like a provider that keeps going after a barge-in.
        while not release.is_set():
            try:
                await asyncio.wait_for(release.wait(), timeout=5)
            except asyncio.CancelledError:
                continue
        return "STALE ANSWER"

    subscription = session.subscribe()
    await _drain(subscription)
    stage = asyncio.create_task(session.run_stage(Stage.MODEL, stubborn_model))
    await asyncio.sleep(0.05)

    await session.interrupt()
    result = await asyncio.wait_for(stage, timeout=2)
    release.set()
    await asyncio.sleep(0.05)

    assert result.applied is False
    assert result.reason == "superseded"
    assert session.late_results_dropped == 1
    assert session.state == SessionState.LISTENING
    texts = json.dumps([e["payload"] for e in await _drain(subscription)])
    assert "STALE ANSWER" not in texts


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        (Stage.STT, "STT_TIMEOUT"),
        (Stage.MODEL, "MODEL_TIMEOUT"),
        (Stage.TOOL, "TOOL_TIMEOUT"),
        (Stage.TTS, "TTS_TIMEOUT"),
    ],
)
async def test_each_stage_has_its_own_deadline_and_times_out_to_a_typed_error(stage, code):
    deadlines = DeadlineConfig(stt=5.0, model=5.0, tool=5.0, tts=5.0)
    deadlines = DeadlineConfig(**{**deadlines.__dict__, stage.value: 0.05})
    session, _, _ = _session(deadlines=deadlines)
    await _to_listening(session)
    subscription = session.subscribe()
    await _drain(subscription)

    async def too_slow() -> str:
        await asyncio.sleep(1.0)
        return "late"

    result = await session.run_stage(stage, too_slow)

    assert result.applied is False
    assert result.reason == "timeout"
    errors = [e for e in await _drain(subscription) if e["kind"] == "error"]
    assert errors[0]["payload"]["code"] == code
    assert errors[0]["payload"]["recoverable"] is True
    assert session.state == SessionState.IDLE


async def test_a_stage_that_finishes_in_time_returns_its_value():
    session, _, _ = _session()
    await _to_listening(session)

    async def quick() -> str:
        return "ok"

    result = await session.run_stage(Stage.STT, quick)

    assert (result.applied, result.value) == (True, "ok")


async def test_capture_loss_returns_to_safe_idle_with_a_typed_error():
    session, stops, _ = _session()
    await _to_listening(session)
    subscription = session.subscribe()
    await _drain(subscription)

    await session.capture_lost()

    events = await _drain(subscription)
    assert session.state == SessionState.IDLE
    assert stops, "playback must be stopped when the mic is lost"
    assert any(e["kind"] == "error" and e["payload"]["code"] == "CAPTURE_LOST" for e in events)


async def test_permission_denied_returns_to_idle_with_a_typed_error():
    session, _, _ = _session()
    await session.start()
    subscription = session.subscribe()
    await _drain(subscription)

    await session.capture_denied()

    events = await _drain(subscription)
    assert session.state == SessionState.IDLE
    assert any(e["kind"] == "error" and e["payload"]["code"] == "PERMISSION_DENIED" for e in events)


async def test_per_stage_timings_appear_in_events():
    session, _, clock = _session()
    await _to_listening(session)
    subscription = session.subscribe()
    await _drain(subscription)
    clock.advance(0.5)
    session.mark("speech_end")
    await session.transition(SessionState.ENDPOINTING)
    await session.transition(SessionState.TRANSCRIBING)

    async def stt() -> str:
        clock.advance(0.3)
        return "hello"

    await session.run_stage(Stage.STT, stt)
    session.mark("stt_final")
    await session.transition(SessionState.REASONING)

    last = [e for e in await _drain(subscription) if e["kind"] == "session.state"][-1]
    timings = last["payload"]["timings_ms"]
    assert timings["speech_end"] == 500
    assert timings["stt_final"] == 800
    assert timings["stt_ms"] == 300


async def test_slow_subscriber_drops_old_partials_but_never_state_events():
    session, _, _ = _session()
    subscription = session.subscribe(maxsize=8)
    await _drain(subscription)
    await _to_listening(session)

    for i in range(40):
        await session.emit_partial_transcript(f"word {i}")

    kept = await _drain(subscription)
    kinds = [e["kind"] for e in kept]
    assert "session.state" in kinds
    assert len(kept) <= 8
    assert kinds.count("speech.transcript.partial") < 40


async def test_coordinator_bounds_the_number_of_sessions_and_releases_on_close():
    coordinator = SessionCoordinator(max_sessions=2)
    first = coordinator.open("device-0001")
    coordinator.open("device-0001")

    with pytest.raises(ValidationError):
        coordinator.open("device-0001")

    assert await coordinator.close(first.id) is True
    assert coordinator.get(first.id) is None
    coordinator.open("device-0001")


async def test_the_stop_hook_is_told_which_session_to_silence():
    scopes: list[str] = []
    session, stops, _ = _session(scopes=scopes)
    await _to_speaking(session)

    await session.interrupt()

    assert stops == [1]
    assert scopes == [session.id]


async def test_two_sessions_count_their_epochs_independently():
    calls: list[tuple[str, int]] = []

    async def stop_speaking(session_id: str, epoch: int) -> None:
        calls.append((session_id, epoch))

    coordinator = SessionCoordinator(stop_speaking=stop_speaking)
    one = coordinator.open("device-0001")
    two = coordinator.open("device-0002")
    await _to_speaking(one)
    await _to_speaking(two)

    await one.interrupt()
    await one.cancel()
    await two.interrupt()

    assert one.turn_epoch == 2 and two.turn_epoch == 1
    assert calls == [(one.id, 1), (one.id, 2), (two.id, 1)]
