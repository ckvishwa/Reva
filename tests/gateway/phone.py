"""A phone for tests: its own Kernel, its own P-256 key, and a TLS client that pins the gateway.

It speaks the real wire protocol (reva_core/gateway/protocol.py) to a real gateway listener on
127.0.0.1 with a real self-signed certificate. Nothing here touches a real vault or real data: the
Kernel runs on an in-memory key provider in a temp directory.
"""

from __future__ import annotations

import http.client
import json
import secrets
import ssl
import time
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from reva_core.domains.kernel_loader import load_kernel
from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.gateway import protocol


class PinMismatch(Exception):
    """The server's TLS key is not the one in the QR code."""


class BadResponseSignature(Exception):
    """An authenticated response was not signed by the paired PC."""


class Reply:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status = status
        self.body = body
        self.headers = {k.lower(): v for k, v in headers.items()}

    def json(self) -> dict[str, Any]:
        parsed: dict[str, Any] = json.loads(self.body)
        return parsed


class Phone:
    def __init__(self, directory: Path, name: str = "Test phone") -> None:
        self.binding = load_kernel()
        self.name = name
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        binding = self.binding
        phone = self

        class _Signer(binding.DeviceSigner):  # type: ignore[misc]
            def public_key(self) -> bytes:
                return phone.public

            def sign(self, message: bytes) -> bytes:
                return phone.sign(bytes(message))

        self.kernel = binding.open_domain("finance", InMemoryKeyProvider(), str(directory))
        self.kernel.set_signer(_Signer())
        self.device_id: str | None = None
        self.host = ""
        self.port = 0
        self.gateway_sha256 = ""
        self.pc_signing_key: bytes | None = None
        self.pc_kernel_id: str | None = None
        self.skew = 0  # seconds added to the phone's clock
        self.clock = time.time

    # ------------------------------------------------------------------------------ crypto

    def sign(self, message: bytes) -> bytes:
        return self.key.sign(message, ec.ECDSA(hashes.SHA256()))

    # --------------------------------------------------------------------------- transport

    def point_at(self, qr_text: str) -> dict[str, Any]:
        """Read the QR code: remember the address and the pinned gateway key."""
        payload = protocol.parse_qr_text(qr_text)
        self.host, self.port, self.gateway_sha256 = payload["host"], payload["port"], payload["gw"]
        return payload

    def request(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        *,
        pin: str | None = None,
    ) -> Reply:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # the pin below replaces CA validation
        connection = http.client.HTTPSConnection(self.host, self.port, context=context, timeout=15)
        try:
            connection.connect()
            assert connection.sock is not None
            der = connection.sock.getpeercert(binary_form=True)
            assert der is not None
            spki = (
                x509.load_der_x509_certificate(der)
                .public_key()
                .public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
                )
            )
            if protocol.spki_sha256(spki) != (pin or self.gateway_sha256):
                raise PinMismatch("the gateway's TLS key is not the one in the QR code")
            all_headers = {"Content-Type": "application/json", **(headers or {})}
            connection.request(method, path, body=body, headers=all_headers)
            response = connection.getresponse()
            return Reply(response.status, response.read(), dict(response.getheaders()))
        finally:
            connection.close()

    def post(self, path: str, data: dict[str, Any], **kwargs: Any) -> Reply:
        return self.request("POST", path, json.dumps(data).encode(), **kwargs)

    # ----------------------------------------------------------------------------- pairing

    def start_pairing(self, qr_text: str, **override: Any) -> Reply:
        payload = self.point_at(qr_text)
        code = override.pop("code", payload["code"])
        body = {
            "code": code,
            "name": self.name,
            "platform": "android",
            "public_key": protocol.b64u(self.public),
            "kernel_devices": {"finance": self.kernel.device_id()},
            "proof": protocol.b64u(
                self.sign(protocol.pair_start_message(code, self.gateway_sha256))
            ),
            **override,
        }
        return self.post("/pair/start", body)

    def expected_fingerprint(self, session_id: str) -> str:
        return protocol.fingerprint(self.gateway_sha256, self.public, session_id)

    def poll_pairing(self, session_id: str, nonce: str | None = None) -> Reply:
        nonce = nonce or secrets.token_urlsafe(16)
        proof = self.sign(protocol.pair_complete_message(session_id, nonce, self.gateway_sha256))
        return self.post(
            "/pair/complete",
            {"session_id": session_id, "nonce": nonce, "proof": protocol.b64u(proof)},
        )

    def finish_pairing(self, reply: Reply) -> None:
        """Take the approved grant: remember our id and register the PC as a Kernel peer."""
        grant = reply.json()
        gateway = grant["gateway"]
        self.device_id = grant["device_id"]
        self.pc_signing_key = protocol.b64u_decode(gateway["signing_public_key"])
        self.pc_kernel_id = gateway["kernel_devices"]["finance"]
        assert gateway["tls_sha256"] == self.gateway_sha256
        # Re-pairing starts from nothing: forget what the PC was believed to hold.
        peers = {p.device_id: p for p in self.kernel.list_peers()}
        if self.pc_kernel_id in peers and peers[self.pc_kernel_id].status == "active":
            self.kernel.revoke_peer(self.pc_kernel_id)
        self.kernel.register_peer(self.pc_kernel_id, self.pc_signing_key, "PC", ["finance"])

    # ------------------------------------------------------------------------------- sync

    def signed(
        self,
        path: str,
        data: dict[str, Any],
        *,
        nonce: str | None = None,
        timestamp: int | None = None,
        device_id: str | None = None,
        tamper_body: bool = False,
        verify_reply: bool = True,
    ) -> Reply:
        body = json.dumps(data).encode()
        nonce = nonce or secrets.token_urlsafe(16)
        timestamp = int(self.clock()) + self.skew if timestamp is None else timestamp
        signature = self.sign(
            protocol.request_message("POST", path, timestamp, nonce, body, self.gateway_sha256)
        )
        if tamper_body:
            body = body.replace(b"finance", b"finance ")
        reply = self.request(
            "POST",
            path,
            body,
            {
                protocol.HEADER_DEVICE: device_id or self.device_id or "",
                protocol.HEADER_TIMESTAMP: str(timestamp),
                protocol.HEADER_NONCE: nonce,
                protocol.HEADER_SIGNATURE: protocol.b64u(signature),
            },
        )
        if verify_reply and reply.status == 200:
            self.check_reply(reply, nonce)
        return reply

    def check_reply(self, reply: Reply, nonce: str) -> None:
        signature = reply.headers.get(protocol.HEADER_RESPONSE_SIGNATURE.lower())
        assert self.pc_signing_key is not None
        if signature is None or not protocol.verify(
            self.pc_signing_key,
            protocol.response_message(nonce, reply.status, reply.body),
            protocol.b64u_decode(signature),
        ):
            raise BadResponseSignature("the answer was not signed by the paired PC")

    def push(self, limit: int = 500, **kwargs: Any) -> Reply:
        assert self.pc_kernel_id is not None
        batch = self.kernel.sync_export(self.pc_kernel_id, limit)
        data = {
            "domain": "finance",
            "events_json": batch.events_json,
            "cursor_from": batch.cursor_from,
            "cursor_to": batch.cursor_to,
            "count": batch.count,
        }
        reply = self.signed("/sync/push", data, **kwargs)
        if reply.status == 200:
            self.kernel.sync_ack(self.pc_kernel_id, reply.json()["ack_cursor"])
        return reply

    def pull(self, limit: int = 500, **kwargs: Any) -> tuple[Reply, Any]:
        """Pull, register directory entries, apply, acknowledge. Returns (reply, ApplyReport)."""
        reply = self.signed("/sync/pull", {"domain": "finance", "limit": limit}, **kwargs)
        if reply.status != 200:
            return reply, None
        data = reply.json()
        for entry in data["directory"]:
            self.kernel.register_peer(
                entry["device_id"],
                protocol.b64u_decode(entry["public_key"]),
                entry["label"],
                ["finance"],
            )
        assert self.pc_kernel_id is not None
        batch = self.binding.SyncBatch(
            events_json=data["events_json"],
            cursor_from=data["cursor_from"],
            cursor_to=data["cursor_to"],
            count=data["count"],
        )
        report = self.kernel.sync_apply(self.pc_kernel_id, batch)
        ack = self.signed("/sync/ack", {"domain": "finance", "cursor": data["cursor_to"]})
        assert ack.status == 200, ack.body
        return reply, report
