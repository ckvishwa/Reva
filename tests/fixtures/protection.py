"""Test-only authenticated protector. Never imported by production code.

This exercises dialogue persistence and purpose isolation, not Windows DPAPI.
Keys live only for one test; files are confined to pytest's guarded temporary data.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from reva_core.security.dpapi import ProtectionError


class TestProtector:
    __test__ = False

    def __init__(self, key: bytes, purpose: bytes) -> None:
        self._cipher = AESGCM(key)
        self._purpose = purpose

    def protect(self, data: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(nonce, data, self._purpose)

    def unprotect(self, data: bytes) -> bytes:
        if len(data) < 28:
            raise ProtectionError("invalid test ciphertext")
        try:
            return self._cipher.decrypt(data[:12], data[12:], self._purpose)
        except InvalidTag as exc:
            raise ProtectionError("invalid test ciphertext or purpose") from exc
