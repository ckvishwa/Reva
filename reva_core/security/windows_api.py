"""Typed access to Windows' thread-local error code; never a non-Windows fallback."""

from __future__ import annotations

import ctypes
import sys


def windows_last_error() -> int:
    if sys.platform == "win32":
        return ctypes.get_last_error()
    raise OSError("Windows error codes are only available on Windows")
