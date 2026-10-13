"""Test and fixture helper: two Kernel installs that trust each other and exchange signed events.

The Kernel no longer exposes an unauthenticated way to apply events from another install, so tests
and the fixture generator that simulate "a phone" pair two handles and sync them the way the real
transport does: export signed events, apply them on the other side, acknowledge the cursor.
Keys are generated in memory by `cryptography`; nothing here touches a real vault.
"""

from __future__ import annotations

from typing import Any


def make_device_key(binding: Any) -> Any:
    """A device key held in memory, implementing the Kernel's `DeviceSigner` callback interface."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    class DeviceKey(binding.DeviceSigner):  # type: ignore[misc]
        def __init__(self) -> None:
            self._key = ec.generate_private_key(ec.SECP256R1())

        def public_key(self) -> bytes:
            return self._key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )

        def sign(self, message: bytes) -> bytes:
            return self._key.sign(bytes(message), ec.ECDSA(hashes.SHA256()))

    return DeviceKey()


def pair(binding: Any, first: Any, second: Any, label: str = "Test device") -> None:
    """Give both handles a device key and register each as the other's peer (finance scope)."""
    keys = {id(first): make_device_key(binding), id(second): make_device_key(binding)}
    first.set_signer(keys[id(first)])
    second.set_signer(keys[id(second)])
    first.register_peer(second.device_id(), keys[id(second)].public_key(), label, ["finance"])
    second.register_peer(first.device_id(), keys[id(first)].public_key(), label, ["finance"])


def push(sender: Any, receiver: Any, limit: int = 500) -> Any:
    """Export from `sender`, apply on `receiver`, acknowledge. Returns the ApplyReport."""
    batch = sender.sync_export(receiver.device_id(), limit)
    report = receiver.sync_apply(sender.device_id(), batch)
    sender.sync_ack(receiver.device_id(), batch.cursor_to)
    return report
