"""Manifest-bound asset verification (AR-VA-020, ADR-038).

A voice or model loads only if every file it needs is listed in
`assets.manifest.json`, exists under the asset root, hashes to the
recorded SHA-256, and carries a provenance that is neither unfilled
nor excluded. Anything else is a refusal, and the caller falls back to
another provider instead of loading an unverified file.

This module reads the manifest and hashes files. It never writes, never
moves, and never follows a path out of the asset root.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any

from reva_core.shared.errors import ProviderError, ProviderErrorKind

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_UNVERIFIED_PROVENANCE = frozenset({"", "TODO"})
_HASH_CHUNK_BYTES = 1024 * 1024


class AssetRefusal(StrEnum):
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_INVALID = "manifest_invalid"
    UNLISTED = "unlisted"
    FILE_MISSING = "file_missing"
    HASH_MISMATCH = "hash_mismatch"
    HASH_NOT_RECORDED = "hash_not_recorded"
    PROVENANCE_UNVERIFIED = "provenance_unverified"
    EXCLUDED = "excluded"
    PATH_ESCAPE = "path_escape"


class AssetVerificationError(ProviderError):
    """A required asset failed verification. Never carries file contents."""

    def __init__(self, reason: AssetRefusal, asset_id: str) -> None:
        super().__init__(
            ProviderErrorKind.UNAVAILABLE, f"asset {asset_id!r} refused: {reason.value}"
        )
        self.reason = reason
        self.asset_id = asset_id


def verify_assets(
    manifest_path: Path, asset_root: Path, asset_ids: Sequence[str]
) -> dict[str, Path]:
    """Return `{asset_id: verified path}` or raise `AssetVerificationError`."""
    entries = _load_entries(manifest_path)
    root = asset_root.resolve()
    resolved: dict[str, Path] = {}
    for asset_id in asset_ids:
        entry = entries.get(asset_id)
        if entry is None:
            raise AssetVerificationError(AssetRefusal.UNLISTED, asset_id)
        resolved[asset_id] = _verify_entry(entry, asset_id, root)
    return resolved


def _load_entries(manifest_path: Path) -> dict[str, dict[str, Any]]:
    if not manifest_path.is_file():
        raise AssetVerificationError(AssetRefusal.MANIFEST_MISSING, "<manifest>")
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        assets = document["assets"]
        if not isinstance(assets, list):
            raise TypeError("assets must be a list")
        return {str(item["id"]): item for item in assets if isinstance(item, dict)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AssetVerificationError(AssetRefusal.MANIFEST_INVALID, "<manifest>") from exc


def _verify_entry(entry: dict[str, Any], asset_id: str, root: Path) -> Path:
    provenance = entry.get("provenance_status")
    if provenance == "excluded":
        raise AssetVerificationError(AssetRefusal.EXCLUDED, asset_id)
    if not isinstance(provenance, str) or provenance in _UNVERIFIED_PROVENANCE:
        raise AssetVerificationError(AssetRefusal.PROVENANCE_UNVERIFIED, asset_id)

    expected = entry.get("sha256")
    if not isinstance(expected, str) or not _SHA256_RE.match(expected):
        raise AssetVerificationError(AssetRefusal.HASH_NOT_RECORDED, asset_id)

    path = _resolve_under_root(root, entry.get("path"), asset_id)
    if not path.is_file():
        raise AssetVerificationError(AssetRefusal.FILE_MISSING, asset_id)
    if _sha256_of(path) != expected:
        raise AssetVerificationError(AssetRefusal.HASH_MISMATCH, asset_id)
    return path


def _resolve_under_root(root: Path, raw: object, asset_id: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise AssetVerificationError(AssetRefusal.MANIFEST_INVALID, asset_id)
    # Manifest paths are written with Windows separators; normalize either form.
    relative = Path(*PureWindowsPath(raw).parts)
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AssetVerificationError(AssetRefusal.PATH_ESCAPE, asset_id) from exc
    return candidate


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
