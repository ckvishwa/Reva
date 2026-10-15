"""B4: network capture per domain (AR-CORE-010). What reaches the hosted-model client, by domain.

The hosted client is replaced by a capture that records the exact request body and also fails the
test if anything opens a socket. For every domain the sentinel text must be absent from the request
unless that domain is consented to, and it must never appear for a domain that is not.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reva_core.providers.cloud import (
    DEFAULT_OFF_DOMAINS,
    HOSTED_DOMAINS,
    CloudReasoner,
    CloudSettingsStore,
)
from reva_core.security.credential_store import InMemorySecretStore

KEY = "sk-ant-test-key-0123456789"


class Capture:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

        async def create(**kwargs: Any) -> Any:
            self.requests.append(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text="ok")]
            )

        async def close() -> None:
            return None

        self.client = SimpleNamespace(messages=SimpleNamespace(create=create), close=close)

    def wire(self) -> str:
        return json.dumps(self.requests, ensure_ascii=False, default=str)


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any connection that leaves this machine fails the test (asyncio loopback pair is fine)."""
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"a test opened a network connection to {host!r}")
        real_connect(self, address)  # type: ignore[arg-type]

    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("a test opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket, "create_connection", refuse)


def make(
    tmp_path: Path, *, on: tuple[str, ...], enabled: bool = True
) -> tuple[CloudReasoner, Capture]:
    store = CloudSettingsStore(tmp_path / "cloud_settings.json")
    settings = store.load()
    settings.enabled = enabled
    for name in on:
        settings.domains[name] = True
    store.save(settings)
    capture = Capture()
    reasoner = CloudReasoner(
        store, InMemorySecretStore(KEY), client_factory=lambda _key, _timeout: capture.client
    )
    return reasoner, capture


def context() -> dict[str, str]:
    return {name: f"SENTINEL-{name.upper()}-PRIVATE-CONTENT" for name in HOSTED_DOMAINS}


@pytest.mark.parametrize("domain", HOSTED_DOMAINS)
def test_a_domain_that_is_not_consented_never_reaches_the_wire(
    tmp_path: Path, no_sockets: None, domain: str
) -> None:
    others = tuple(d for d in HOSTED_DOMAINS if d != domain)
    reasoner, capture = make(tmp_path, on=others)

    asyncio.run(reasoner.reply("what's my day like", context()))

    wire = capture.wire()
    assert f"SENTINEL-{domain.upper()}" not in wire
    for other in others:
        assert f"SENTINEL-{other.upper()}-PRIVATE-CONTENT" in wire  # consented ones do go


@pytest.mark.parametrize("domain", HOSTED_DOMAINS)
def test_only_the_consented_domain_is_sent(tmp_path: Path, no_sockets: None, domain: str) -> None:
    reasoner, capture = make(tmp_path, on=(domain,))

    asyncio.run(reasoner.reply("hello", context()))

    wire = capture.wire()
    assert f"SENTINEL-{domain.upper()}-PRIVATE-CONTENT" in wire
    for other in HOSTED_DOMAINS:
        if other != domain:
            assert f"SENTINEL-{other.upper()}" not in wire


def test_with_every_switch_off_only_the_spoken_words_are_sent(
    tmp_path: Path, no_sockets: None
) -> None:
    reasoner, capture = make(tmp_path, on=())

    asyncio.run(reasoner.reply("what is the capital of France", context()))

    assert "SENTINEL" not in capture.wire()
    assert "capital of France" in capture.wire()


@pytest.mark.parametrize("domain", DEFAULT_OFF_DOMAINS)
def test_the_sensitive_four_are_off_until_the_owner_turns_them_on(
    tmp_path: Path, no_sockets: None, domain: str
) -> None:
    # Cloud is on, a key is stored, and the owner has enabled nothing else: still not sent.
    reasoner, capture = make(tmp_path, on=())

    asyncio.run(reasoner.reply("hi", {domain: f"SENTINEL-{domain.upper()}-PRIVATE-CONTENT"}))

    assert "SENTINEL" not in capture.wire()


def test_unclassified_data_does_not_leave(tmp_path: Path, no_sockets: None) -> None:
    reasoner, capture = make(tmp_path, on=HOSTED_DOMAINS)

    asyncio.run(
        reasoner.reply("hi", {"finance": "OK-FINANCE", "clipboard": "SENTINEL-CLIPBOARD", "": "X"})
    )

    assert "OK-FINANCE" in capture.wire()
    assert "SENTINEL-CLIPBOARD" not in capture.wire()


def test_when_cloud_is_off_nothing_is_sent_at_all(tmp_path: Path, no_sockets: None) -> None:
    from reva_core.providers.cloud import CloudUnavailable

    reasoner, capture = make(tmp_path, on=HOSTED_DOMAINS, enabled=False)

    with pytest.raises(CloudUnavailable):
        asyncio.run(reasoner.reply("hello", context()))

    assert capture.requests == []


def test_the_api_key_is_never_part_of_the_request_body(tmp_path: Path, no_sockets: None) -> None:
    reasoner, capture = make(tmp_path, on=HOSTED_DOMAINS)

    asyncio.run(reasoner.reply("hello", context()))

    assert KEY not in capture.wire()


def test_the_unified_privacy_switch_is_what_the_filter_obeys(
    client, auth_headers, core, no_sockets: None
) -> None:
    client.put(
        "/v1/settings/privacy",
        headers=auth_headers,
        json={"domains": {"career": {"hosted_model": True}}},
    )
    settings = core.cloud_settings_store.load()
    settings.enabled = True
    core.cloud_settings_store.save(settings)
    capture = Capture()
    reasoner = CloudReasoner(
        core.cloud_settings_store,
        InMemorySecretStore(KEY),
        client_factory=lambda _k, _t: capture.client,
    )

    asyncio.run(reasoner.reply("hi", {"career": "SENTINEL-CAREER", "finance": "SENTINEL-FINANCE"}))

    assert "SENTINEL-CAREER" in capture.wire() and "SENTINEL-FINANCE" not in capture.wire()
