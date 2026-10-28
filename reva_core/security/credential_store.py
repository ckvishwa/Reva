"""Secret strings (API keys) in Windows Credential Manager (CLAUDE.md rule 6).

`WindowsSecretStore` keeps one secret under a `reva.provider.<name>` target name; Credential
Manager encrypts it for the current Windows user. The secret is never logged, never put in an
exception message and never returned by an API: `read` is for the process that calls the provider.

Under pytest the default store refuses every call, so a test can never read or write the owner's
real keys. Tests inject `InMemorySecretStore` (or a throw-away `reva.test.*` target).
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Protocol

from reva_core.security.windows_api import windows_last_error

TARGET_PREFIX = "reva.provider."
MAX_SECRET_CHARS = 512

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class SecretStoreError(RuntimeError):
    """The vault could not be used. The message never contains the secret."""


class SecretStore(Protocol):
    def read(self) -> str | None: ...

    def write(self, secret: str) -> None: ...

    def delete(self) -> bool: ...


def check_secret(secret: str) -> str:
    if (
        not secret
        or len(secret) > MAX_SECRET_CHARS
        or any(c.isspace() or c == "\x00" for c in secret)
    ):
        raise SecretStoreError("the secret is empty, too long or contains whitespace")
    return secret


class InMemorySecretStore:
    """For tests and tools. Never used by a running Core."""

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret

    def read(self) -> str | None:
        return self._secret

    def write(self, secret: str) -> None:
        self._secret = check_secret(secret)

    def delete(self) -> bool:
        had, self._secret = self._secret is not None, None
        return had


class UnavailableSecretStore:
    """No OS vault (or running under pytest): every access fails closed."""

    def read(self) -> str | None:
        raise SecretStoreError("no OS secret store is available")

    def write(self, secret: str) -> None:
        raise SecretStoreError("no OS secret store is available")

    def delete(self) -> bool:
        raise SecretStoreError("no OS secret store is available")


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


class WindowsSecretStore:
    _target: str
    _advapi: ctypes.CDLL

    def __init__(self, name: str) -> None:
        if not sys.platform.startswith("win"):
            raise SecretStoreError("Windows Credential Manager is only available on Windows")
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise SecretStoreError("invalid secret name")
        self._target = f"{TARGET_PREFIX}{name}"
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        advapi.CredReadW.restype = wintypes.BOOL
        advapi.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        advapi.CredWriteW.restype = wintypes.BOOL
        advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        advapi.CredDeleteW.restype = wintypes.BOOL
        advapi.CredFree.argtypes = [ctypes.c_void_p]
        advapi.CredFree.restype = None
        self._advapi = advapi

    def read(self) -> str | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self._advapi.CredReadW(self._target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = windows_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise SecretStoreError(f"credential read failed (Windows error {error})")
        try:
            credential = pointer.contents
            size = int(credential.CredentialBlobSize)
            raw = ctypes.string_at(credential.CredentialBlob, size) if size else b""
        finally:
            self._advapi.CredFree(pointer)
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise SecretStoreError("stored secret is not valid text") from exc

    def write(self, secret: str) -> None:
        blob_bytes = check_secret(secret).encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(blob_bytes)).from_buffer_copy(blob_bytes)
        credential = _Credential()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = self._target
        credential.CredentialBlobSize = len(blob_bytes)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "reva"
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise SecretStoreError(
                f"credential write failed (Windows error {windows_last_error()})"
            )

    def delete(self) -> bool:
        if self._advapi.CredDeleteW(self._target, _CRED_TYPE_GENERIC, 0):
            return True
        error = windows_last_error()
        if error == _ERROR_NOT_FOUND:
            return False
        raise SecretStoreError(f"credential delete failed (Windows error {error})")


def default_secret_store(name: str) -> SecretStore:
    # Tests must inject their own store; they may never read or write the owner's real secrets.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return UnavailableSecretStore()
    if sys.platform.startswith("win"):
        return WindowsSecretStore(name)
    return UnavailableSecretStore()
