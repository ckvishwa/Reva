"""What the gateway does for an authenticated phone, and the rules for letting it in.

One lock (`_lock`) covers "check the grant" and "do the Kernel call" together, and revoking
takes the same lock. So after `revoke` returns, no request admitted earlier is still running and
no later request can be admitted (AR-DATA-004). The Kernel enforces revocation again on its own.

Third-device forwarding (decision, see docs/architecture/pairing-gateway.md): the PC forwards an
event from device X to phone P only if X is the PC itself or another active phone with a finance
grant, and it sends P the public key of every such X in the same response (`directory`), scoped
to that grant. Events whose origin is not in that set (a revoked phone) are not forwarded; they
stay on the PC.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Any

from reva_core.audit.events import AuditOutcome
from reva_core.domains.privacy import DomainPrivacyStore
from reva_core.domains.service import DomainRequestError, DomainService
from reva_core.gateway import protocol
from reva_core.gateway.identity import GatewayIdentity, make_kernel_signer
from reva_core.gateway.pairing import SCOPES, PairingError, PendingPhone
from reva_core.gateway.store import Grant, GrantStore

DOMAIN = "finance"
CLOCK_SKEW_SECONDS = 120
MAX_PULL_EVENTS = 500
_FAILURE_WINDOW = 60.0
_FAILURE_LIMIT = 20
_NONCE_CAPACITY = 20_000


class GatewayError(Exception):
    """A refusal with a stable code and HTTP status. Never carries secrets or record contents."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class GatewayService:
    def __init__(
        self,
        *,
        store: GrantStore,
        identity: Callable[[], GatewayIdentity],
        domains: Callable[[], DomainService],
        privacy: DomainPrivacyStore,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._identity_factory = identity
        self._domains = domains
        self._privacy = privacy
        self._now = now
        self._lock = threading.RLock()
        self._nonces: OrderedDict[str, float] = OrderedDict()
        self._failures: dict[str, deque[float]] = {}

    @property
    def _identity(self) -> GatewayIdentity:
        # Created on first use, so revoking or listing devices never has to touch the vault.
        return self._identity_factory()

    # ------------------------------------------------------------------------ admission

    def note_failure(self, remote: str) -> None:
        with self._lock:
            if len(self._failures) > 1024:
                self._failures.clear()
            self._failures.setdefault(remote, deque()).append(self._now())

    def _check_rate(self, remote: str) -> None:
        attempts = self._failures.get(remote)
        if not attempts:
            return
        horizon = self._now() - _FAILURE_WINDOW
        while attempts and attempts[0] < horizon:
            attempts.popleft()
        if len(attempts) >= _FAILURE_LIMIT:
            raise GatewayError("rate_limited", 429)

    def check_not_rate_limited(self, remote: str) -> None:
        with self._lock:
            self._check_rate(remote)

    def precheck(self, *, device_id: str, timestamp: str, nonce: str, remote: str) -> None:
        """Cheap admission before the body is read: a stranger cannot make the gateway buffer
        megabytes. The signature (which covers the body) is verified later, in `dispatch`."""
        with self._lock:
            self._check_rate(remote)
            if not protocol.DEVICE_ID_PATTERN.match(device_id or ""):
                raise self._deny(remote, "bad_device_id")
            try:
                ts = int(timestamp)
            except (TypeError, ValueError):
                raise self._deny(remote, "malformed") from None
            if abs(self._now() - ts) > CLOCK_SKEW_SECONDS:
                raise self._deny(remote, "stale_timestamp")
            if not protocol.DEVICE_ID_PATTERN.match(nonce or "") or len(nonce) < 16:
                raise self._deny(remote, "bad_nonce")
            grant = self._store.get(device_id)
            if grant is None:
                raise self._deny(remote, "unknown_device")
            if not grant.active:
                raise self._deny(remote, "revoked_device", device_id)

    def dispatch(
        self,
        op: Callable[[Grant], dict[str, Any]],
        *,
        device_id: str,
        timestamp: str,
        nonce: str,
        signature: str,
        method: str,
        path: str,
        body: bytes,
        remote: str,
    ) -> dict[str, Any]:
        """Authenticate, then run `op` while the grant cannot change underneath it."""
        with self._lock:
            self._check_rate(remote)
            grant = self._authenticate(
                device_id, timestamp, nonce, signature, method, path, body, remote
            )
            return op(grant)

    def _deny(self, remote: str, reason: str, device_id: str | None = None) -> GatewayError:
        self.note_failure(remote)
        self._store.audit(
            "gateway_request_denied", AuditOutcome.DENIED, device_id=device_id, reason=reason
        )
        # One answer for every reason: a caller learns nothing about which check failed.
        return GatewayError("unauthorized", 401)

    def _authenticate(
        self,
        device_id: str,
        timestamp: str,
        nonce: str,
        signature: str,
        method: str,
        path: str,
        body: bytes,
        remote: str,
    ) -> Grant:
        if not protocol.DEVICE_ID_PATTERN.match(device_id or ""):
            raise self._deny(remote, "bad_device_id")
        try:
            ts = int(timestamp)
            sig = protocol.b64u_decode(signature)
        except (TypeError, ValueError):
            raise self._deny(remote, "malformed") from None
        if abs(self._now() - ts) > CLOCK_SKEW_SECONDS:
            raise self._deny(remote, "stale_timestamp")
        if not protocol.DEVICE_ID_PATTERN.match(nonce or "") or len(nonce) < 16:
            raise self._deny(remote, "bad_nonce")
        grant = self._store.get(device_id)
        if grant is None:
            raise self._deny(remote, "unknown_device")
        if not grant.active:
            raise self._deny(remote, "revoked_device", device_id)
        key = f"{device_id}:{nonce}"
        if key in self._nonces:
            raise self._deny(remote, "replayed_request", device_id)
        message = protocol.request_message(method, path, ts, nonce, body, self._identity.tls_sha256)
        if not protocol.verify(grant.public_key, message, sig):
            raise self._deny(remote, "bad_signature", device_id)
        self._remember_nonce(key)
        self._store.touch(device_id)
        return grant

    def _remember_nonce(self, key: str) -> None:
        now = self._now()
        self._nonces[key] = now + 2 * CLOCK_SKEW_SECONDS
        while self._nonces and (
            len(self._nonces) > _NONCE_CAPACITY or next(iter(self._nonces.values())) < now
        ):
            self._nonces.popitem(last=False)

    # ------------------------------------------------------------------- pairing + revoke

    def approve_phone(self, phone: PendingPhone) -> dict[str, Any]:
        """Create the grant and register the peer in the Kernel; undo the grant if it refuses."""
        with self._lock:
            handle, module = self._finance()
            self._ensure_signer(handle, module)
            device_id = self._store.add(
                display_name=phone.name,
                platform=phone.platform,
                public_key=phone.public_key,
                kernel_ids=phone.kernel_ids,
                scopes=SCOPES,
            )
            try:
                handle.register_peer(
                    phone.kernel_ids[DOMAIN], phone.public_key, phone.name, list(SCOPES)
                )
            except module.DomainError as exc:
                self._store.remove(device_id)
                self._store.audit(
                    "device_pairing_approved", AuditOutcome.FAILURE, reason=_name(exc)
                )
                raise PairingError("kernel_refused", 409) from exc
            self._store.audit("device_pairing_approved", AuditOutcome.SUCCESS, device_id=device_id)
            return {
                "device_id": device_id,
                "scopes": list(SCOPES),
                "gateway": {
                    "tls_sha256": self._identity.tls_sha256,
                    "signing_public_key": protocol.b64u(self._identity.device_spki),
                    "kernel_devices": {DOMAIN: handle.device_id()},
                },
            }

    def revoke(self, device_id: str) -> bool:
        """Revoke a phone everywhere, atomically with respect to requests in flight."""
        with self._lock:
            grant = self._store.get(device_id)
            if grant is None:
                return False
            changed = self._store.revoke(device_id)
            handle, module = self._finance()
            for kernel_id in grant.kernel_ids.values():
                # Not registered in the Kernel? The grant is revoked either way.
                with contextlib.suppress(module.DomainError):
                    handle.revoke_peer(kernel_id)
            self._store.audit("device_revoked", AuditOutcome.SUCCESS, device_id=device_id)
            return changed

    # ------------------------------------------------------------------------------ sync

    def push(self, grant: Grant, payload: dict[str, Any]) -> dict[str, Any]:
        handle, module = self._sync_ready(grant, payload)
        batch = _batch(module, payload)
        try:
            report = handle.sync_apply(grant.kernel_ids[DOMAIN], batch)
        except module.DomainError as exc:
            raise _map(module, exc) from exc
        if report.applied:
            # Tell open screens (PC Finance and Today) to reload: they wait on this counter.
            self._domains().note_change(DOMAIN)
        self._store.audit(
            "sync_push", AuditOutcome.SUCCESS, device_id=grant.device_id, applied=report.applied
        )
        return {
            "applied": report.applied,
            "duplicates": report.duplicates,
            "conflicts": [
                {
                    "aggregate_type": c.aggregate_type,
                    "aggregate_id": c.aggregate_id,
                    "field": c.field,
                    "local_value": c.local_value,
                    "remote_value": c.remote_value,
                }
                for c in report.conflicts
            ],
            "ack_cursor": batch.cursor_to,
        }

    def pull(self, grant: Grant, payload: dict[str, Any]) -> dict[str, Any]:
        handle, module = self._sync_ready(grant, payload)
        limit = payload.get("limit", MAX_PULL_EVENTS)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_PULL_EVENTS
        ):
            raise GatewayError("bad_request", 422)
        try:
            batch = handle.sync_export(grant.kernel_ids[DOMAIN], limit)
        except module.DomainError as exc:
            raise _map(module, exc) from exc
        events: list[dict[str, Any]] = json.loads(batch.events_json)
        own = handle.device_id()
        known: dict[str, Grant] = {
            g.kernel_ids[DOMAIN]: g
            for g in self._store.active_grants()
            if g.device_id != grant.device_id and DOMAIN in g.scopes
        }
        kept = [e for e in events if e["origin_device_id"] == own or e["origin_device_id"] in known]
        origins = {e["origin_device_id"] for e in kept} - {own}
        directory = [
            {
                "device_id": kernel_id,
                "public_key": protocol.b64u(known[kernel_id].public_key),
                "label": known[kernel_id].display_name,
            }
            for kernel_id in sorted(origins)
        ]
        return {
            "events_json": json.dumps(kept, separators=(",", ":")),
            "cursor_from": batch.cursor_from,
            "cursor_to": batch.cursor_to,
            "count": len(kept),
            "withheld": len(events) - len(kept),
            "directory": directory,
        }

    def ack(self, grant: Grant, payload: dict[str, Any]) -> dict[str, Any]:
        handle, module = self._sync_ready(grant, payload)
        cursor = payload.get("cursor")
        if not isinstance(cursor, int) or isinstance(cursor, bool):
            raise GatewayError("bad_request", 422)
        try:
            handle.sync_ack(grant.kernel_ids[DOMAIN], cursor)
        except module.DomainError as exc:
            raise _map(module, exc) from exc
        return {"acknowledged": cursor}

    # ---------------------------------------------------------------------------- helpers

    def _finance(self) -> tuple[Any, Any]:
        service = self._domains()
        try:
            return service.handle(DOMAIN), service.binding()
        except DomainRequestError as exc:
            raise GatewayError("domain_unavailable", 503) from exc

    def _ensure_signer(self, handle: Any, module: Any) -> None:
        handle.set_signer(make_kernel_signer(module, self._identity))

    def _sync_ready(self, grant: Grant, payload: dict[str, Any]) -> tuple[Any, Any]:
        if payload.get("domain") != DOMAIN or DOMAIN not in grant.scopes:
            raise GatewayError("out_of_scope", 403)
        if not self._privacy.get(DOMAIN)["sync"]:
            raise GatewayError("sync_disabled", 403)
        handle, module = self._finance()
        self._ensure_signer(handle, module)
        return handle, module


def _int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise GatewayError("bad_request", 422)
    return value


def _batch(module: Any, payload: dict[str, Any]) -> Any:
    events_json = payload.get("events_json")
    if not isinstance(events_json, str):
        raise GatewayError("bad_request", 422)
    count = _int(payload, "count")
    if count < 0:
        raise GatewayError("bad_request", 422)
    return module.SyncBatch(
        events_json=events_json,
        cursor_from=_int(payload, "cursor_from"),
        cursor_to=_int(payload, "cursor_to"),
        count=count,
    )


def _name(exc: Exception) -> str:
    return type(exc).__name__


def _map(module: Any, exc: Exception) -> GatewayError:
    if isinstance(exc, module.DomainError.Rejected):
        return GatewayError("sync_rejected", 403)
    if isinstance(exc, module.DomainError.Validation):
        return GatewayError("bad_request", 422)
    return GatewayError("internal_error", 500)
