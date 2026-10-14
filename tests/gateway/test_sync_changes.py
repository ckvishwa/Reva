"""SYNC-1e: an applied sync batch bumps the Finance change counter, so an open screen reloads."""

from __future__ import annotations

from tests.gateway.conftest import Env
from tests.gateway.phone import Phone


def _paired(env: Env) -> Phone:
    env.enable()
    phone = env.new_phone()
    env.pair(phone)
    return phone


def _counter(env: Env) -> int:
    return env.lifecycle.domain_service.change_counter("finance")


def test_a_pushed_batch_that_applies_events_bumps_the_counter(env: Env) -> None:
    phone = _paired(env)
    env.add_account(phone.kernel)
    env.add_expense(phone.kernel, "tx-phone-001", -1200)
    before = _counter(env)

    reply = phone.push()

    assert reply.status == 200 and reply.json()["applied"] == 2
    assert _counter(env) == before + 1, "one batch is one change, however many events it holds"


def test_a_resent_batch_with_nothing_new_does_not_bump_it(env: Env) -> None:
    phone = _paired(env)
    env.add_account(phone.kernel)
    assert phone.push().status == 200
    after_first = _counter(env)

    phone.kernel.reset_peer_cursors(phone.pc_kernel_id)  # the phone resends everything
    again = phone.push()

    assert again.status == 200 and again.json()["applied"] == 0
    assert _counter(env) == after_first


def test_a_refused_request_does_not_bump_it(env: Env) -> None:
    phone = _paired(env)
    env.add_account(phone.kernel)
    before = _counter(env)

    refused = phone.push(timestamp=1)  # far outside the allowed clock skew

    assert refused.status == 401
    assert _counter(env) == before


def test_a_pull_changes_nothing_on_the_pc(env: Env) -> None:
    phone = _paired(env)
    env.add_account(env.pc_kernel())
    before = _counter(env)

    reply, _ = phone.pull()

    assert reply.status == 200
    assert _counter(env) == before
