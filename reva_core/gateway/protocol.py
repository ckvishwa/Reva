"""Wire format of the pairing gateway (ARD-500 section 2, ADR-009, ADR-010).

Everything a phone and the PC must agree on byte for byte lives here: the QR payload, the strings
that get signed, and the 6-digit fingerprint both screens show. Nothing here does I/O.

Authentication model
* The phone pins the gateway by the SHA-256 of its TLS public key (SubjectPublicKeyInfo DER), which
  it reads from the QR code. A certificate with any other key is refused before a byte is sent.
* After pairing, every request carries the phone's device id, a timestamp, a random nonce and an
  ECDSA P-256 signature over the method, path, timestamp, nonce, body hash and the gateway hash.
  The gateway re-checks the grant in the database on every request, so revocation is immediate.
* Responses to authenticated requests are signed by the PC's device key over the request nonce, the
  status and the body hash, so a phone can tell a real answer from one replayed or forged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

PROTOCOL = "REVA-GW1"
QR_PREFIX = "REVA-PAIR1:"
QR_VERSION = 1
CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22,43}$")
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

HEADER_DEVICE = "X-Reva-Device"
HEADER_TIMESTAMP = "X-Reva-Ts"
HEADER_NONCE = "X-Reva-Nonce"
HEADER_SIGNATURE = "X-Reva-Sig"
HEADER_RESPONSE_SIGNATURE = "X-Reva-Resp-Sig"

# The only paths the gateway serves. Anything else is a 404 before any auth logic runs.
ALLOWED_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", "/pair/start"),
    ("POST", "/pair/complete"),
    ("POST", "/sync/push"),
    ("POST", "/sync/pull"),
    ("POST", "/sync/ack"),
    ("POST", "/actions/propose"),
    ("POST", "/actions/status"),
)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    if not isinstance(text, str) or len(text) > 8192:
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not base64url") from exc


def spki_sha256(spki_der: bytes) -> str:
    """The pin and fingerprint input: SHA-256 of a public key's SubjectPublicKeyInfo DER, hex."""
    return hashlib.sha256(spki_der).hexdigest()


def load_public_key(spki_der: bytes) -> ec.EllipticCurvePublicKey:
    key = serialization.load_der_public_key(spki_der)
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("not a P-256 public key")
    return key


def verify(spki_der: bytes, message: bytes, signature_der: bytes) -> bool:
    try:
        load_public_key(spki_der).verify(signature_der, message, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False
    return True


# ------------------------------------------------------------------------------ QR payload


def make_qr_text(*, host: str, port: int, code: str, gateway_sha256: str, expires_at: int) -> str:
    """The text inside the QR code. Validated by contracts/pairing-qr.schema.json."""
    payload = {
        "v": QR_VERSION,
        "host": host,
        "port": port,
        "code": code,
        "gw": gateway_sha256,
        "exp": expires_at,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return QR_PREFIX + b64u(raw)


def parse_qr_text(text: str) -> dict[str, Any]:
    if not text.startswith(QR_PREFIX):
        raise ValueError("not a REVA pairing code")
    payload = json.loads(b64u_decode(text[len(QR_PREFIX) :]))
    if (
        not isinstance(payload, dict)
        or payload.get("v") != QR_VERSION
        or set(payload) != {"v", "host", "port", "code", "gw", "exp"}
    ):
        raise ValueError("unsupported pairing code")
    return payload


# ----------------------------------------------------------------- strings that are signed


def pair_start_message(code: str, gateway_sha256: str) -> bytes:
    return f"{PROTOCOL}\npair-start\n{code}\n{gateway_sha256}".encode()


def pair_complete_message(session_id: str, nonce: str, gateway_sha256: str) -> bytes:
    return f"{PROTOCOL}\npair-complete\n{session_id}\n{nonce}\n{gateway_sha256}".encode()


def request_message(
    method: str, path: str, timestamp: int, nonce: str, body: bytes, gateway_sha256: str
) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    return (
        f"{PROTOCOL}\nrequest\n{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}\n"
        f"{gateway_sha256}"
    ).encode()


def response_message(nonce: str, status: int, body: bytes) -> bytes:
    return f"{PROTOCOL}\nresponse\n{nonce}\n{status}\n{hashlib.sha256(body).hexdigest()}".encode()


# -------------------------------------------------------------------------------------- fingerprint


def fingerprint(gateway_sha256: str, phone_spki_der: bytes, session_id: str) -> str:
    """The 6 digits both screens show. Binds the gateway key, the phone key and this session."""
    digest = hashlib.sha256(
        b"REVA-GW1\nsas\n"
        + bytes.fromhex(gateway_sha256)
        + b"\n"
        + phone_spki_der
        + b"\n"
        + session_id.encode("ascii")
    ).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"
