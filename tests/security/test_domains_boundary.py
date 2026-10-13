"""Auth, architecture and credential-vault rules for the Domain Kernel integration."""

from __future__ import annotations

import ast
import re
import sys
import uuid
from pathlib import Path

import pytest

from reva_core.domains import keys as keys_module
from reva_core.domains.keys import (
    InMemoryKeyProvider,
    KeyStoreError,
    WindowsCredentialKeyProvider,
    entry_name,
)

ROOT = Path(__file__).resolve().parents[2]
DOMAINS_PACKAGE = ROOT / "reva_core" / "domains"

ROUTES = [
    ("get", "/v1/domains", {}),
    ("get", "/v1/domains/finance/accounts", {}),
    ("post", "/v1/domains/finance/accounts", {"json": {"name": "x", "currency": "USD"}}),
    ("get", "/v1/domains/finance/accounts/acct-main-1", {}),
    ("patch", "/v1/domains/finance/accounts/acct-main-1", {"json": {"name": "y"}}),
    ("delete", "/v1/domains/finance/accounts/acct-main-1", {}),
    ("get", "/v1/domains/finance/reports/spend_by_category", {"params": {"period": "2026-10"}}),
    ("get", "/v1/domains/finance/export", {}),
    (
        "post",
        "/v1/domains/finance/import",
        {"json": {"format": "csv", "data_base64": "AA==", "options": {}}},
    ),
    (
        "post",
        "/v1/domains/finance/bills/bill-api-0001/mark-paid",
        {"json": {"paid_date": "2026-10-20"}},
    ),
    ("get", "/v1/today", {}),
    ("get", "/v1/domains/finance/privacy", {}),
    ("patch", "/v1/domains/finance/privacy", {"json": {"sync": False}}),
    ("get", "/v1/domains/finance/conflicts", {}),
    ("post", "/v1/domains/finance/conflicts/1/resolve", {"json": {"keep": "local"}}),
]


@pytest.mark.parametrize("method,path,kwargs", ROUTES)
def test_every_domain_route_rejects_missing_auth(client, method, path, kwargs):
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401
    assert "acct-main-1" not in response.text


@pytest.mark.parametrize("method,path,kwargs", ROUTES)
def test_every_domain_route_rejects_a_wrong_token(client, method, path, kwargs):
    response = getattr(client, method)(
        path, headers={"Authorization": "Bearer not-the-token"}, **kwargs
    )
    assert response.status_code == 401


def test_domains_package_contains_no_sql_and_no_database_access():
    forbidden_imports = {"sqlite3", "sqlalchemy", "psycopg2", "psycopg", "apsw"}
    sql = re.compile(
        r"\b(SELECT\s.+\sFROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b",
        re.I | re.S,
    )
    files = sorted(DOMAINS_PACKAGE.glob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            assert not (set(names) & forbidden_imports), f"{path.name} imports a database module"
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) > 12
            ):
                assert not sql.search(node.value), f"{path.name} contains SQL: {node.value[:40]!r}"


def test_domains_package_has_no_network_clients():
    for path in DOMAINS_PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in (
            "import requests",
            "import httpx",
            "import socket",
            "urllib.request",
            "aiohttp",
        ):
            assert needle not in text, f"{path.name}: {needle}"


def test_legacy_aura_credential_entry_is_never_addressable():
    with pytest.raises(KeyStoreError):
        entry_name("finance", prefix="com.aura.assistant.")
    assert entry_name("finance") == "reva.domain.finance"
    for bad in ("", "Finance", "a/b", "x y", "../x"):
        with pytest.raises(KeyStoreError):
            entry_name(bad)
    source = (DOMAINS_PACKAGE / "keys.py").read_text(encoding="utf-8")
    assert (
        "CredDeleteW" in source and "com.aura" in source
    )  # the guard exists next to the delete call


def test_in_memory_provider_never_replaces_an_existing_key():
    provider = InMemoryKeyProvider()
    provider.store_key("finance", b"a" * 32)
    with pytest.raises(KeyStoreError):
        provider.store_key("finance", b"b" * 32)
    assert provider.load_key("finance") == b"a" * 32


def test_tests_cannot_reach_the_real_vault_through_the_default_provider():
    provider = keys_module.default_key_provider()
    with pytest.raises(KeyStoreError):
        provider.load_key("finance")


@pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="Windows Credential Manager only exists on Windows"
)
def test_windows_credential_manager_round_trip_with_a_throwaway_entry():
    prefix = f"reva.test.{uuid.uuid4().hex[:12]}."
    provider = WindowsCredentialKeyProvider(prefix=prefix)
    assert provider.load_key("finance") is None
    key = bytes(range(32))
    try:
        provider.store_key("finance", key)
        assert provider.load_key("finance") == key
        with pytest.raises(KeyStoreError):
            provider.store_key("finance", b"\x01" * 32)  # never replaces an existing key
        assert provider.load_key("finance") == key
    finally:
        assert provider.delete_key("finance") is True
    assert provider.load_key("finance") is None
    assert provider.delete_key("finance") is False


@pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="Windows Credential Manager only exists on Windows"
)
def test_windows_provider_rejects_bad_prefixes_and_bad_keys():
    with pytest.raises(KeyStoreError):
        WindowsCredentialKeyProvider(prefix="com.aura.assistant.")
    provider = WindowsCredentialKeyProvider(prefix=f"reva.test.{uuid.uuid4().hex[:12]}.")
    with pytest.raises(KeyStoreError):
        provider.store_key("finance", b"short")
