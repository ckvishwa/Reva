"""Signed grants (AR-WIN-008, AR-AGT-004, AR-AGT-016).

A grant is the only thing an executor will act on. Core signs it with an ECDSA P-256 key that lives
in the OS vault; the executor holds only the public key and checks, before doing anything:

  * the signature (nobody but Core can make a grant, and a changed field breaks it);
  * the grant is bound to this action: capability, canonical arguments, target device, actor;
  * it has not expired and is not from the future;
  * its idempotency key has not been used before (a replayed grant does nothing).

The signature is the raw 64-byte r||s form (IEEE P1363), base64url without padding, because that is
what .NET's `ECDsa.VerifyData(..., DSASignatureFormat.IeeeP1363FixedFieldConcatenation)` takes: the
Windows executor verifies with the same bytes (tests/fixtures hold shared vectors for both sides).
"""

from __future__ import annotations

import base64
import json
import os
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from reva_core.domains.keys import (
    KEY_LENGTH,
    DomainKeyProvider,
    InMemoryKeyProvider,
    KeyStoreError,
    WindowsCredentialKeyProvider,
    ensure_memory_keystore_allowed,
)

GRANT_VERSION = "1"
GRANT_TTL = timedelta(seconds=60)
CLOCK_SKEW = timedelta(seconds=5)
ACTIONS_ENTRY_PREFIX = "reva.actions."
PUBLIC_KEY_FILE = "grant_public_key.pem"


@dataclass(frozen=True)
class Grant:
    grant_id: str
    action_id: str
    capability: str
    args_hash: str
    target_device: str
    actor: str
    issued_at: str  # ISO 8601, UTC
    expires_at: str
    idempotency_key: str
    version: str = GRANT_VERSION

    def signing_bytes(self) -> bytes:
        """Exactly what is signed: every field, sorted keys, no spaces."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> Grant:
        fields = (
            "grant_id",
            "action_id",
            "capability",
            "args_hash",
            "target_device",
            "actor",
            "issued_at",
            "expires_at",
            "idempotency_key",
            "version",
        )
        if set(raw) != set(fields) or not all(isinstance(raw[f], str) for f in fields):
            raise ValueError("a grant has exactly these text fields")
        return Grant(**{f: raw[f] for f in fields})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class GrantSigner:
    def __init__(self, key: ec.EllipticCurvePrivateKey) -> None:
        self._key = key

    def sign(self, grant: Grant) -> str:
        der = self._key.sign(grant.signing_bytes(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    def public_key_pem(self) -> bytes:
        return self._key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def write_public_key(self, directory: Path) -> Path:
        """The desktop app reads this file from the same data directory; it holds no secret."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / PUBLIC_KEY_FILE
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(self.public_key_pem())
        os.replace(temporary, path)
        return path


def grant_key_provider(keystore: str, data_dir: Path) -> DomainKeyProvider:
    """The vault for the grant key. Tests never reach the real one."""
    if keystore == "memory":
        ensure_memory_keystore_allowed(data_dir)
        return InMemoryKeyProvider()
    if "PYTEST_CURRENT_TEST" in os.environ:
        return _Unavailable()
    return WindowsCredentialKeyProvider(prefix=ACTIONS_ENTRY_PREFIX)


class _Unavailable:
    def load_key(self, domain: str) -> bytes | None:
        raise KeyStoreError("no OS key vault is available here")

    def store_key(self, domain: str, key: bytes) -> None:
        raise KeyStoreError("no OS key vault is available here")


def load_or_create_signer(provider: DomainKeyProvider, name: str = "grants") -> GrantSigner:
    raw = provider.load_key(name)
    if raw is None:
        key = ec.generate_private_key(ec.SECP256R1())
        provider.store_key(name, key.private_numbers().private_value.to_bytes(KEY_LENGTH, "big"))
        return GrantSigner(key)
    return GrantSigner(ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1()))


@dataclass(frozen=True)
class GrantCheck:
    ok: bool
    reason: str  # OK or a stable code


class ReplayCache:
    """Idempotency keys already used. Bounded: the oldest go first (grants last a minute)."""

    def __init__(self, capacity: int = 4096) -> None:
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._capacity = capacity

    def seen(self, key: str) -> bool:
        return key in self._seen

    def mark(self, key: str) -> None:
        self._seen[key] = None
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)


class GrantVerifier:
    """What an executor runs before acting (the Python reference of the Windows executor)."""

    def __init__(self, public_key_pem: bytes, replay: ReplayCache | None = None) -> None:
        key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise ValueError("the grant key must be an EC public key")
        self._key = key
        self.replay = replay or ReplayCache()

    def verify(
        self,
        grant: Grant,
        signature: str,
        *,
        now: datetime,
        capability: str,
        args_hash: str,
        target_device: str,
        actor: str,
    ) -> GrantCheck:
        try:
            raw = _unb64(signature)
        except (ValueError, TypeError):
            return GrantCheck(False, "MALFORMED")
        if len(raw) != 64 or grant.version != GRANT_VERSION:
            return GrantCheck(False, "MALFORMED")
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        try:
            self._key.verify(der, grant.signing_bytes(), ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            return GrantCheck(False, "BAD_SIGNATURE")
        try:
            issued = datetime.fromisoformat(grant.issued_at)
            expires = datetime.fromisoformat(grant.expires_at)
        except ValueError:
            return GrantCheck(False, "MALFORMED")
        if issued.tzinfo is None or expires.tzinfo is None:
            return GrantCheck(False, "MALFORMED")
        if now >= expires:
            return GrantCheck(False, "EXPIRED")
        if issued - CLOCK_SKEW > now:
            return GrantCheck(False, "NOT_YET_VALID")
        if grant.capability != capability:
            return GrantCheck(False, "CAPABILITY_MISMATCH")
        if grant.args_hash != args_hash:
            return GrantCheck(False, "ARGS_MISMATCH")
        if grant.target_device != target_device:
            return GrantCheck(False, "WRONG_TARGET")
        if grant.actor != actor:
            return GrantCheck(False, "WRONG_ACTOR")
        if self.replay.seen(grant.idempotency_key):
            return GrantCheck(False, "REPLAYED")
        self.replay.mark(grant.idempotency_key)
        return GrantCheck(True, "OK")


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()
