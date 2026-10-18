"""Native OS guarantees remain distinct from portable dialogue fixture coverage."""

from __future__ import annotations

import sys

import pytest

from reva_core.security.dpapi import DpapiProtector, ProtectionError
from reva_core.security.windows_api import windows_last_error
from tests.fixtures.protection import TestProtector


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows refusal contract")
def test_production_dpapi_still_refuses_without_windows():
    with pytest.raises(ProtectionError, match="only available on Windows"):
        DpapiProtector(b"test")
    with pytest.raises(OSError, match="only available on Windows"):
        windows_last_error()


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows DPAPI")
def test_native_dpapi_round_trip_and_ciphertext(tmp_path):
    from reva_core.language.dialogue import FileDialogueStore

    # Also pin the real consumer: the Windows autouse fixture must never substitute it.
    store = FileDialogueStore(tmp_path / "dialogue")
    assert isinstance(store._protector, DpapiProtector)
    protector = DpapiProtector(b"reva.test.native")
    secret = b"throwaway dialogue content"
    encrypted = protector.protect(secret)
    assert secret not in encrypted
    assert protector.unprotect(encrypted) == secret


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows DPAPI")
def test_native_dpapi_rejects_other_purpose_and_tampering():
    protector = DpapiProtector(b"reva.test.native")
    encrypted = protector.protect(b"throwaway")
    with pytest.raises(ProtectionError):
        DpapiProtector(b"reva.test.other").unprotect(encrypted)
    damaged = bytearray(encrypted)
    damaged[len(damaged) // 2] ^= 1
    with pytest.raises(ProtectionError):
        protector.unprotect(bytes(damaged))


def test_test_protector_checks_purpose_key_and_integrity():
    first = TestProtector(b"a" * 32, b"dialogue")
    raw = first.protect(b"test content")
    assert first.unprotect(raw) == b"test content"
    for other in (TestProtector(b"b" * 32, b"dialogue"), TestProtector(b"a" * 32, b"other")):
        with pytest.raises(ProtectionError):
            other.unprotect(raw)
    with pytest.raises(ProtectionError):
        first.unprotect(raw[:-1])
