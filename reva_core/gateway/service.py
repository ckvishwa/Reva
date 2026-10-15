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
import hashlib
import json
import re
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
from reva_core.policy.authorize import Proposal
from reva_core.policy.broker import ActionView, Broker, BrokerFull, UnknownAction

DOMAIN = "finance"

# What a paired phone may ask this PC to do, and the grant scope that allows each. Nothing else is
# reachable from a phone, whatever the registry says: not UI control, not memory, not money.
PHONE_ACTION_SCOPES = {
    "windows.app.open": "pc.app.open",  # T1: opens an app the owner approved
    "windows.app.close": "pc.app.close",  # T2: also needs a click on this PC
}
MAX_OPEN_PER_PHONE = 8  # one phone cannot fill the broker and starve this PC's own actions
ACTION_REQUEST_TTL = 120  # seconds a request may sit before the PC refuses it as stale
ACTION_REQUEST_FUTURE = 30  # clock skew allowed the other way
MAX_ACTION_ARGS_BYTES = 2048
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
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
        broker: Callable[[], Broker | None] = lambda: None,
    ) -> None:
        self._broker = broker
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
            withdrawn = 0
            broker = self._broker()
            if broker is not None:
                # Requests from this phone that are still waiting, or whose order nobody has picked
                # up, are withdrawn; the PC's app is never handed an order from a revoked phone.
                withdrawn = broker.cancel_for_origin(device_id)
            self._store.audit(
                "device_revoked", AuditOutcome.SUCCESS, device_id=device_id, withdrawn=withdrawn
            )
            return changed

    def set_phone_actions(
        self, device_id: str, *, open_apps: bool, close_apps: bool
    ) -> dict[str, bool]:
        """The owner, on this PC, decides which PC actions an already paired phone may ask for.
        This is the upgrade path: a phone paired before actions existed gets nothing until then."""
        with self._lock:
            grant = self._store.get(device_id)
            if grant is None or not grant.active:
                raise GatewayError("unknown_device", 404)
            kept = tuple(s for s in grant.scopes if s not in PHONE_ACTION_SCOPES.values())
            chosen = tuple(
                scope
                for wanted, scope in (
                    (open_apps, "pc.app.open"),
                    (close_apps, "pc.app.close"),
                )
                if wanted
            )
            self._store.set_scopes(device_id, kept + chosen)
            self._store.audit(
                "device_actions_changed",
                AuditOutcome.SUCCESS,
                device_id=device_id,
                open_apps=int(open_apps),
                close_apps=int(close_apps),
            )
            return {"open_apps": open_apps, "close_apps": close_apps}

    def is_active_device(self, device_id: str) -> bool:
        grant = self._store.get(device_id)
        return grant is not None and grant.active

    def device_name(self, device_id: str) -> str:
        grant = self._store.get(device_id)
        return grant.display_name if grant is not None else "A phone"

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

    # -------------------------------------------------------------------------- actions

    def act_propose(self, grant: Grant, payload: dict[str, Any]) -> dict[str, Any]:
        """A phone asks this PC to do one allowlisted thing. The same `request_id` is the same
        request, however many times it is sent: a retry after a dropped connection never acts twice,
        and the same id with different content is refused, not merged. Nothing here decides or acts:
        the broker authorizes, a click on this PC approves anything sensitive, and only the PC's
        executor reports what happened."""
        request_id = _request_id(payload)
        capability = payload.get("capability")
        args = payload.get("args")
        issued_at = payload.get("issued_at")
        if (
            not isinstance(capability, str)
            or not isinstance(args, dict)
            or not isinstance(issued_at, int)
            or isinstance(issued_at, bool)
            or len(json.dumps(args)) > MAX_ACTION_ARGS_BYTES
        ):
            raise GatewayError("bad_request", 422)
        age = self._now() - issued_at
        if age > ACTION_REQUEST_TTL or age < -ACTION_REQUEST_FUTURE:
            self._store.audit(
                "phone_action_refused",
                AuditOutcome.DENIED,
                device_id=grant.device_id,
                reason="request_expired",
            )
            raise GatewayError("request_expired", 410)
        needed = PHONE_ACTION_SCOPES.get(capability)
        if needed is None:
            self._store.audit(
                "phone_action_refused",
                AuditOutcome.DENIED,
                device_id=grant.device_id,
                reason="capability_not_allowed",
            )
            raise GatewayError("capability_not_allowed", 403)
        if needed not in grant.scopes:
            self._store.audit(
                "phone_action_refused",
                AuditOutcome.DENIED,
                device_id=grant.device_id,
                reason="out_of_scope",
            )
            raise GatewayError("out_of_scope", 403)
        broker = self._broker()
        if broker is None:
            raise GatewayError("actions_unavailable", 503)
        proposal_id = _proposal_id(grant.device_id, request_id)
        if not broker.knows(proposal_id) and broker.open_for_origin(grant.device_id) >= (
            MAX_OPEN_PER_PHONE
        ):
            raise GatewayError("too_many_actions", 429)  # a retry of a known request is not new
        proposal = Proposal(
            proposal_id=proposal_id,
            capability=capability,
            args=args,
            source="phone",
            origin_device=grant.device_id,
            target_device="local",
        )
        try:
            view = broker.propose(proposal, device_scopes=frozenset({"windows"}))
        except BrokerFull as exc:
            raise GatewayError("too_many_actions", 429) from exc
        self._store.audit(
            "phone_action_requested",
            AuditOutcome.SUCCESS,
            device_id=grant.device_id,
            capability=capability,
            status=view.status,
        )
        return _action_view(request_id, view)

    def act_status(self, grant: Grant, payload: dict[str, Any]) -> dict[str, Any]:
        """What the Core's own record says about this phone's request. A phone can read only its
        own requests (the id is derived from its device id) and never receives an order or grant."""
        request_id = _request_id(payload)
        broker = self._broker()
        if broker is None:
            raise GatewayError("actions_unavailable", 503)
        try:
            view = broker.get(_proposal_id(grant.device_id, request_id))
        except UnknownAction as exc:
            raise GatewayError("unknown_request", 404) from exc
        return _action_view(request_id, view)

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
        if not self._privacy.devices_allowed(DOMAIN):
            raise GatewayError("devices_disabled", 403)
        if not self._privacy.get(DOMAIN)["sync"]:
            raise GatewayError("sync_disabled", 403)
        handle, module = self._finance()
        self._ensure_signer(handle, module)
        return handle, module


def _request_id(payload: dict[str, Any]) -> str:
    value = payload.get("request_id")
    if not isinstance(value, str) or not _REQUEST_ID.match(value):
        raise GatewayError("bad_request", 422)
    return value


def _proposal_id(device_id: str, request_id: str) -> str:
    """The broker's id for a phone's request: derived from the phone, so two phones (or a phone and
    this PC's own app) can never collide on, read, or overwrite each other's requests."""
    return "ph-" + hashlib.sha256(f"{device_id}:{request_id}".encode()).hexdigest()[:40]


def _action_view(request_id: str, view: ActionView) -> dict[str, Any]:
    """The answer for a phone. Words come from the Core's templates; success is only ever
    `verified`, which the broker records only with the executor's evidence. No order, grant or
    signature."""
    return {
        "request_id": request_id,
        "capability": view.capability,
        "tier": view.tier,
        "status": view.status,
        "reason": view.reason,
        "speak": view.speak,
        "prompt": view.prompt,
        "deadline": view.deadline,
        "evidence_kind": view.evidence_kind,
    }


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
