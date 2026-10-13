"""Core endpoints the Finance page uses: privacy, conflicts, transaction source, test keystore."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.domains.kernel_loader import KernelUnavailableError, load_kernel
from reva_core.domains.keys import InMemoryKeyProvider, default_key_provider
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.errors import ConfigurationError
from tools.kernel.paired_devices import pair, push

try:
    binding = load_kernel()
except KernelUnavailableError as exc:
    pytest.skip(f"Domain Kernel binding not built: {exc}", allow_module_level=True)


def _client(tmp_path: Path, keys=None):
    settings = load_settings(
        _env_file=None, data_dir=tmp_path, assistant_orchestrator="deterministic"
    )
    core = CoreLifecycle(settings, domain_key_provider=keys or InMemoryKeyProvider())
    core.startup()
    client = TestClient(create_app(core))
    client.headers.update({"Authorization": f"Bearer {core.local_token}"})
    return core, client


@pytest.fixture
def api(tmp_path):
    core, client = _client(tmp_path)
    yield core, client
    core.shutdown()


def test_privacy_defaults_follow_the_adr(api):
    _, client = api
    body = client.get("/v1/domains/finance/privacy").json()
    assert body == {"domain": "finance", "privacy": {"sync": True, "hosted_model_access": False}}
    listed = client.get("/v1/domains").json()["domains"][0]["privacy"]
    assert listed == {"sync": True, "hosted_model_access": False}


def test_privacy_changes_persist_across_a_restart(tmp_path):
    keys = InMemoryKeyProvider()
    core, client = _client(tmp_path, keys)
    try:
        changed = client.patch(
            "/v1/domains/finance/privacy", json={"hosted_model_access": True}
        ).json()
        assert changed["privacy"] == {"sync": True, "hosted_model_access": True}
        client.patch("/v1/domains/finance/privacy", json={"sync": False})
    finally:
        core.shutdown()
    core2, client2 = _client(tmp_path, keys)
    try:
        assert client2.get("/v1/domains/finance/privacy").json()["privacy"] == {
            "sync": False,
            "hosted_model_access": True,
        }
        stored = json.loads((tmp_path / "domain_privacy.json").read_text("utf-8"))
        assert stored == {"finance": {"hosted_model_access": True, "sync": False}}
    finally:
        core2.shutdown()


def test_privacy_rejects_unknown_switches_non_booleans_and_empty_patches(api):
    _, client = api
    for body, field in [
        ({"shell_access": True}, "shell_access"),
        ({"sync": "yes"}, "sync"),
        ({"hosted_model_access": 1}, "hosted_model_access"),
    ]:
        response = client.patch("/v1/domains/finance/privacy", json=body)
        assert response.status_code == 422 and response.json()["field"] == field, body
    assert client.patch("/v1/domains/finance/privacy", json={}).status_code == 422
    assert client.get("/v1/domains/health/privacy").status_code == 404
    assert client.get("/v1/domains/finance/privacy").json()["privacy"] == {
        "sync": True,
        "hosted_model_access": False,
    }


def test_a_corrupt_privacy_file_falls_back_to_the_safe_defaults(tmp_path):
    (tmp_path / "domain_privacy.json").write_text("{not json", encoding="utf-8")
    core, client = _client(tmp_path)
    try:
        assert client.get("/v1/domains/finance/privacy").json()["privacy"] == {
            "sync": True,
            "hosted_model_access": False,
        }
    finally:
        core.shutdown()


def test_transactions_report_where_they_came_from(api):
    _, client = api
    client.post(
        "/v1/domains/finance/accounts",
        json={"id": "acct-main-1", "name": "Main", "currency": "USD"},
    )
    client.post(
        "/v1/domains/finance/transactions",
        json={
            "id": "tx-src-manual",
            "account_id": "acct-main-1",
            "date": "2026-10-01",
            "amount_minor": -1,
            "description": "m",
        },
    )
    client.post(
        "/v1/domains/finance/transactions",
        json={
            "id": "tx-src-voice1",
            "account_id": "acct-main-1",
            "date": "2026-10-01",
            "amount_minor": -2,
            "description": "v",
            "source": "voice",
        },
    )
    bad = client.post(
        "/v1/domains/finance/transactions",
        json={
            "account_id": "acct-main-1",
            "date": "2026-10-01",
            "amount_minor": -3,
            "description": "x",
            "source": "phone",
        },
    )
    assert bad.status_code == 422 and bad.json()["field"] == "source"
    kinds = {
        t["id"]: t["source_kind"]
        for t in client.get("/v1/domains/finance/transactions").json()["items"]
    }
    assert kinds == {"tx-src-manual": "manual", "tx-src-voice1": "voice"}


def test_conflicts_can_be_listed_and_resolved_over_http(api, tmp_path_factory):
    core, client = api
    client.post(
        "/v1/domains/finance/accounts",
        json={"id": "acct-main-1", "name": "Main", "currency": "USD"},
    )
    client.post(
        "/v1/domains/finance/transactions",
        json={
            "id": "tx-conflict1",
            "account_id": "acct-main-1",
            "date": "2026-10-01",
            "amount_minor": -5000,
            "description": "Corner Cafe",
        },
    )
    pc = core.domain_service.handle("finance")

    # A second "device" (a separate Kernel install) starts from the same history and diverges.
    phone_dir = tmp_path_factory.mktemp("phone")
    phone = binding.open_domain("finance", InMemoryKeyProvider(), str(phone_dir))
    pair(binding, pc, phone)
    push(pc, phone)
    client.patch("/v1/domains/finance/transactions/tx-conflict1", json={"amount_minor": -1111})
    phone.command("transaction.update", json.dumps({"id": "tx-conflict1", "amount_minor": -2222}))
    push(pc, phone)
    assert len(push(phone, pc).conflicts) == 1

    listed = client.get("/v1/domains/finance/conflicts").json()["items"]
    assert (
        len(listed) == 1 and listed[0]["label"] == "Corner Cafe" and listed[0]["currency"] == "USD"
    )
    cid = listed[0]["id"]
    assert (
        client.post(
            f"/v1/domains/finance/conflicts/{cid}/resolve", json={"keep": "everything"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/domains/finance/conflicts/9999/resolve", json={"keep": "local"}
        ).status_code
        == 404
    )

    resolved = client.post(f"/v1/domains/finance/conflicts/{cid}/resolve", json={"keep": "local"})
    assert resolved.status_code == 200
    assert (
        client.get("/v1/domains/finance/transactions/tx-conflict1").json()["item"]["amount_minor"]
        == -1111
    )
    assert client.get("/v1/domains/finance/conflicts").json()["items"] == []
    again = client.post(f"/v1/domains/finance/conflicts/{cid}/resolve", json={"keep": "remote"})
    assert again.status_code == 409


def test_memory_keystore_is_refused_outside_the_temp_directory(tmp_path):
    outside = Path.home() / "reva-not-temp-data"
    with pytest.raises(ConfigurationError):
        load_settings(_env_file=None, data_dir=outside, domain_keystore="memory")
    inside = load_settings(_env_file=None, data_dir=tmp_path, domain_keystore="memory")
    assert isinstance(default_key_provider(inside.domain_keystore), InMemoryKeyProvider)
    assert load_settings(_env_file=None, data_dir=outside).domain_keystore == "windows"
