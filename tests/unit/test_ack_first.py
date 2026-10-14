"""S06: acknowledge-first (ARD-450 §4.2, AR-LANG-010, ADR-037).

If reasoning runs past ~700 ms, a short neutral acknowledgement is played. It is never phrased as
success, it is skipped for fast-path turns and for answers that arrive in time, and a barge-in
cancels it. Timing tests use a short delay so the suite stays fast; the default is asserted as a
constant.
"""

from __future__ import annotations

import asyncio

import pytest

from reva_core.session.ack import ACK_AFTER_SECONDS, ACK_TEMPLATES, FORBIDDEN_IN_AN_ACK
from reva_core.session.coordinator import DeadlineConfig, SessionCoordinator, VoiceSession
from reva_core.session.state import SessionState

DELAY = 0.08


async def _reasoning(session: VoiceSession) -> None:
    await session.start()
    await session.capture_opened()
    for state in (
        SessionState.ENDPOINTING,
        SessionState.TRANSCRIBING,
        SessionState.REASONING,
    ):
        await session.transition(state)


def _session(ack_delay: float = DELAY, **kwargs):
    spoken: list[tuple[str, int, str]] = []
    stops: list[tuple[str, int]] = []

    async def speak_ack(session_id: str, epoch: int, text: str) -> None:
        spoken.append((session_id, epoch, text))

    async def stop_speaking(session_id: str, epoch: int) -> None:
        stops.append((session_id, epoch))

    coordinator = SessionCoordinator(
        deadlines=DeadlineConfig(stt=2.0, model=2.0, tool=2.0, tts=2.0),
        stop_speaking=stop_speaking,
        speak_ack=speak_ack,
        ack_delay_seconds=ack_delay,
        **kwargs,
    )
    return coordinator.open("device-0001"), spoken, stops


async def _kinds(session: VoiceSession) -> list[dict]:
    subscription = session.subscribe(replay=False)
    return [subscription]  # type: ignore[return-value]


def _acks(session: VoiceSession) -> list[dict]:
    return [
        e.model_dump(mode="json")
        for e in session._history  # noqa: SLF001 - the recorded event stream
        if e.kind.value == "tts.started" and e.payload.get("purpose") == "ack"
    ]


def test_the_budget_is_700_ms_and_the_templates_are_neutral() -> None:
    assert ACK_AFTER_SECONDS == 0.7
    assert ACK_TEMPLATES == ("One sec.", "Checking.")
    for text in ACK_TEMPLATES:
        lowered = text.lower()
        assert not any(word in lowered for word in FORBIDDEN_IN_AN_ACK), text


async def test_slow_reasoning_gets_an_acknowledgement_after_the_budget() -> None:
    session, spoken, _ = _session()
    await _reasoning(session)

    async def slow_model() -> str:
        await asyncio.sleep(DELAY * 4)
        return "answer"

    result = await session.run_stage_with_ack(slow_model)

    assert result.applied and result.value == "answer"
    assert len(spoken) == 1
    assert spoken[0][0] == session.id and spoken[0][2] in ACK_TEMPLATES
    acks = _acks(session)
    assert len(acks) == 1 and acks[0]["payload"]["text"] == spoken[0][2]
    assert acks[0]["payload"]["purpose"] == "ack"
    assert "ack_ms" in acks[0]["payload"]["timings_ms"]


async def test_a_fast_answer_gets_no_acknowledgement() -> None:
    session, spoken, _ = _session()
    await _reasoning(session)

    async def quick_model() -> str:
        await asyncio.sleep(DELAY / 4)
        return "answer"

    await session.run_stage_with_ack(quick_model)
    await asyncio.sleep(DELAY * 2)  # long enough for a stray timer to fire

    assert spoken == [] and _acks(session) == []


