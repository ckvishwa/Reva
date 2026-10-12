"""Key providers for the Domain Kernel (ADR-028: keys live in the OS vault, never in config).

`WindowsCredentialKeyProvider` stores one 32-byte key per domain in Windows Credential
Manager under the target name `reva.domain.<domain>` (for Finance: `reva.domain.finance`).
Credential Manager encrypts the secret for the current Windows user (DPAPI).

Safety rules enforced here:
* Only targets that start with the REVA prefix are ever read, written or deleted. The legacy
  AuraO entry `com.aura.assistant.finance` is never touched.
* `store_key` never replaces an existing key: losing a key loses the data it protects.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Protocol

ENTRY_PREFIX = "reva.domain."
_FORBIDDEN_FRAGMENTS = ("com.aura",)
KEY_LENGTH = 32

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class KeyStoreError(RuntimeError):
    """The vault could not be read or written. Message never contains key material."""


class DomainKeyProvider(Protocol):
    """Same shape as the Kernel's `KeyProvider` callback interface."""

    def load_key(self, domain: str) -> bytes | None: ...

    def store_key(self, domain: str, key: bytes) -> None: ...


def entry_name(domain: str, prefix: str = ENTRY_PREFIX) -> str:
    if not domain or not domain.replace("_", "").isalnum() or domain != domain.lower():
        raise KeyStoreError(f"invalid domain name {domain!r}")
    name = f"{prefix}{domain}"
    if any(fragment in name.lower() for fragment in _FORBIDDEN_FRAGMENTS):
        raise KeyStoreError("refusing to use a legacy AuraO credential entry")
    return name


class InMemoryKeyProvider:
    """For tests and tools. Never used by a running Core."""

    def __init__(self) -> None:
        self.keys: dict[str, bytes] = {}

    def load_key(self, domain: str) -> bytes | None:
        return self.keys.get(domain)

    def store_key(self, domain: str, key: bytes) -> None:
        if domain in self.keys:
            raise KeyStoreError("a key already exists for this domain")
        self.keys[domain] = bytes(key)


class _Credential(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes layout
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialKeyProvider:
    """Windows Credential Manager, via advapi32 (no third-party package)."""

    def __init__(self, prefix: str = ENTRY_PREFIX) -> None:
        if not sys.platform.startswith("win"):
            raise KeyStoreError("Windows Credential Manager is only available on Windows")
        if not prefix.startswith("reva."):
            raise KeyStoreError("credential prefix must start with 'reva.'")
        self._prefix = prefix
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    def entry(self, domain: str) -> str:
        return entry_name(domain, self._prefix)

    def load_key(self, domain: str) -> bytes | None:
        target = self.entry(domain)
        pointer = ctypes.POINTER(_Credential)()
        if not self._advapi.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise KeyStoreError(f"credential read failed (Windows error {error})")
        try:
            credential = pointer.contents
            size = int(credential.CredentialBlobSize)
            blob = bytes(ctypes.string_at(credential.CredentialBlob, size)) if size else b""
        finally:
            self._advapi.CredFree(pointer)
        if len(blob) != KEY_LENGTH:
            raise KeyStoreError("stored key has an unexpected length")
        return blob

    def store_key(self, domain: str, key: bytes) -> None:
        target = self.entry(domain)
        if len(key) != KEY_LENGTH:
            raise KeyStoreError("key must be exactly 32 bytes")
        if self.load_key(domain) is not None:
            raise KeyStoreError("a key already exists for this domain; refusing to replace it")
        blob = (ctypes.c_ubyte * len(key)).from_buffer_copy(bytes(key))
        credential = _Credential()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(key)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "reva"
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise KeyStoreError(
                f"credential write failed (Windows error {ctypes.get_last_error()})"
            )

    def delete_key(self, domain: str) -> bool:
        """Remove a key. Only for tests that created their own prefixed entry."""
        target = self.entry(domain)
        if self._advapi.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
            return True
        error = ctypes.get_last_error()
        if error == _ERROR_NOT_FOUND:
            return False
        raise KeyStoreError(f"credential delete failed (Windows error {error})")


class _UnavailableKeyProvider:
    """Used where no OS vault exists; every access fails, so a domain stays locked."""

    def load_key(self, domain: str) -> bytes | None:
        raise KeyStoreError("no OS key vault is available on this platform")

    def store_key(self, domain: str, key: bytes) -> None:
        raise KeyStoreError("no OS key vault is available on this platform")


def default_key_provider(keystore: str = "windows") -> DomainKeyProvider:
    if keystore == "memory":
        # Allowed only for a temp data directory (see `load_settings`).
        return InMemoryKeyProvider()
    # Tests must inject their own provider; they may never create or read the user's real keys.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return _UnavailableKeyProvider()
    if sys.platform.startswith("win"):
        return WindowsCredentialKeyProvider()
    return _UnavailableKeyProvider()
