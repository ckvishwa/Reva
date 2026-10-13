"""A Core with the gateway enabled on 127.0.0.1, an in-memory vault and temp directories only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.domains.kernel_loader import KernelUnavailableError, load_kernel
from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.orchestration.lifecycle import CoreLifecycle
from tests.gateway.phone import Phone


@dataclass
class Env:
    lifecycle: CoreLifecycle
    client: TestClient
    tmp_path: Path
    clock: list[float]
    phones: list[Phone] = field(default_factory=list)
    gateway_keys: InMemoryKeyProvider = field(default_factory=InMemoryKeyProvider)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.lifecycle.local_token}"}

    @property
    def manager(self) -> Any:
        return self.lifecycle.gateway

    def enable(self) -> dict[str, Any]:
        reply = self.client.patch(
            "/v1/devices/gateway", json={"enabled": True}, headers=self.headers
        )
        assert reply.status_code == 200, reply.text
        status: dict[str, Any] = reply.json()["gateway"]
        return status

    def new_phone(self, name: str = "Test phone") -> Phone:
        directory = self.tmp_path / f"phone-{len(self.phones)}"
        phone = Phone(directory, name)
        phone.clock = lambda: self.clock[0]
        self.phones.append(phone)
        return phone

    def open_pairing(self) -> dict[str, Any]:
        reply = self.client.post("/v1/devices/pairing", headers=self.headers)
        assert reply.status_code == 200, reply.text
        opened: dict[str, Any] = reply.json()
        return opened

    def pair(self, phone: Phone) -> str:
        """The whole happy path: QR, scan, compare digits, approve on the PC, take the grant."""
        qr = self.open_pairing()["qr_text"]
        started = phone.start_pairing(qr)
        assert started.status == 200, started.body
        session_id = started.json()["session_id"]
        shown = self.pairing_view()["fingerprint"]
        assert shown == phone.expected_fingerprint(session_id)
        approved = self.client.post(
            "/v1/devices/pairing/approve", json={"fingerprint": shown}, headers=self.headers
        )
        assert approved.status_code == 200, approved.text
        done = phone.poll_pairing(session_id)
        assert done.status == 200, done.body
        phone.finish_pairing(done)
        assert phone.device_id is not None
        return phone.device_id

    def pairing_view(self) -> dict[str, Any]:
        listing = self.client.get("/v1/devices", headers=self.headers).json()
        view: dict[str, Any] = listing["gateway"]["pairing"]
        return view

    def pc_kernel(self) -> Any:
        return self.lifecycle.domain_service.handle("finance")

    def add_account(self, handle: Any, ident: str = "acct-main-1") -> None:
        handle.command(
            "account.create", json.dumps({"id": ident, "name": "Main", "currency": "USD"})
        )

    def add_expense(
        self, handle: Any, ident: str, amount: int, account: str = "acct-main-1"
    ) -> None:
        handle.command(
            "transaction.create",
            json.dumps(
                {
                    "id": ident,
                    "account_id": account,
                    "date": "2026-10-01",
                    "amount_minor": amount,
                    "description": f"Expense {ident}",
                }
            ),
        )


def build_env(tmp_path: Path) -> Env:
    try:
        load_kernel()
    except KernelUnavailableError as exc:  # needs tools/kernel/build_bindings.py
        pytest.skip(f"Domain Kernel binding not built: {exc}")
    settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "core",
        domain_keystore="memory",
        gateway_host="127.0.0.1",
        gateway_port=0,
    )
    keys = InMemoryKeyProvider()
    lifecycle = CoreLifecycle(
        settings, domain_key_provider=InMemoryKeyProvider(), gateway_key_provider=keys
    )
    lifecycle.startup()
    clock = [1_800_000_000.0]
    lifecycle.gateway._now = lambda: clock[0]  # noqa: SLF001 - tests move time
    client = TestClient(create_app(lifecycle))
    env = Env(lifecycle=lifecycle, client=client, tmp_path=tmp_path, clock=clock)
    env.gateway_keys = keys
    return env


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    holder = build_env(tmp_path)
    try:
        yield holder
    finally:
        holder.lifecycle.shutdown()


@pytest.fixture
def other_env(tmp_path: Path) -> Iterator[Env]:
    """A second, unrelated Core with its own gateway identity: the machine in the middle."""
    holder = build_env(tmp_path / "other")
    try:
        yield holder
    finally:
        holder.lifecycle.shutdown()
