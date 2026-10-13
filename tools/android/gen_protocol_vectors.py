"""Shared test vectors for the gateway wire format, written from the Python reference (protocol.py).

    python tools/android/gen_protocol_vectors.py           # rewrite the vector file
    python tools/android/gen_protocol_vectors.py --check # fail if it no longer matches protocol.py

The Android JVM tests (GatewayProtocolTest.kt) read the same file, so the phone and the PC cannot
drift apart silently. The ECDSA signature in the file is made once, with a throw-away key that
exists only for this vector; --check verifies it instead of re-signing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "android" / "app" / "src" / "test" / "resources" / "protocol_vectors.json"

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from reva_core.gateway import protocol as p  # noqa: E402

GW = "ab" * 32
CODE = "A1b2C3d4E5f6G7h8I9j0K1"
SESSION = "sess_0123456789abcdef"
NONCE = "nonce_0123456789abcdef"


def _key() -> ec.EllipticCurvePrivateKey:
    # Fixed scalar: a vector key, never used for anything else.
    return ec.derive_private_key(
        0x1F2E3D4C5B6A79880123456789ABCDEF0123456789ABCDEF0123456789ABCDEF, ec.SECP256R1()
    )


def _spki(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def build(existing: dict | None = None) -> dict:
    key = _key()
    spki = _spki(key)
    body = '{"domain":"finance","limit":5}'
    message = p.request_message("POST", "/sync/pull", 1800000000, NONCE, body.encode(), GW)
    signature = (
        p.b64u_decode(existing["signature"]["signature_b64u"])
        if existing
        else key.sign(message, ec.ECDSA(hashes.SHA256()))
    )
    qr_text = p.make_qr_text(
        host="192.168.1.20", port=47821, code=CODE, gateway_sha256=GW, expires_at=1800000120
    )
    return {
        "b64u": [
            {"hex": h, "b64u": p.b64u(bytes.fromhex(h))}
            for h in ("", "00", "fbff", "00ff10", "deadbeefcafe")
        ],
        "spki": {"b64u": p.b64u(spki), "sha256": p.spki_sha256(spki)},
        "fingerprint": [
            {
                "gw": GW,
                "spki_b64u": p.b64u(spki),
                "session": SESSION,
                "expected": p.fingerprint(GW, spki, SESSION),
            },
            {
                "gw": GW,
                "spki_b64u": p.b64u(spki),
                "session": "other",
                "expected": p.fingerprint(GW, spki, "other"),
            },
        ],
        "messages": {
            "gateway": GW,
            "code": CODE,
            "session": SESSION,
            "nonce": NONCE,
            "pair_start": p.pair_start_message(CODE, GW).decode(),
            "pair_complete": p.pair_complete_message(SESSION, NONCE, GW).decode(),
            "request": {
                "method": "POST",
                "path": "/sync/pull",
                "timestamp": 1800000000,
                "body": body,
                "text": message.decode(),
            },
            "response": {
                "status": 200,
                "body": '{"count":0}',
                "text": p.response_message(NONCE, 200, b'{"count":0}').decode(),
            },
        },
        "qr": {
            "text": qr_text,
            "payload": p.parse_qr_text(qr_text),
            "bad_texts": ["", "REVA-PAIR1:", "REVA-PAIR1:e30", "OTHER:" + qr_text.split(":", 1)[1]],
        },
        "signature": {
            "public_b64u": p.b64u(spki),
            "message": message.decode(),
            "signature_b64u": p.b64u(signature),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        current = json.loads(OUT.read_text(encoding="utf-8"))
        if build(current) != current:
            print("protocol_vectors.json is out of date with reva_core/gateway/protocol.py")
            return 1
        sig = current["signature"]
        if not p.verify(
            p.b64u_decode(sig["public_b64u"]),
            sig["message"].encode(),
            p.b64u_decode(sig["signature_b64u"]),
        ):
            print("vector signature does not verify")
            return 1
        print("vectors are current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    OUT.write_text(json.dumps(build(existing), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
