"""Windows DPAPI (CryptProtectData) for small local files.

Data is protected for the current Windows user, so another user account, or a copy of the file on
another machine, cannot read it. Used for state that must not sit on disk as plain text (the
dialogue state, which holds the names of recent transactions).

`protect` and `unprotect` raise `ProtectionError` and never include the data in the message.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class ProtectionError(RuntimeError):
    """The data could not be protected or unprotected (wrong user, damaged, DPAPI missing)."""


class Protector(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, data: bytes) -> bytes: ...


class _Blob(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes layout
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(data: bytes) -> tuple[_Blob, object]:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


class DpapiProtector:
    """DPAPI with a fixed `purpose` mixed in, so one REVA file type cannot be read as another."""

    def __init__(self, purpose: bytes) -> None:
        if sys.platform != "win32":
            raise ProtectionError("DPAPI is only available on Windows")
        self._purpose = purpose

    def protect(self, data: bytes) -> bytes:
        return self._call("CryptProtectData", data)

    def unprotect(self, data: bytes) -> bytes:
        return self._call("CryptUnprotectData", data)

    def _call(self, function: str, data: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined,unused-ignore]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        source, source_buffer = _blob(data)
        entropy, entropy_buffer = _blob(self._purpose)
        result = _Blob()
        if function == "CryptProtectData":
            ok = crypt32.CryptProtectData(
                ctypes.byref(source), None, ctypes.byref(entropy), None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result),
            )  # fmt: skip
        else:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(source), None, ctypes.byref(entropy), None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result),
            )  # fmt: skip
        del source_buffer, entropy_buffer
        if not ok:
            raise ProtectionError(f"{function} failed")
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            kernel32.LocalFree(result.pbData)