async def test_a_fast_path_turn_is_never_acknowledged() -> None:
    session, spoken, _ = _session()
    await _reasoning(session)

    async def slow_model() -> str:
        await asyncio.sleep(DELAY * 3)
        return "answer"

    await session.run_stage_with_ack(slow_model, fast_path=True)

    assert spoken == [] and _acks(session) == []


async def test_a_barge_in_before_the_budget_cancels_the_acknowledgement() -> None:
    session, spoken, _ = _session(ack_delay=0.3)
    await _reasoning(session)

    async def slow_model() -> str:
        await asyncio.sleep(5)
        return "answer"

    stage = asyncio.create_task(session.run_stage_with_ack(slow_model))
    await asyncio.sleep(0.05)
    await session.interrupt()
    result = await stage
    await asyncio.sleep(0.4)

    assert result.applied is False and result.reason == "superseded"
    assert spoken == [] and _acks(session) == []


async def test_a_barge_in_while_the_acknowledgement_plays_stops_it() -> None:
    session, spoken, stops = _session()
    await _reasoning(session)
    subscription = session.subscribe(replay=False)

    async def slow_model() -> str:
        await asyncio.sleep(5)
        return "answer"

    stage = asyncio.create_task(session.run_stage_with_ack(slow_model))
    for _ in range(100):
        if spoken:
            break
        await asyncio.sleep(0.02)
    assert spoken, "the acknowledgement never played"

    await session.interrupt()
    await stage

    events = []
    while not subscription.empty():
        events.append((await subscription.get()).model_dump(mode="json"))
    stopped = [e for e in events if e["kind"] == "tts.stopped"]
    assert stopped and stopped[0]["payload"]["purpose"] == "ack"
    assert stops and stops[-1][0] == session.id


async def test_the_acknowledgement_is_announced_once_per_turn() -> None:
    session, spoken, _ = _session()
    await _reasoning(session)

    async def slow_model() -> str:
        await asyncio.sleep(DELAY * 6)
        return "answer"

    await session.run_stage_with_ack(slow_model)

    assert len(spoken) == 1


async def test_a_model_timeout_still_gets_at_most_the_one_acknowledgement() -> None:
    coordinator = SessionCoordinator(
        deadlines=DeadlineConfig(stt=1.0, model=0.3, tool=1.0, tts=1.0),
        ack_delay_seconds=0.05,
        speak_ack=lambda *_: asyncio.sleep(0),
    )
    session = coordinator.open("device-0001")
    await _reasoning(session)

    async def never() -> str:
        await asyncio.sleep(5)
        return "late"

    result = await session.run_stage_with_ack(never)

    assert result.applied is False and result.reason == "timeout"
    assert len(_acks(session)) == 1


@pytest.mark.parametrize("turn", [0, 1, 2, 3])
async def test_templates_rotate_so_the_voice_does_not_repeat_itself(turn: int) -> None:
    session, spoken, _ = _session()
    await _reasoning(session)
    session.turn_number = turn

    async def slow_model() -> str:
        await asyncio.sleep(DELAY * 3)
        return "x"

    await session.run_stage_with_ack(slow_model)

    assert spoken[0][2] == ACK_TEMPLATES[turn % len(ACK_TEMPLATES)]


async def test_acknowledgement_events_satisfy_the_session_event_contract() -> None:
    import json
    from pathlib import Path

    import jsonschema

    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "session-event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    session, _, _ = _session()
    await _reasoning(session)

    async def slow_model() -> str:
        await asyncio.sleep(5)
        return "x"

    stage = asyncio.create_task(session.run_stage_with_ack(slow_model))
    for _ in range(100):
        if _acks(session):
            break
        await asyncio.sleep(0.02)
    await session.interrupt()
    await stage

    events = [e.model_dump(mode="json") for e in session._history]  # noqa: SLF001
    relevant = [e for e in events if e["kind"] in ("tts.started", "tts.stopped")]
    assert len(relevant) == 2
    for event in relevant:
        jsonschema.validate(event, schema)
