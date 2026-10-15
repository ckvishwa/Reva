"""Secret strings in Windows Credential Manager (and the stores tests may use instead)."""

from __future__ import annotations

import sys
import uuid

import pytest

from reva_core.security.credential_store import (
    InMemorySecretStore,
    SecretStoreError,
    UnavailableSecretStore,
    WindowsSecretStore,
    check_secret,
    default_secret_store,
)


@pytest.mark.parametrize("bad", ["", " ", "a b", "tab\there", "nul\x00", "x" * 513])
def test_unusable_secrets_are_refused(bad: str) -> None:
    with pytest.raises(SecretStoreError):
        check_secret(bad)
    with pytest.raises(SecretStoreError):
        InMemorySecretStore().write(bad)


def test_the_in_memory_store_round_trips() -> None:
    store = InMemorySecretStore()
    assert store.read() is None and store.delete() is False
    store.write("sk-ant-abc")
    assert store.read() == "sk-ant-abc"
    assert store.delete() is True and store.read() is None


def test_under_pytest_the_default_store_is_closed() -> None:
    store = default_secret_store("anthropic")

    assert isinstance(store, UnavailableSecretStore)
    for call in (store.read, store.delete):
        with pytest.raises(SecretStoreError):
            call()
    with pytest.raises(SecretStoreError):
        store.write("sk-ant-abc")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows Credential Manager")
def test_windows_credential_manager_round_trip_on_a_throwaway_entry() -> None:
    store = WindowsSecretStore(f"test-{uuid.uuid4().hex[:12]}")  # reva.provider.test-... only
    try:
        assert store.read() is None
        store.write("sk-ant-throwaway-0123456789")
        assert store.read() == "sk-ant-throwaway-0123456789"
        store.write("sk-ant-replaced-0123456789")  # replacing is allowed for a rotated key
        assert store.read() == "sk-ant-replaced-0123456789"
        assert store.delete() is True
        assert store.read() is None and store.delete() is False
    finally:
        store.delete()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows Credential Manager")
@pytest.mark.parametrize("name", ["", "has space", "../escape", "a;b"])
def test_windows_store_refuses_odd_names(name: str) -> None:
    with pytest.raises(SecretStoreError):
        WindowsSecretStore(name)
