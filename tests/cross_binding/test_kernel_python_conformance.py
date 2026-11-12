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


class _DeviceKey(binding.DeviceSigner):
    """A device key held by the Python host, signing with `cryptography` (what the Core will do)."""

    def __init__(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ec

        self._ec = ec
        self._key = ec.generate_private_key(ec.SECP256R1())

    def public_key(self) -> bytes:
        from cryptography.hazmat.primitives import serialization

        return self._key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def sign(self, message: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes

        return self._key.sign(bytes(message), self._ec.ECDSA(hashes.SHA256()))


def _paired_peer(handle) -> str:
    """Give `handle` a signing key and one registered peer, and return the peer's device id."""
    handle.set_signer(_DeviceKey())
    peer_id = "peer-device-0001"
    handle.register_peer(peer_id, _DeviceKey().public_key(), "Test phone", ["finance"])
    return peer_id


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
    with pytest.raises(binding.DomainError.Validation) as caught:
        binding.open_domain("unknown-domain", _Vault(), data_dir)
    assert caught.value.field == "domain"


def test_health_domain_is_available_through_python_binding(data_dir):
    import json

    handle = binding.open_domain("health", _Vault(), data_dir)
    summary = json.loads(handle.query("daily_summary", '{"date":"2026-10-19"}').rows_json)
    assert len(summary) == 1
    assert summary[0]["date"] == "2026-10-19"
    assert summary[0]["workout_count"] == 0
    with pytest.raises(binding.DomainError.Validation):
        handle.command("unsupported.command", "{}")


def test_health_backup_and_health_connect_import_through_python_binding(tmp_path):
    import json

    source = binding.open_domain("health", _Vault(), str(tmp_path / "a"))
    source.command("steps.log", '{"date":"2026-10-18","steps":5000}')
    days = {
        "format": "reva-health-connect-v1",
        "days": [
            {"date": "2026-10-18", "type": "steps", "steps": 7000, "origins": ["com.example.watch"]}
        ],
    }
    first = source.import_data("health_connect", json.dumps(days).encode(), "{}")
    again = source.import_data("health_connect", json.dumps(days).encode(), "{}")
    assert (first.accepted, again.accepted, again.duplicates) == (1, 0, 1)
    summary = json.loads(source.query("daily_summary", '{"date":"2026-10-18"}').rows_json)[0]
    assert summary["steps"] == 5000, "the manual entry is used and never added to Health Connect's"
    assert summary["steps_conflict"] is True
    assert summary["steps_health_connect"] == 7000

    restored = binding.open_domain("health", _Vault(), str(tmp_path / "b"))
    report = restored.import_data("json", source.export("json"), "{}")
    assert (report.accepted, len(report.rejected)) == (2, 0)
    assert restored.projection_digest() == source.projection_digest()


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
    peer = _paired_peer(handle)
    events = json.loads(handle.sync_export(peer, 100).events_json)
    assert len(events) == 6
    kinds = [e["kind"] for e in events]
    assert kinds == [
        "account.created", "category.created", "transaction.created", "transaction.updated",
        "transaction.deleted", "transaction.imported",
    ]  # fmt: skip
    for event in events:
        errors = list(validator.iter_errors(event))
        assert not errors, f"{event['kind']}: {[e.message for e in errors]}"
        assert event["signature"].startswith("es256:")
    assert [e["tombstone"] for e in events] == [False, False, False, False, True, False]


def test_events_signed_by_python_verify_in_the_kernel_on_another_device(data_dir):
    """ECDSA interop: `cryptography` DER signatures are accepted by the Kernel's verifier."""
    other_dir = tempfile.mkdtemp(prefix="reva-kernel-peer-")
    try:
        sender = binding.open_domain("finance", _Vault(), data_dir)
        receiver = binding.open_domain("finance", _Vault(), other_dir)
        sender_key, receiver_key = _DeviceKey(), _DeviceKey()
        sender.set_signer(sender_key)
        receiver.set_signer(receiver_key)
        sender.register_peer(receiver.device_id(), receiver_key.public_key(), "PC", ["finance"])
        receiver.register_peer(sender.device_id(), sender_key.public_key(), "Phone", ["finance"])
        sender.command("account.create", '{"id": "acct-main-1", "name": "Main", "currency": "USD"}')
        batch = sender.sync_export(receiver.device_id(), 100)
        report = receiver.sync_apply(sender.device_id(), batch)
        assert report.applied == 1
        assert sender.projection_digest() == receiver.projection_digest()
        # The same batch from a device that was never paired is refused.
        with pytest.raises(binding.DomainError.Rejected):
            receiver.sync_apply("stranger-device-1", batch)
    finally:
        shutil.rmtree(other_dir, ignore_errors=True)
