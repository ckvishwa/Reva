"""Owns the gateway's lifetime: the Devices setting, the listener, pairing and revocation.

Off by default. Turning it on creates the identity (touching the OS vault), builds the gateway
app and binds one LAN address; turning it off closes the socket. The setting is remembered in
`<data_dir>/gateway/settings.json`. Revoking and listing devices work with the listener down.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from reva_core.audit.events import AuditOutcome
from reva_core.config.settings import Settings
from reva_core.domains.keys import DomainKeyProvider
from reva_core.domains.privacy import DomainPrivacyStore
from reva_core.domains.service import DomainService
from reva_core.gateway import protocol
from reva_core.gateway.app import build_gateway_app
from reva_core.gateway.identity import GatewayIdentity, gateway_key_provider
from reva_core.gateway.pairing import DEFAULT_TTL_SECONDS, PairingError, PairingManager
from reva_core.gateway.server import GatewayListenError, GatewayServer, detect_lan_address
from reva_core.gateway.service import GatewayError, GatewayService
from reva_core.gateway.store import Grant, GrantStore
from reva_core.gateway.trace import FileTraceSink
from reva_core.policy.broker import Broker
from reva_core.shared.logging import get_logger

logger = get_logger("gateway")

SETTINGS_FILE = "settings.json"
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "", "*"})  # noqa: S104 - listed only to refuse them


class GatewayStateError(Exception):
    """The request does not fit the current state (gateway off, no pairing open, ...)."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class GatewayManager:
    def __init__(
        self,
        settings: Settings,
        domains: Callable[[], DomainService],
        privacy: DomainPrivacyStore,
        key_provider: DomainKeyProvider | None = None,
        *,
        pairing_ttl: int = DEFAULT_TTL_SECONDS,
        now: Callable[[], float] = time.time,
        broker: Callable[[], Broker | None] = lambda: None,
    ) -> None:
        self._broker = broker
        self._settings = settings
        self._dir = Path(settings.data_dir) / "gateway"
        self._key_provider = key_provider
        self._pairing_ttl = pairing_ttl
        self._now = now
        self._lock = threading.RLock()
        self._identity_lock = (
            threading.Lock()
        )  # separate: requests ask for the identity while holding the service lock
        self._identity: GatewayIdentity | None = None
        self._store = GrantStore(settings.db_path)
        self._service = GatewayService(
            store=self._store,
            identity=self._get_identity,
            domains=domains,
            privacy=privacy,
            now=lambda: self._now(),
            broker=broker,
        )
        self._pairing: PairingManager | None = None
        self._server: GatewayServer | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------------- lifetime

    def startup(self) -> None:
        """Start the listener if the user left it on. A failure is reported, not fatal."""
        if not self._read_enabled():
            return
        try:
            self._start()
        except Exception as exc:  # noqa: BLE001 - Core must come up even if the LAN is unavailable
            self.last_error = _safe(exc)
            logger.warning("pairing gateway could not start: %s", self.last_error)

    def shutdown(self) -> None:
        with self._lock:
            self._stop()
            self._store.close()

    # -------------------------------------------------------------------------- settings

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            if enabled:
                self._start()
            else:
                self._stop()
            self._write_enabled(enabled)
            self._store.audit(
                "gateway_enabled" if enabled else "gateway_disabled", AuditOutcome.SUCCESS
            )
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            server = self._server
            listening = bool(server and server.listening)
            return {
                "enabled": self._read_enabled(),
                "listening": listening,
                "host": server.host if listening and server else None,
                "port": server.port if listening and server else None,
                "tls_sha256": self._identity.tls_sha256 if self._identity else None,
                "error": self.last_error,
                "pairing": self._pairing_view(),
            }

    # --------------------------------------------------------------------------- pairing

    def open_pairing(self) -> dict[str, Any]:
        with self._lock:
            server, pairing = self._server, self._pairing
            if server is None or pairing is None or not server.listening or self._identity is None:
                raise GatewayStateError("gateway_off")
            session, code = pairing.open()
            self._store.audit("pairing_opened", AuditOutcome.SUCCESS)
            assert server.host is not None and server.port is not None
            return {
                "session_id": session.id,
                "qr_text": protocol.make_qr_text(
                    host=server.host,
                    port=server.port,
                    code=code,
                    gateway_sha256=self._identity.tls_sha256,
                    expires_at=int(session.expires_at),
                ),
                "expires_at": int(session.expires_at),
            }

    def approve_pairing(self, fingerprint: str) -> dict[str, Any]:
        with self._lock:
            pairing = self._require_pairing()
            try:
                result = pairing.approve(fingerprint)
            except PairingError as exc:
                self._store.audit("pairing_approve_refused", AuditOutcome.DENIED, reason=exc.code)
                raise GatewayStateError(exc.code, exc.status) from exc
            return {"device_id": result["device_id"]}

    def deny_pairing(self) -> None:
        with self._lock:
            self._require_pairing().deny()
            self._store.audit("pairing_denied", AuditOutcome.DENIED)

    def cancel_pairing(self) -> None:
        with self._lock:
            if self._pairing is not None:
                self._pairing.cancel()

    # ------------------------------------------------------------------------- devices

    def devices(self) -> list[dict[str, Any]]:
        return [_device_view(g) for g in self._store.list_all()]

    def revoke(self, device_id: str) -> bool:
        grant = self._store.get(device_id)
        if grant is None:
            raise GatewayStateError("unknown_device", 404)
        return self._service.revoke(device_id)

    # ------------------------------------------------------------- phone actions (C2)

    def set_phone_actions(
        self, device_id: str, *, open_apps: bool, close_apps: bool
    ) -> dict[str, Any]:
        try:
            chosen = self._service.set_phone_actions(
                device_id, open_apps=open_apps, close_apps=close_apps
            )
        except GatewayError as exc:
            raise GatewayStateError(exc.code, exc.status) from exc
        return {"device_id": device_id, **chosen}

    def actions_inbox(self, after: int, wait: float) -> dict[str, Any]:
        """What this PC's app must do for phones: confirm cards and signed orders. Waits up to
        `wait` seconds for something new after `after`. Orders are handed out once."""
        broker = self._broker()
        if broker is None:
            return {"seq": after, "items": []}
        seq = broker.wait_remote(after, wait) if wait > 0 else broker.remote_seq()
        items = broker.remote_inbox(active_origins=self._service.is_active_device)
        return {
            "seq": seq,
            "items": [
                {
                    "action_id": v.action_id,
                    "capability": v.capability,
                    "tier": v.tier,
                    "status": v.status,
                    "prompt": v.prompt,
                    "deadline": v.deadline,
                    "from": self._origin_name(broker, v.action_id),
                    "order": _order_json(v),
                }
                for v in items
            ],
        }

    def _origin_name(self, broker: Broker, action_id: str) -> str:
        record = broker._records.get(action_id)  # noqa: SLF001 - same package family, read only
        return self._service.device_name(record.proposal.origin_device) if record else "A phone"

    # ------------------------------------------------------------------------- internals

    def _get_identity(self) -> GatewayIdentity:
        with self._identity_lock:
            if self._identity is None:
                provider = self._key_provider or gateway_key_provider(
                    self._settings.domain_keystore, Path(self._settings.data_dir)
                )
                self._identity = GatewayIdentity(provider)
            return self._identity

    def _start(self) -> None:
        with self._lock:
            if self._server is not None and self._server.listening:
                return
            host = self._settings.gateway_host or detect_lan_address()
            if host is None:
                raise GatewayListenError("no local network address was found for the gateway")
            if host in _WILDCARD_HOSTS:
                raise GatewayListenError(
                    "the gateway binds one interface address, not every interface"
                )
            identity = self._get_identity()
            pairing = PairingManager(
                identity.tls_sha256,
                self._service.approve_phone,
                ttl_seconds=self._pairing_ttl,
                now=lambda: self._now(),
            )
            trace = self._settings.gateway_trace
            app = build_gateway_app(
                self._service, pairing, identity, FileTraceSink(trace) if trace else None
            )
            server = GatewayServer(app, identity, self._dir / "tls")
            server.start(host, self._settings.gateway_port)
            self._pairing, self._server = pairing, server
            self.last_error = None

    def _stop(self) -> None:
        if self._pairing is not None:
            self._pairing.cancel()
        if self._server is not None:
            self._server.stop()
        self._pairing = self._server = None

    def _require_pairing(self) -> PairingManager:
        if self._pairing is None:
            raise GatewayStateError("gateway_off")
        return self._pairing

    def _pairing_view(self) -> dict[str, Any] | None:
        session = self._pairing.current() if self._pairing else None
        if session is None:
            return None
        view: dict[str, Any] = {
            "state": session.state,
            "expires_in": max(0, int(session.expires_at - self._now())),
        }
        if session.state == "pending" and session.phone is not None:
            view["fingerprint"] = session.fingerprint
            view["device_name"] = session.phone.name
            view["platform"] = session.phone.platform
        return view

    def _read_enabled(self) -> bool:
        try:
            data = json.loads((self._dir / SETTINGS_FILE).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return False
        return isinstance(data, dict) and data.get("enabled") is True

    def _write_enabled(self, enabled: bool) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=self._dir, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump({"enabled": enabled}, out)
            os.replace(temp, self._dir / SETTINGS_FILE)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise


def _order_json(view: Any) -> dict[str, Any] | None:
    if view.order is None:
        return None
    return {
        "grant": view.order.grant.to_dict(),
        "signature": view.order.signature,
        "capability": view.order.capability,
        "args": dict(view.order.args),
        "target_device_id": view.order.target_device,
    }


def _device_view(grant: Grant) -> dict[str, Any]:
    return {
        "device_id": grant.device_id,
        "name": grant.display_name,
        "platform": grant.platform,
        "scopes": list(grant.scopes),
        "actions": {
            "open_apps": "pc.app.open" in grant.scopes,
            "close_apps": "pc.app.close" in grant.scopes,
        },
        "status": grant.status,
        "fingerprint": protocol.spki_sha256(grant.public_key),
        "approved_at": grant.approved_at,
        "revoked_at": grant.revoked_at,
        "last_seen_at": grant.last_seen_at,
    }


def _safe(exc: BaseException) -> str:
    return exc.args[0] if exc.args and isinstance(exc.args[0], str) else type(exc).__name__
