"""Anthropic API key storage in the current user's Windows Credential Manager."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

_TARGET = "REVA/Anthropic"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _advapi32() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("Windows Credential Manager is required")
    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def read_anthropic_key() -> str | None:
    api = _advapi32()
    pointer = ctypes.POINTER(_Credential)()
    if not api.CredReadW(_TARGET, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        return None
    try:
        credential = pointer.contents
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        api.CredFree(pointer)


def write_anthropic_key(key: str) -> None:
    if not key or len(key) > 4096 or "\x00" in key:
        raise ValueError("invalid API key")
    api = _advapi32()
    blob = key.encode("utf-16-le")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _Credential()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = _TARGET
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = buffer
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "REVA"
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise RuntimeError("Credential Manager could not save the key")
