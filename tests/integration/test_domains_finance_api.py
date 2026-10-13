"""`/v1/domains/finance/*` and `/v1/today` through the real Rust Kernel (Python binding).

Needs the built binding (`python tools/kernel/build_bindings.py`). Uses an in-memory key
provider: these tests never touch the user's Windows Credential Manager entries.
"""

from __future__ import annotations

import base64
import json

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


@pytest.fixture
def keys():
    return InMemoryKeyProvider()


@pytest.fixture
def lifecycle(tmp_path, keys):
    settings = load_settings(
        _env_file=None, data_dir=tmp_path, assistant_orchestrator="deterministic"
    )
    core = CoreLifecycle(settings, domain_key_provider=keys)
    core.startup()
    yield core
    core.shutdown()


@pytest.fixture
def api(lifecycle):
    client = TestClient(create_app(lifecycle))
    client.headers.update({"Authorization": f"Bearer {lifecycle.local_token}"})
    return client


def _seed(api):
    assert (
        api.post(
            "/v1/domains/finance/accounts",
            json={
                "id": "acct-main-1",
                "name": "Main",
                "currency": "USD",
                "opening_balance_minor": 100000,
            },
        ).status_code
        == 201
    )
    assert (
        api.post(
            "/v1/domains/finance/categories",
            json={"id": "cat-food-01", "name": "Food", "aliases": ["groceries"]},
        ).status_code
        == 201
    )
    for i, (date, amount, desc) in enumerate(
        [
            ("2026-10-01", -1500, "Market"),
            ("2026-10-02", -2500, "Cafe"),
            ("2026-10-03", 5000, "Refund"),
        ]
    ):
        body = {
            "id": f"tx-api-{i:04d}",
            "account_id": "acct-main-1",
            "date": date,
            "amount_minor": amount,
            "description": desc,
        }
        if amount < 0:
            body["category"] = "groceries"
        assert api.post("/v1/domains/finance/transactions", json=body).status_code == 201


def test_domains_listing_reports_state_and_privacy(api):
    body = api.get("/v1/domains").json()
    finance = body["domains"][0]
    assert (
        finance["domain"] == "finance"
        and finance["state"] == "ready"
        and finance["schema_version"] == 2
    )
    assert finance["privacy"] == {"sync_default": True, "hosted_model_access": False}


def test_create_read_update_delete_round_trip(api):
    _seed(api)
    items = api.get("/v1/domains/finance/transactions").json()["items"]
    assert [i["id"] for i in items] == ["tx-api-0002", "tx-api-0001", "tx-api-0000"]

    one = api.get("/v1/domains/finance/transactions/tx-api-0001").json()["item"]
    assert one["amount_minor"] == -2500 and one["category_id"] == "cat-food-01"

    patched = api.patch(
        "/v1/domains/finance/transactions/tx-api-0001", json={"amount_minor": -2600}
    ).json()
    assert patched["version"] == 2
    assert (
        api.get("/v1/domains/finance/transactions/tx-api-0001").json()["item"]["amount_minor"]
        == -2600
    )

    deleted = api.delete("/v1/domains/finance/transactions/tx-api-0001")
    assert deleted.status_code == 200
    gone = api.get("/v1/domains/finance/transactions/tx-api-0001")
    assert gone.status_code == 410 and gone.json()["error"] == "deleted"
    missing = api.get("/v1/domains/finance/transactions/tx-nope-0001")
    assert missing.status_code == 404 and missing.json()["error"] == "not_found"


def test_list_filters_and_pagination(api):
    _seed(api)
    assert [
        i["id"]
        for i in api.get("/v1/domains/finance/transactions", params={"q": "cafe"}).json()["items"]
    ] == ["tx-api-0001"]
    page = api.get("/v1/domains/finance/transactions", params={"limit": 1, "offset": 1}).json()[
        "items"
    ]
    assert [i["id"] for i in page] == ["tx-api-0001"]
    bad = api.get("/v1/domains/finance/transactions", params={"limit": "many"})
    assert bad.status_code == 422 and bad.json()["field"] == "limit"


