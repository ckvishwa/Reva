"""`GET /v1/domains/changes`: the long-poll a screen waits on, and what bumps its counter."""

from __future__ import annotations

import base64
import threading
import time

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.domains.kernel_loader import KernelUnavailableError, load_kernel
from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.orchestration.lifecycle import CoreLifecycle

try:
    load_kernel()
except KernelUnavailableError as exc:
    pytest.skip(f"Domain Kernel binding not built: {exc}", allow_module_level=True)

ACCOUNT = {"id": "acct-main-1", "name": "Main", "currency": "USD", "opening_balance_minor": 1000}
CSV = "Date,Memo,Amount\n2026-10-01,Coffee,-3.50\n2026-10-02,Lunch,-9.25\n"


@pytest.fixture
def lifecycle(tmp_path):
    settings = load_settings(
        _env_file=None, data_dir=tmp_path, assistant_orchestrator="deterministic"
    )
    core = CoreLifecycle(settings, domain_key_provider=InMemoryKeyProvider())
    core.startup()
    yield core
    core.shutdown()


@pytest.fixture
def api(lifecycle):
    client = TestClient(create_app(lifecycle))
    client.headers.update({"Authorization": f"Bearer {lifecycle.local_token}"})
    return client


def _counter(api, **params) -> int:
    reply = api.get("/v1/domains/changes", params={"domain": "finance", **params})
    assert reply.status_code == 200, reply.text
    return int(reply.json()["counter"])


def _expense(ident: str, amount: int = -500) -> dict:
    return {
        "id": ident,
        "account_id": "acct-main-1",
        "date": "2026-10-01",
        "amount_minor": amount,
        "description": f"Expense {ident}",
    }


def test_the_route_requires_the_bearer_token(lifecycle):
    bare = TestClient(create_app(lifecycle))
    assert bare.get("/v1/domains/changes").status_code == 401
    assert (
        bare.get("/v1/domains/changes", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


def test_the_reply_names_the_domain_the_counter_and_whether_it_changed(api):
    body = api.get("/v1/domains/changes", params={"domain": "finance"}).json()

    assert body["domain"] == "finance"
    assert body["counter"] == 0
    assert body["changed"] is True, "no baseline given: the caller should load once"

    again = api.get("/v1/domains/changes", params={"domain": "finance", "since": 0, "timeout": 0})
    assert again.json()["changed"] is False


def test_unknown_domains_and_bad_parameters_are_refused(api):
    assert api.get("/v1/domains/changes", params={"domain": "nope"}).status_code == 404
    assert api.get("/v1/domains/changes", params={"since": -1}).status_code == 422
    assert api.get("/v1/domains/changes", params={"timeout": 31}).status_code == 422
    assert api.get("/v1/domains/changes", params={"timeout": -1}).status_code == 422
    assert api.get("/v1/domains/changes", params={"since": "x"}).status_code == 422


def test_each_local_commit_bumps_the_counter(api):
    start = _counter(api)

    assert api.post("/v1/domains/finance/accounts", json=ACCOUNT).status_code == 201
    assert _counter(api) == start + 1

    assert (
        api.post("/v1/domains/finance/transactions", json=_expense("tx-alpha-01")).status_code
        == 201
    )
    assert _counter(api) == start + 2

    assert (
        api.patch(
            "/v1/domains/finance/transactions/tx-alpha-01", json={"amount_minor": -700}
        ).status_code
        == 200
    )
    assert _counter(api) == start + 3

    assert api.delete("/v1/domains/finance/transactions/tx-alpha-01").status_code == 200
    assert _counter(api) == start + 4


def test_a_refused_command_changes_nothing(api):
    api.post("/v1/domains/finance/accounts", json=ACCOUNT)
    before = _counter(api)

    refused = api.post(
        "/v1/domains/finance/transactions", json={**_expense("tx-bad-0001"), "date": "x"}
    )
    assert refused.status_code >= 400
    assert api.get("/v1/domains/finance/transactions/does-not-exist").status_code == 404

    assert _counter(api) == before


def test_reads_do_not_bump_the_counter(api):
    api.post("/v1/domains/finance/accounts", json=ACCOUNT)
    before = _counter(api)

    for path in (
        "/v1/domains/finance/transactions",
        "/v1/domains/finance/conflicts",
        "/v1/domains/finance/reports/account_balances",
        "/v1/today",
        "/v1/domains",
    ):
        assert api.get(path).status_code == 200, path

    assert _counter(api) == before


def test_an_import_bumps_only_when_it_writes(api):
    api.post("/v1/domains/finance/accounts", json=ACCOUNT)
    request = {
        "format": "csv",
        "data_base64": base64.b64encode(CSV.encode()).decode(),
        "options": {
            "account_id": "acct-main-1",
            "mapping": {"date": "Date", "description": "Memo", "amount": "Amount"},
            "dry_run": True,
        },
    }
    before = _counter(api)

    assert api.post("/v1/domains/finance/import", json=request).status_code == 200
    assert _counter(api) == before, "a dry run writes nothing"

    request["options"]["dry_run"] = False
    assert api.post("/v1/domains/finance/import", json=request).json()["accepted"] == 2
    assert _counter(api) == before + 1

    assert api.post("/v1/domains/finance/import", json=request).json()["accepted"] == 0
    assert _counter(api) == before + 1, "all duplicates: nothing changed"


def test_the_long_poll_wakes_when_something_commits(api):
    api.post("/v1/domains/finance/accounts", json=ACCOUNT)
    baseline = _counter(api)

    def commit_soon() -> None:
        time.sleep(0.4)
        api.post("/v1/domains/finance/transactions", json=_expense("tx-wake-001"))

    worker = threading.Thread(target=commit_soon)
    worker.start()
    started = time.monotonic()
    reply = api.get(
        "/v1/domains/changes", params={"domain": "finance", "since": baseline, "timeout": 10}
    )
    elapsed = time.monotonic() - started
    worker.join()

    assert reply.status_code == 200
    assert reply.json() == {"domain": "finance", "counter": baseline + 1, "changed": True}
    assert 0.3 < elapsed < 5.0, f"woke after {elapsed:.2f}s"


def test_the_long_poll_returns_unchanged_after_its_timeout(api):
    baseline = _counter(api)

    started = time.monotonic()
    reply = api.get(
        "/v1/domains/changes", params={"domain": "finance", "since": baseline, "timeout": 1}
    )

    assert reply.json()["changed"] is False
    assert 0.8 < time.monotonic() - started < 4.0


def test_the_reply_carries_no_data_and_is_not_cached(api):
    api.post("/v1/domains/finance/accounts", json=ACCOUNT)
    reply = api.get("/v1/domains/changes", params={"domain": "finance"})

    assert set(reply.json()) == {"domain", "counter", "changed"}
    assert reply.headers.get("cache-control") == "no-store"
