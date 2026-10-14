"""SYNC-1e: a per-domain change counter that screens can wait on.

The counter is bumped on every local commit and every applied sync batch (the call sites are
covered in tests/integration/test_domains_changes_api.py and tests/gateway/test_sync_changes.py).
This file covers the counter itself, with no Kernel needed.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.domains.service import DomainRequestError, DomainService


@pytest.fixture
def service(tmp_path):
    return DomainService(tmp_path, InMemoryKeyProvider())


def test_counters_start_at_zero_and_are_per_domain(service):
    assert service.change_counter("finance") == 0
    assert service.note_change("finance") == 1
    assert service.note_change("finance") == 2
    assert service.change_counter("finance") == 2


def test_an_unknown_domain_is_a_404_not_a_new_counter(service):
    with pytest.raises(DomainRequestError) as raised:
        service.change_counter("not-a-domain")
    assert raised.value.status == 404
    with pytest.raises(DomainRequestError):
        service.note_change("not-a-domain")


async def test_waiting_for_a_different_counter_returns_at_once(service):
    service.note_change("finance")

    started = time.monotonic()
    counter = await service.wait_for_change("finance", since=0, timeout=5.0)

    assert counter == 1
    assert time.monotonic() - started < 0.5


async def test_waiting_with_no_baseline_returns_the_current_counter_at_once(service):
    service.note_change("finance")
    assert await service.wait_for_change("finance", since=None, timeout=5.0) == 1


async def test_waiting_wakes_when_another_thread_commits(service):
    threading.Timer(0.2, service.note_change, args=("finance",)).start()

    started = time.monotonic()
    counter = await service.wait_for_change("finance", since=0, timeout=5.0)

    assert counter == 1
    assert 0.1 < time.monotonic() - started < 2.0


async def test_waiting_times_out_with_the_unchanged_counter(service):
    started = time.monotonic()
    counter = await service.wait_for_change("finance", since=0, timeout=0.3)

    assert counter == 0
    assert 0.25 < time.monotonic() - started < 1.5


async def test_a_counter_that_went_backwards_counts_as_a_change(service):
    """Core restarted: the client's baseline (57) is from the previous run. It must refresh."""
    assert await service.wait_for_change("finance", since=57, timeout=5.0) == 0


async def test_the_number_of_waiters_is_bounded(tmp_path):
    service = DomainService(tmp_path, InMemoryKeyProvider(), max_watchers=2)
    waiting = [
        asyncio.create_task(service.wait_for_change("finance", since=0, timeout=2.0))
        for _ in range(2)
    ]
    await asyncio.sleep(0.1)

    with pytest.raises(DomainRequestError) as raised:
        await service.wait_for_change("finance", since=0, timeout=2.0)
    assert (raised.value.code, raised.value.status) == ("too_many_watchers", 429)

    service.note_change("finance")
    assert await asyncio.gather(*waiting) == [1, 1]
    # Slots are released once the waiters finish.
    assert await service.wait_for_change("finance", since=0, timeout=2.0) == 1


async def test_a_cancelled_waiter_releases_its_slot(tmp_path):
    service = DomainService(tmp_path, InMemoryKeyProvider(), max_watchers=1)
    task = asyncio.create_task(service.wait_for_change("finance", since=0, timeout=30.0))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await service.wait_for_change("finance", since=5, timeout=0.2) == 0
