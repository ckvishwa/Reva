"""Domain Kernel through the generated Python binding (the path the Core uses).

Needs the built binding: python tools/kernel/build_bindings.py
(or REVA_KERNEL_BINDINGS=<dir with reva_kernel.py and the native library>).
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from tests.cross_binding import conformance_runner as runner

try:
    binding = runner.load_binding()
except (FileNotFoundError, OSError) as exc:  # missing binding or native library
    pytest.skip(f"Kernel Python binding not built: {exc}", allow_module_level=True)


def test_finance_conformance_suite_through_python():
    steps = runner.run_suite(binding)
    assert steps >= 90


class _Vault:
    def __init__(self) -> None:
        self.keys: dict[str, bytes] = {}

    def load_key(self, domain: str):
        return self.keys.get(domain)

    def store_key(self, domain: str, key: bytes) -> None:
        self.keys[domain] = bytes(key)


class _OfflineVault:
    def load_key(self, domain: str):
        raise binding.KeyProviderError.Unavailable("vault offline")

    def store_key(self, domain: str, key: bytes) -> None:
        raise binding.KeyProviderError.Unavailable("vault offline")


class _BuggyVault:
    def load_key(self, domain: str):
        raise RuntimeError("host bug")

    def store_key(self, domain: str, key: bytes) -> None:
        raise RuntimeError("host bug")


@pytest.fixture
def data_dir():
    path = tempfile.mkdtemp(prefix="reva-kernel-host-")
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_host_vault_failures_surface_as_locked(data_dir):
    for vault in (_OfflineVault(), _BuggyVault()):
        with pytest.raises(binding.DomainError.Locked):
            binding.open_domain("finance", vault, data_dir)


def test_wrong_and_missing_keys_are_typed_through_the_binding(data_dir):
    vault = _Vault()
    handle = binding.open_domain("finance", vault, data_dir)
    handle.command("account.create", '{"id": "acct-main-1", "name": "Main", "currency": "USD"}')
    del handle

    good = vault.keys["finance"]
    vault.keys["finance"] = b"\x07" * 32
    with pytest.raises(binding.DomainError.WrongKey):
        binding.open_domain("finance", vault, data_dir)
    del vault.keys["finance"]
    with pytest.raises(binding.DomainError.Locked):
        binding.open_domain("finance", vault, data_dir)
    vault.keys["finance"] = good
    assert binding.open_domain("finance", vault, data_dir).event_count() == 1


def test_unknown_domains_are_refused(data_dir):
    with pytest.raises(binding.DomainError.Validation):
        binding.open_domain("health", _Vault(), data_dir)


def test_validation_errors_carry_field_and_reason(data_dir):
    handle = binding.open_domain("finance", _Vault(), data_dir)
    with pytest.raises(binding.DomainError.Validation) as caught:
        handle.command("account.create", '{"name": "X", "currency": "usd"}')
    assert caught.value.field == "currency"


def test_emitted_events_validate_against_the_domain_event_contract(data_dir):
    import json
    from pathlib import Path

    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (Path(runner.REPO_ROOT) / "contracts" / "domain-event.schema.json").read_text("utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    handle = binding.open_domain("finance", _Vault(), data_dir)
    handle.command("account.create", '{"id": "acct-main-1", "name": "Main", "currency": "USD"}')
    handle.command("category.create", '{"id": "cat-food-01", "name": "Food"}')
    handle.command(
        "transaction.create",
        json.dumps(
            {
                "id": "tx-contract-1",
                "account_id": "acct-main-1",
                "date": "2026-10-01",
                "amount_minor": -5,
                "description": "x",
            }
        ),
    )
    handle.command("transaction.update", '{"id": "tx-contract-1", "amount_minor": -6}')
    handle.command("transaction.delete", '{"id": "tx-contract-1"}')
    handle.import_data(
        "csv",
        b"Date,Memo,Amount\n2026-10-02,Imported,-1.00\n",
        json.dumps(
            {
                "account_id": "acct-main-1",
                "mapping": {"date": "Date", "description": "Memo", "amount": "Amount"},
            }
        ),
    )
    events = json.loads(handle.pending_events(100).events_json)
    assert len(events) == 6
    kinds = [e["kind"] for e in events]
    assert kinds == [
        "account.created", "category.created", "transaction.created", "transaction.updated",
        "transaction.deleted", "transaction.imported",
    ]  # fmt: skip
    for event in events:
        errors = list(validator.iter_errors(event))
        assert not errors, f"{event['kind']}: {[e.message for e in errors]}"
    assert [e["tombstone"] for e in events] == [False, False, False, False, True, False]
