"""B4: every buffer has a bound and a defined behaviour at the bound (AR-CORE-012)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.models.tts import SynthesizedAudio
from reva_core.policy.authorize import Proposal
from reva_core.policy.broker import MAX_OPEN, Broker, BrokerFull
from reva_core.policy.grants import ReplayCache, load_or_create_signer
from reva_core.policy.ledger import MemoryLedger
from reva_core.session.coordinator import DeadlineConfig, SessionCoordinator
from reva_core.session.events import EventSubscription, SessionEvent, SessionEventKind
from reva_core.session.pipeline import AudioStore

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def event(kind: SessionEventKind, n: int) -> SessionEvent:
    return SessionEvent(
        event_id=f"e{n}",
        sequence=n,
        timestamp=NOW,
        device_id="device-0001",
        session_id="s1",
        turn_id="t1",
        turn_epoch=0,
        correlation_id="c1",
        kind=kind,
        payload={"n": n},
    )


# ------------------------------------------------------------ event subscription


def test_a_full_subscription_drops_droppable_events_before_anything_essential() -> None:
    subscription = EventSubscription(maxsize=4)
    subscription.put(event(SessionEventKind.SESSION_STATE, 0))
    for n in range(1, 4):
        subscription.put(event(SessionEventKind.TRANSCRIPT_PARTIAL, n))

    subscription.put(event(SessionEventKind.SESSION_STATE, 4))  # needs room: a partial goes

    kept = [e.sequence for e in drain(subscription)]
    assert 0 in kept and 4 in kept and len(kept) == 4
    assert not subscription.closed and not subscription.overrun


def test_a_full_subscription_of_essential_events_is_closed_not_grown() -> None:
    subscription = EventSubscription(maxsize=3)
    for n in range(3):
        subscription.put(event(SessionEventKind.SESSION_STATE, n))

    subscription.put(event(SessionEventKind.SESSION_STATE, 3))

    assert subscription.closed and subscription.overrun
    assert len(drain(subscription)) == 3  # nothing was added beyond the bound
    subscription.put(event(SessionEventKind.SESSION_STATE, 9))
    assert subscription.empty()


def test_an_endless_stream_never_makes_a_subscription_longer_than_its_bound() -> None:
    subscription = EventSubscription(maxsize=8)

    for n in range(5000):
        subscription.put(event(SessionEventKind.ASSISTANT_TEXT_DELTA, n))

    assert len(drain(subscription)) == 8


def drain(subscription: EventSubscription) -> list[SessionEvent]:
    items = []
    while not subscription.empty():
        items.append(asyncio.run(subscription.get()))  # type: ignore[arg-type]
    return [i for i in items if i is not None]


def test_session_history_for_replay_is_bounded() -> None:
    coordinator = SessionCoordinator(
        deadlines=DeadlineConfig(stt=2.0, model=2.0, tool=2.0, tts=2.0), ack_delay_seconds=30.0
    )
    session = coordinator.open("device-0001")

    for _ in range(500):
        session.emit(SessionEventKind.ERROR, {"code": "X", "recoverable": True, "stage": None})

    late = session.subscribe(replay=True)
    assert len(drain(late)) <= 64


def test_sessions_are_capped() -> None:
    coordinator = SessionCoordinator(
        deadlines=DeadlineConfig(stt=2.0, model=2.0, tool=2.0, tts=2.0),
        ack_delay_seconds=30.0,
        max_sessions=2,
    )
    coordinator.open("device-0001")
    coordinator.open("device-0001")

    with pytest.raises(Exception, match="(?i)too many|limit|session"):
        coordinator.open("device-0001")


# ------------------------------------------------------------------- audio store


def test_the_audio_store_deletes_the_oldest_file_beyond_four(tmp_path: Path) -> None:
    store = AudioStore(max_items=4)
    ids = []
    paths = []
    for n in range(7):
        path = tmp_path / f"a{n}.wav"
        path.write_bytes(b"x")
        paths.append(path)
        ids.append(
            store.put(
                SynthesizedAudio(
                    path=path, sample_rate=24000, duration_ms=10, provider="t", language="en"
                )
            )
        )

    assert [p.exists() for p in paths] == [False, False, False, True, True, True, True]
    assert store.path(ids[0]) is None and store.path(ids[-1]) == paths[-1]


# -------------------------------------------------------------------- the broker


def make_broker() -> Broker:
    return Broker(
        signer=load_or_create_signer(InMemoryKeyProvider()),
        ledger=MemoryLedger(),
        clock=lambda: NOW,
    )


def test_waiting_actions_are_capped_and_the_next_one_is_a_clean_refusal() -> None:
    broker = make_broker()
    for n in range(MAX_OPEN):
        broker.propose(Proposal(f"act-{n:08d}", "windows.app.close", {"app_key": "notepad"}))

    with pytest.raises(BrokerFull):
        broker.propose(Proposal("act-99999999", "windows.app.close", {"app_key": "notepad"}))


def test_used_grant_keys_are_bounded() -> None:
    cache = ReplayCache(capacity=100)

    for n in range(1000):
        cache.mark(f"key-{n}")

    assert len(cache._seen) == 100
    assert cache.seen("key-999") and not cache.seen("key-0")
