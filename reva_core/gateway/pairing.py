"""Pairing sessions (ARD-500 section 2): one short-lived, one-time code at a time.

Life of a session
1. The user opens pairing on the PC (`open`). A random code is made; only its hash is kept. The
   QR shows the code and the gateway key hash.
2. The phone scans, checks the TLS key against the hash, and calls `start` with the code, its P-256
   public key and a signature over the code made with that key (proof of possession). The code is
   consumed: a second `start` with it fails with `code_used`. Both screens now show the same 6-digit
   fingerprint.
3. The user compares the digits and approves on the PC (`approve`, which must echo the digits).
   Only then is the grant created. The phone polls `complete` (signed) to learn the outcome.

Fail closed: wrong codes lock the session after a few tries, every window is short, and a session
that is not `open` never accepts a code.
"""

from __future__ import annotations

import functools
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, cast

from reva_core.gateway import protocol

SCOPES = ("finance",)
DEFAULT_TTL_SECONDS = 120
MAX_BAD_CODES = 5
_MAX_SEEN_NONCES = 200


def _locked[F: Callable[..., Any]](fn: F) -> F:
    """Run a PairingManager method under its lock, so a code is consumed exactly once."""

    @functools.wraps(fn)
    def wrapper(self: PairingManager, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return fn(self, *args, **kwargs)

    return cast(F, wrapper)


class PairingError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class PendingPhone:
    name: str
    platform: str
    public_key: bytes
    kernel_ids: dict[str, str]


@dataclass
class PairingSession:
    id: str
    code_hash: bytes
    expires_at: float
    state: str = "open"  # open | pending | approved | denied | expired | locked | cancelled
    bad_attempts: int = 0
    phone: PendingPhone | None = None
    fingerprint: str | None = None
    result: dict[str, Any] | None = None
    seen_nonces: set[str] = field(default_factory=set)


def _hash(code: str) -> bytes:
    return sha256(code.encode("utf-8")).digest()


class PairingManager:
    def __init__(
        self,
        gateway_sha256: str,
        on_approve: Callable[[PendingPhone], dict[str, Any]],
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_bad_codes: int = MAX_BAD_CODES,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._gateway = gateway_sha256
        self._on_approve = on_approve
        self._ttl = ttl_seconds
        self._max_bad = max_bad_codes
        self._now = now
        self._session: PairingSession | None = None
        # Gateway threads and the Devices controls meet here; consuming a code must be atomic.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------------------- PC side

    @_locked
    def open(self) -> tuple[PairingSession, str]:
        """Start a fresh session. Any earlier one is cancelled, so its code stops working."""
        if self._session is not None and self._session.state in ("open", "pending"):
            self._session.state = "cancelled"
        code = secrets.token_urlsafe(24)
        session = PairingSession(
            id=secrets.token_urlsafe(16),
            code_hash=_hash(code),
            expires_at=self._now() + self._ttl,
        )
        self._session = session
        return session, code

    @_locked
    def cancel(self) -> None:
        if self._session is not None and self._session.state in ("open", "pending"):
            self._session.state = "cancelled"

    @_locked
    def current(self) -> PairingSession | None:
        session = self._session
        if session is not None:
            self._expire(session)
        return session

    @_locked
    def approve(self, fingerprint: str) -> dict[str, Any]:
        session = self.current()
        if session is None or session.state != "pending" or session.phone is None:
            raise PairingError("nothing_to_approve", 409)
        if not hmac.compare_digest(fingerprint.encode(), (session.fingerprint or "").encode()):
            raise PairingError("fingerprint_mismatch", 409)
        result = self._on_approve(session.phone)  # raises if the Kernel or the store refuses
        session.result = result
        session.state = "approved"
        return result

    @_locked
    def deny(self) -> None:
        session = self.current()
        if session is not None and session.state in ("open", "pending"):
            session.state = "denied"

    # ---------------------------------------------------------------------------- phone side

    @_locked
    def start(
        self,
        *,
        code: str,
        name: str,
        platform: str,
        public_key: bytes,
        kernel_ids: dict[str, str],
        proof: bytes,
    ) -> str:
        session = self.current()
        if session is None or session.state in ("cancelled", "denied"):
            raise PairingError("no_open_pairing", 403)
        if session.state == "locked":
            raise PairingError("locked", 429)
        if session.state == "expired":
            raise PairingError("code_expired", 410)
        code_matches = protocol.CODE_PATTERN.match(code or "") is not None and hmac.compare_digest(
            _hash(code), session.code_hash
        )
        if not code_matches:
            self._bad_attempt(session)
            raise PairingError(
                "locked" if session.state == "locked" else "code_invalid",
                429 if session.state == "locked" else 403,
            )
        if session.state != "open":
            raise PairingError("code_used", 409)
        phone = self._validate_phone(name, platform, public_key, kernel_ids)
        if not protocol.verify(public_key, protocol.pair_start_message(code, self._gateway), proof):
            self._bad_attempt(session)
            raise PairingError("bad_proof", 403)
        session.phone = phone
        session.state = "pending"
        session.expires_at = self._now() + self._ttl  # time to compare the digits and approve
        session.fingerprint = protocol.fingerprint(self._gateway, public_key, session.id)
        return session.id

    @_locked
    def complete(self, *, session_id: str, nonce: str, proof: bytes) -> tuple[int, dict[str, Any]]:
        """Poll for the outcome. Returns (HTTP status, body)."""
        session = self.current()
        if session is None or not hmac.compare_digest(session_id.encode(), session.id.encode()):
            raise PairingError("unknown_session", 404)
        if session.phone is None:
            raise PairingError("unknown_session", 404)
        message = protocol.pair_complete_message(session.id, nonce, self._gateway)
        if not protocol.verify(session.phone.public_key, message, proof):
            raise PairingError("bad_proof", 403)
        if nonce in session.seen_nonces or len(session.seen_nonces) >= _MAX_SEEN_NONCES:
            raise PairingError("replayed", 409)
        session.seen_nonces.add(nonce)
        if session.state == "pending":
            return 202, {"status": "pending"}
        if session.state == "approved" and session.result is not None:
            return 200, {"status": "approved", **session.result}
        if session.state == "expired":
            raise PairingError("code_expired", 410)
        raise PairingError("denied", 403)

    # -------------------------------------------------------------------------------- helpers

    def _expire(self, session: PairingSession) -> None:
        if session.state in ("open", "pending") and self._now() > session.expires_at:
            session.state = "expired"

    def _bad_attempt(self, session: PairingSession) -> None:
        session.bad_attempts += 1
        if session.bad_attempts >= self._max_bad:
            session.state = "locked"

    @staticmethod
    def _validate_phone(
        name: str, platform: str, public_key: bytes, kernel_ids: dict[str, str]
    ) -> PendingPhone:
        try:
            protocol.load_public_key(public_key)
        except ValueError as exc:
            raise PairingError("bad_public_key", 422) from exc
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
            raise PairingError("bad_device_name", 422)
        if platform != "android":
            raise PairingError("bad_platform", 422)
        if (
            not isinstance(kernel_ids, dict)
            or set(kernel_ids) != set(SCOPES)
            or not all(
                isinstance(v, str) and protocol.DEVICE_ID_PATTERN.match(v)
                for v in kernel_ids.values()
            )
        ):
            raise PairingError("bad_kernel_devices", 422)
        return PendingPhone(
            name=name.strip(), platform=platform, public_key=public_key, kernel_ids=dict(kernel_ids)
        )
