"""The gateway is a separate, opt-in listener: off by default, one allowlisted surface.

AR-DATA-005 (binds only when enabled, reports interface and port), AR-DATA-006 (no route outside the
allowlist, never the Core API), AR-DATA-002 (TLS).
"""

from __future__ import annotations

import socket
import sys
import threading
import uuid
from pathlib import Path

import pytest

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.gateway import protocol
from reva_core.gateway.server import detect_lan_address
from reva_core.orchestration.lifecycle import CoreLifecycle
from tests.gateway.conftest import Env, build_env
from tests.gateway.phone import Phone

GATEWAY_SOURCES = sorted(
    Path(__file__).resolve().parents[2].joinpath("reva_core", "gateway").glob("*.py")
)


def _can_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def test_the_gateway_is_off_by_default(env: Env) -> None:
    status = env.client.get("/v1/devices", headers=env.headers).json()["gateway"]
    assert status["enabled"] is False and status["listening"] is False
    assert status["host"] is None and status["port"] is None
    assert not [t for t in threading.enumerate() if t.name == "reva-gateway"]
    # Nothing to pair with while it is off.
    reply = env.client.post("/v1/devices/pairing", headers=env.headers)
    assert (reply.status_code, reply.json()["error"]) == (409, "gateway_off")


def test_the_port_is_bound_only_while_enabled_and_reported(env: Env) -> None:
    status = env.enable()
    assert status["enabled"] and status["listening"]
    assert status["host"] == "127.0.0.1", "one interface address, not the wildcard"
    port = status["port"]
    assert port and port != env.lifecycle.settings.api_port
    assert _can_connect("127.0.0.1", port)
    reported = env.client.get("/v1/devices", headers=env.headers).json()["gateway"]
    assert (reported["host"], reported["port"]) == ("127.0.0.1", port)

    off = env.client.patch("/v1/devices/gateway", json={"enabled": False}, headers=env.headers)
    assert off.json()["gateway"]["listening"] is False
    assert not _can_connect("127.0.0.1", port), "closing the setting closes the socket"
    assert not [t for t in threading.enumerate() if t.name == "reva-gateway"]


def test_the_setting_survives_a_restart_and_off_stays_off(env: Env) -> None:
    env.enable()
    env.lifecycle.shutdown()
    settings = env.lifecycle.settings
    again = CoreLifecycle(
        settings,
        domain_key_provider=InMemoryKeyProvider(),
        gateway_key_provider=InMemoryKeyProvider(),
    )
    again.startup()
    try:
        assert again.gateway.status()["listening"] is True
        again.gateway.set_enabled(False)
    finally:
        again.shutdown()
    third = CoreLifecycle(
        settings,
        domain_key_provider=InMemoryKeyProvider(),
        gateway_key_provider=InMemoryKeyProvider(),
    )
    third.startup()
    try:
        assert third.gateway.status() == {
            **third.gateway.status(),
            "enabled": False,
            "listening": False,
        }
    finally:
        third.shutdown()


def test_a_listener_that_cannot_start_reports_why_and_does_not_stay_enabled(env: Env) -> None:
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    busy = blocker.getsockname()[1]
    try:
        env.lifecycle.settings.gateway_port = busy
        reply = env.client.patch("/v1/devices/gateway", json={"enabled": True}, headers=env.headers)
        assert reply.status_code == 409 and reply.json()["error"] == "gateway_unavailable"
        status = env.client.get("/v1/devices", headers=env.headers).json()["gateway"]
        assert status["enabled"] is False and status["listening"] is False
    finally:
        blocker.close()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "*"])  # noqa: S104
def test_the_gateway_refuses_to_listen_on_every_interface(env: Env, host: str) -> None:
    env.lifecycle.settings.gateway_host = host
    reply = env.client.patch("/v1/devices/gateway", json={"enabled": True}, headers=env.headers)
    assert reply.status_code == 409 and reply.json()["error"] == "gateway_unavailable"
    status = env.client.get("/v1/devices", headers=env.headers).json()["gateway"]
    assert status["enabled"] is False and status["listening"] is False


def test_the_lan_address_is_never_loopback_or_wildcard() -> None:
    address = detect_lan_address()
    assert address is None or not address.startswith("127.") and address != "0.0.0.0"  # noqa: S104


def test_only_the_five_allowlisted_routes_exist(env: Env) -> None:
    env.enable()
    app = env.manager._server._app  # noqa: SLF001
    found = {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
        if method not in ("HEAD", "OPTIONS")
    }
    assert found == set(protocol.ALLOWED_ROUTES)
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None