def test_reports_are_computed_by_the_kernel(api):
    _seed(api)
    spend = api.get(
        "/v1/domains/finance/reports/spend_by_category", params={"period": "2026-10"}
    ).json()
    assert spend["rows"][0]["category"] == "Food" and spend["rows"][0]["spent_minor"] == 4000
    assert sorted(spend["source_ids"]) == ["tx-api-0000", "tx-api-0001"]
    balances = api.get(
        "/v1/domains/finance/reports/account_balances", params={"as_of": "2026-10-31"}
    ).json()["rows"]
    assert balances[0]["balance_minor"] == 100000 - 1500 - 2500 + 5000
    assert api.get("/v1/domains/finance/reports/drop_everything").status_code == 404


def test_validation_and_conflict_errors_keep_a_safe_shape(api):
    r = api.post("/v1/domains/finance/accounts", json={"name": "X", "currency": "usd"})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error" and r.json()["field"] == "currency"
    assert "traceback" not in r.text.lower()
    api.post(
        "/v1/domains/finance/accounts",
        json={"id": "acct-main-1", "name": "Main", "currency": "USD"},
    )
    dupe = api.post(
        "/v1/domains/finance/accounts",
        json={"id": "acct-main-1", "name": "Other", "currency": "USD"},
    )
    assert dupe.status_code == 409 and dupe.json()["error"] == "conflict"
    assert api.get("/v1/domains/health/accounts").status_code == 404
    assert api.get("/v1/domains/finance/nonsense").status_code == 404


def test_account_archive_through_patch_and_bill_mark_paid(api):
    _seed(api)
    archived = api.patch("/v1/domains/finance/accounts/acct-main-1", json={"archived": True})
    assert archived.status_code == 200
    blocked = api.post(
        "/v1/domains/finance/transactions",
        json={
            "account_id": "acct-main-1",
            "date": "2026-10-04",
            "amount_minor": -1,
            "description": "x",
        },
    )
    assert blocked.status_code == 409
    api.patch("/v1/domains/finance/accounts/acct-main-1", json={"archived": False})
    api.post(
        "/v1/domains/finance/bills",
        json={
            "id": "bill-api-0001",
            "name": "Power",
            "amount_minor": 7000,
            "currency": "USD",
            "due_date": "2026-10-20",
            "recurrence": "monthly",
            "account_id": "acct-main-1",
        },
    )
    paid = api.post(
        "/v1/domains/finance/bills/bill-api-0001/mark-paid",
        json={"paid_date": "2026-10-20", "record_transaction": True},
    )
    assert paid.status_code == 200 and paid.json()["version"] == 2
    bill = api.get("/v1/domains/finance/bills/bill-api-0001").json()["item"]
    assert bill["due_date"] == "2026-11-20" and bill["last_paid_date"] == "2026-10-20"
    assert any(
        t["description"] == "Power"
        for t in api.get("/v1/domains/finance/transactions").json()["items"]
    )


def test_today_summarises_enabled_domains_only(api):
    _seed(api)
    api.post(
        "/v1/domains/finance/budgets",
        json={
            "category_id": "cat-food-01",
            "amount_minor": 10000,
            "currency": "USD",
            "start_month": "2026-01",
        },
    )
    api.post(
        "/v1/domains/finance/bills",
        json={
            "id": "bill-api-0002",
            "name": "Phone",
            "amount_minor": 3000,
            "currency": "USD",
            "due_date": "2026-10-14",
            "recurrence": "monthly",
        },
    )
    today = api.get("/v1/today", params={"as_of": "2026-10-12"}).json()
    finance = today["domains"]["finance"]
    assert today["as_of"] == "2026-10-12" and list(today["domains"]) == ["finance"]
    assert finance["budget_left_this_month"] == [
        {"currency": "USD", "budget_minor": 10000, "spent_minor": 4000, "remaining_minor": 6000}
    ]
    assert [b["name"] for b in finance["bills_due_7_days"]] == ["Phone"]
    assert api.get("/v1/today", params={"as_of": "12/10/2026"}).status_code == 422


