"""The PC's gateway identity: a TLS key and a device-signing key, both P-256, both in the OS vault.

Windows keeps them in Credential Manager under `reva.gateway.tls` and `reva.gateway.device`
(32-byte private scalars; the entry prefix is checked by `WindowsCredentialKeyProvider`, so nothing
else in the vault can be read or replaced). The certificate is public and rebuilt in memory at every
start; phones pin the SHA-256 of the TLS *public key*, which only changes if the entry is removed.

Private keys never reach a log, a file in the data directory, or the Kernel: the Kernel gets a
`DeviceSigner` that asks this object to sign.
"""

from __future__ import annotations

import datetime
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from reva_core.domains.keys import (
    KEY_LENGTH,
    DomainKeyProvider,
    InMemoryKeyProvider,
    KeyStoreError,
    WindowsCredentialKeyProvider,
    ensure_memory_keystore_allowed,
)
from reva_core.gateway.protocol import spki_sha256

GATEWAY_ENTRY_PREFIX = "reva.gateway."
_CERT_YEARS = 10


def gateway_key_provider(keystore: str, data_dir: Path) -> DomainKeyProvider:
    """The vault for gateway keys. Same rules as domain keys: tests never reach the real one."""
    if keystore == "memory":
        ensure_memory_keystore_allowed(data_dir)
        return InMemoryKeyProvider()
    if "PYTEST_CURRENT_TEST" in os.environ:
        return _UnavailableProvider()
    return WindowsCredentialKeyProvider(prefix=GATEWAY_ENTRY_PREFIX)


class _UnavailableProvider:
    def load_key(self, domain: str) -> bytes | None:
        raise KeyStoreError("no OS key vault is available here")

    def store_key(self, domain: str, key: bytes) -> None:
        raise KeyStoreError("no OS key vault is available here")


def _load_or_create(provider: DomainKeyProvider, name: str) -> ec.EllipticCurvePrivateKey:
    raw = provider.load_key(name)
    if raw is None:
        key = ec.generate_private_key(ec.SECP256R1())
        provider.store_key(name, key.private_numbers().private_value.to_bytes(KEY_LENGTH, "big"))
        return key
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def _spki(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


class GatewayIdentity:
    def __init__(self, provider: DomainKeyProvider) -> None:
        self._tls = _load_or_create(provider, "tls")
        self._device = _load_or_create(provider, "device")
        self.tls_spki = _spki(self._tls)
        self.tls_sha256 = spki_sha256(self.tls_spki)
        self.device_spki = _spki(self._device)

    def sign(self, message: bytes) -> bytes:
        """ECDSA P-256 / SHA-256, DER: what the Kernel's `DeviceSigner` and the phone expect."""
        return self._device.sign(message, ec.ECDSA(hashes.SHA256()))

    def certificate_pem(self) -> bytes:
        now = datetime.datetime.now(datetime.UTC)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "REVA Gateway")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self._tls.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=365 * _CERT_YEARS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(self._tls, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.PEM)

    def write_tls_files(self, directory: Path) -> tuple[Path, Path, str]:
        """Write the certificate and an *encrypted* private key for the TLS server to load, and
        return their paths and the one-time password. Callers delete both files right after the
        server has loaded them, so a plain private key never sits on disk."""
        directory.mkdir(parents=True, exist_ok=True)
        password = os.urandom(24).hex()
        key_pem = self._tls.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password.encode()),
        )
        cert_path = _write_temp(directory, ".pem", self.certificate_pem())
        key_path = _write_temp(directory, ".key", key_pem)
        return cert_path, key_path, password


def _write_temp(directory: Path, suffix: str, data: bytes) -> Path:
    handle, name = tempfile.mkstemp(dir=directory, prefix="gw-", suffix=suffix)
    with os.fdopen(handle, "wb") as out:
        out.write(data)
    return Path(name)


def make_kernel_signer(binding: Any, identity: GatewayIdentity) -> Any:
    """A Kernel `DeviceSigner` backed by the PC's device key."""

    class PcDeviceSigner(binding.DeviceSigner):  # type: ignore[misc]
        def public_key(self) -> bytes:
            return identity.device_spki

        def sign(self, message: bytes) -> bytes:
            return identity.sign(bytes(message))

    return PcDeviceSigner()
