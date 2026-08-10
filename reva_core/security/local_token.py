"""Local Core API authentication token.

**Interim development implementation.** The token is a high-entropy
random string generated once on first startup and stored as a plain
file under REVA's local data directory. This is explicitly a stand-in
for the planned Windows Credential Manager / DPAPI-protected storage
(see docs/security/security-invariants.md) — it is not encrypted at
rest, it relies entirely on Windows filesystem/NTFS permissions on the
containing directory (the same directory `reva.db` lives in, already
excluded from source control and already assumed single-user-owned).

The token is never returned by any API response, never logged, and is
compared using a constant-time comparison (`hmac.compare_digest`) to
avoid timing side channels.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from pathlib import Path

TOKEN_FILENAME = "local_auth_token"  # noqa: S105 - a filename, not a credential
_TOKEN_BYTES = 32  # 256 bits of entropy


def token_path_for(data_dir: Path) -> Path:
    return data_dir / TOKEN_FILENAME


def ensure_local_token(data_dir: Path) -> str:
    """Return the local auth token, generating and persisting one on
    first call. Idempotent: a second call (e.g. after restart) returns
    the same token rather than rotating it.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    path = token_path_for(data_dir)

    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    path.write_text(token, encoding="utf-8")
    # Best-effort on Windows: os.chmod has limited effect on NTFS, the
    # real control is the containing directory's ACLs (owned by the
    # local user, same as reva.db). Never fails startup if this doesn't
    # apply on the current platform/filesystem.
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return token