PROBE_PATHS = [
    "/", "/docs", "/redoc", "/openapi.json", "/health", "/version", "/v1/today", "/v1/domains",
    "/v1/devices", "/v1/messages", "/v1/domains/finance/transactions", "/sync", "/sync/",
    "/sync/push/", "/sync/pull/../push", "/pair", "/admin", "/pair/start/extra", "/%2e%2e/v1/today",
]  # fmt: skip


def test_no_route_outside_the_allowlist_answers(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    phone.point_at(env.open_pairing()["qr_text"])
    for path in PROBE_PATHS:
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            assert (method, path) not in protocol.ALLOWED_ROUTES
            reply = phone.request(method, path, b"{}")
            assert reply.status in (404, 405), (method, path, reply.status, reply.body)
            assert set(reply.json()) == {"error"}, "no detail, no hint about what exists"
    for _method, path in protocol.ALLOWED_ROUTES:
        for wrong in ("GET", "PUT", "PATCH", "DELETE"):
            assert phone.request(wrong, path, b"{}").status == 405, (wrong, path)


def test_the_core_bearer_token_opens_nothing_on_the_gateway(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    phone.point_at(env.open_pairing()["qr_text"])
    for path in ("/sync/push", "/sync/pull", "/sync/ack"):
        reply = phone.post(path, {"domain": "finance"}, headers=env.headers)
        assert reply.status == 401 and reply.json() == {"error": "unauthorized"}
    assert phone.request("GET", "/v1/devices", headers=env.headers).status == 404


def test_the_gateway_code_never_touches_the_core_token_or_core_auth() -> None:
    assert GATEWAY_SOURCES
    for source in GATEWAY_SOURCES:
        if source.name == "routes.py":  # the loopback Devices controls, by design
            continue
        text = source.read_text(encoding="utf-8")
        assert "local_token" not in text, source.name
        assert "reva_core.api.auth" not in text, source.name


def test_the_gateway_speaks_tls_only(env: Env) -> None:
    env.enable()
    port = env.manager.status()["port"]
    with socket.create_connection(("127.0.0.1", port), timeout=3) as plain:
        plain.sendall(b"POST /sync/pull HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\n{}")
        plain.settimeout(3)
        try:
            data = plain.recv(4096)
        except OSError:
            data = b""
    assert b"HTTP/1.1 200" not in data and b"unauthorized" not in data


def test_no_private_key_is_left_on_disk_or_in_the_database(env: Env) -> None:
    env.enable()
    env.pair(env.new_phone())
    scalars = [bytes(v) for v in env.gateway_keys.keys.values()]
    assert len(scalars) == 2, "a TLS key and a device key were created in the vault"
    for path in (env.tmp_path / "core").rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        assert b"PRIVATE KEY" not in data, path
        assert not any(s in data for s in scalars), path
    tls_dir = env.tmp_path / "core" / "gateway" / "tls"
    assert not tls_dir.exists() or not list(tls_dir.iterdir())


def test_a_second_core_has_a_different_gateway_key(env: Env, other_env: Env) -> None:
    assert env.enable()["tls_sha256"] != other_env.enable()["tls_sha256"]


def test_settings_validation_rejects_a_bad_port() -> None:
    with pytest.raises(ValueError):
        load_settings(_env_file=None, gateway_port=70000)


def test_the_core_api_still_has_no_gateway_routes_besides_devices(env: Env) -> None:
    app = create_app(env.lifecycle)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.startswith(("/sync", "/pair")) for p in paths)


def test_phone_helper_builds_without_the_network(tmp_path: Path) -> None:
    env = build_env(tmp_path)
    try:
        assert isinstance(env.new_phone(), Phone)
    finally:
        env.lifecycle.shutdown()


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows Credential Manager only exists on Windows"
)
def test_gateway_keys_round_trip_through_the_real_credential_manager_with_a_throwaway_entry() -> (
    None
):
    from reva_core.domains.keys import WindowsCredentialKeyProvider
    from reva_core.gateway.identity import GatewayIdentity

    provider = WindowsCredentialKeyProvider(prefix=f"reva.test.{uuid.uuid4().hex[:12]}.")
    try:
        first = GatewayIdentity(provider)
        second = GatewayIdentity(provider)  # a restart: the same keys come back from the vault
        assert first.tls_sha256 == second.tls_sha256 and first.device_spki == second.device_spki
        assert len(first.tls_sha256) == 64 and b"BEGIN CERTIFICATE" in first.certificate_pem()
    finally:
        provider.delete_key("tls")
        provider.delete_key("device")
    assert provider.load_key("tls") is None and provider.load_key("device") is None