def test_import_and_export_over_http(api):
    api.post(
        "/v1/domains/finance/accounts",
        json={"id": "acct-main-1", "name": "Main", "currency": "USD"},
    )
    csv_text = "Date,Memo,Amount\n2026-10-01,Coffee,-3.50\nbad,Row,1.00\n2026-10-02,Lunch,-9.25\n"
    request = {
        "format": "csv",
        "data_base64": base64.b64encode(csv_text.encode()).decode(),
        "options": {
            "account_id": "acct-main-1",
            "mapping": {"date": "Date", "description": "Memo", "amount": "Amount"},
            "dry_run": True,
        },
    }
    dry = api.post("/v1/domains/finance/import", json=request).json()
    assert (dry["accepted"], dry["dry_run"], len(dry["rejected"])) == (2, True, 1)
    assert api.get("/v1/domains/finance/transactions").json()["items"] == [], (
        "dry run wrote nothing"
    )

    request["options"]["dry_run"] = False
    real = api.post("/v1/domains/finance/import", json=request).json()
    assert real["accepted"] == 2 and real["rejected"][0]["row"] == 3
    assert len(real["rows"]) == 3
    again = api.post("/v1/domains/finance/import", json=request).json()
    assert (again["accepted"], again["duplicates"]) == (0, 2)

    csv_export = api.get("/v1/domains/finance/export", params={"format": "csv"})
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert (
        "attachment" in csv_export.headers["content-disposition"]
        and csv_export.headers["cache-control"] == "no-store"
    )
    assert "Lunch" in csv_export.text
    dump = api.get("/v1/domains/finance/export", params={"format": "json"}).json()
    assert dump["format"] == "reva-finance-export" and len(dump["transactions"]) == 2

    bad = api.post(
        "/v1/domains/finance/import", json={"format": "csv", "data_base64": "!!!", "options": {}}
    )
    assert bad.status_code == 422
    assert (
        api.post(
            "/v1/domains/finance/import",
            json={"format": "xls", "data_base64": "AA==", "options": {}},
        ).status_code
        == 422
    )


def test_a_locked_vault_returns_423_and_core_still_serves_other_routes(tmp_path):
    class LockedVault:
        def load_key(self, domain):
            raise RuntimeError("vault offline")

        def store_key(self, domain, key):
            raise RuntimeError("vault offline")

    settings = load_settings(
        _env_file=None, data_dir=tmp_path, assistant_orchestrator="deterministic"
    )
    core = CoreLifecycle(settings, domain_key_provider=LockedVault())
    core.startup()
    try:
        client = TestClient(create_app(core))
        client.headers.update({"Authorization": f"Bearer {core.local_token}"})
        locked = client.get("/v1/domains/finance/accounts")
        assert locked.status_code == 423 and locked.json()["error"] == "domain_locked"
        assert client.get("/v1/domains").json()["domains"][0]["state"] == "domain_locked"
        assert client.get("/health").status_code == 200
        assert not (tmp_path / "domains" / "finance.sqlite3").exists()
    finally:
        core.shutdown()


def test_data_lives_under_the_data_dir_and_survives_a_restart(tmp_path, keys):
    settings = load_settings(
        _env_file=None, data_dir=tmp_path, assistant_orchestrator="deterministic"
    )
    first = CoreLifecycle(settings, domain_key_provider=keys)
    first.startup()
    client = TestClient(create_app(first))
    client.headers.update({"Authorization": f"Bearer {first.local_token}"})
    client.post(
        "/v1/domains/finance/accounts",
        json={"id": "acct-main-1", "name": "Main", "currency": "USD"},
    )
    first.shutdown()
    assert (tmp_path / "domains" / "finance.sqlite3").exists()

    second = CoreLifecycle(settings, domain_key_provider=keys)
    second.startup()
    try:
        client = TestClient(create_app(second))
        client.headers.update({"Authorization": f"Bearer {second.local_token}"})
        assert [a["id"] for a in client.get("/v1/domains/finance/accounts").json()["items"]] == [
            "acct-main-1"
        ]
    finally:
        second.shutdown()
    raw = (tmp_path / "domains" / "finance.sqlite3").read_bytes()
    assert b"SQLite format 3" not in raw[:32] and b"Main" not in raw, (
        "the data file is encrypted at rest"
    )
    assert json.dumps(sorted(keys.keys)) == '["finance"]'
