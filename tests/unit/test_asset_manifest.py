"""AR-VA-020: a voice loads only if its files match assets.manifest.json."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reva_core.providers.asset_manifest import (
    AssetRefusal,
    AssetVerificationError,
    verify_assets,
)
from reva_core.shared.errors import ProviderError


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(root: Path, entries: list[dict[str, object]]) -> Path:
    path = root / "assets.manifest.json"
    path.write_text(
        json.dumps({"manifest_version": "1.0", "asset_root": str(root), "assets": entries}),
        encoding="utf-8",
    )
    return path


def _entry(asset_id: str, rel: str, data: bytes, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": asset_id,
        "kind": "tts_model",
        "path": rel,
        "sha256": _sha(data),
        "bytes": len(data),
        "source": "test",
        "license": "apache-2.0",
        "provenance_status": "licensed",
    }
    entry.update(overrides)
    return entry


def _refusal(manifest: Path, root: Path, ids: list[str]) -> AssetVerificationError:
    with pytest.raises(AssetVerificationError) as excinfo:
        verify_assets(manifest, root, ids)
    return excinfo.value


def test_matching_listed_asset_resolves_to_its_path(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "voice.pt").write_bytes(b"voice-bytes")
    manifest = _manifest(tmp_path, [_entry("voice", "models\\voice.pt", b"voice-bytes")])

    resolved = verify_assets(manifest, tmp_path, ["voice"])

    assert resolved == {"voice": tmp_path / "models" / "voice.pt"}


def test_tampered_file_is_refused_with_hash_mismatch(tmp_path):
    (tmp_path / "voice.pt").write_bytes(b"tampered")
    manifest = _manifest(tmp_path, [_entry("voice", "voice.pt", b"original")])

    error = _refusal(manifest, tmp_path, ["voice"])

    assert error.reason == AssetRefusal.HASH_MISMATCH
    assert error.asset_id == "voice"


def test_missing_file_is_refused(tmp_path):
    manifest = _manifest(tmp_path, [_entry("voice", "voice.pt", b"x")])

    assert _refusal(manifest, tmp_path, ["voice"]).reason == AssetRefusal.FILE_MISSING


def test_unlisted_asset_is_refused(tmp_path):
    (tmp_path / "voice.pt").write_bytes(b"x")
    manifest = _manifest(tmp_path, [])

    assert _refusal(manifest, tmp_path, ["voice"]).reason == AssetRefusal.UNLISTED


def test_missing_manifest_is_refused(tmp_path):
    error = _refusal(tmp_path / "assets.manifest.json", tmp_path, ["voice"])

    assert error.reason == AssetRefusal.MANIFEST_MISSING


def test_invalid_manifest_is_refused(tmp_path):
    path = tmp_path / "assets.manifest.json"
    path.write_text("{not json", encoding="utf-8")

    assert _refusal(path, tmp_path, ["voice"]).reason == AssetRefusal.MANIFEST_INVALID


@pytest.mark.parametrize("status", ["TODO", "", None])
def test_unverified_provenance_is_refused(tmp_path, status):
    (tmp_path / "voice.pt").write_bytes(b"x")
    manifest = _manifest(tmp_path, [_entry("voice", "voice.pt", b"x", provenance_status=status)])

    assert _refusal(manifest, tmp_path, ["voice"]).reason == AssetRefusal.PROVENANCE_UNVERIFIED


def test_excluded_asset_is_refused_even_when_hash_matches(tmp_path):
    (tmp_path / "voice.pt").write_bytes(b"x")
    manifest = _manifest(
        tmp_path, [_entry("voice", "voice.pt", b"x", provenance_status="excluded")]
    )

    assert _refusal(manifest, tmp_path, ["voice"]).reason == AssetRefusal.EXCLUDED


@pytest.mark.parametrize("recorded", ["TODO", "DIRECTORY", ""])
def test_unrecorded_hash_is_refused(tmp_path, recorded):
    (tmp_path / "voice.pt").write_bytes(b"x")
    manifest = _manifest(tmp_path, [_entry("voice", "voice.pt", b"x", sha256=recorded)])

    assert _refusal(manifest, tmp_path, ["voice"]).reason == AssetRefusal.HASH_NOT_RECORDED


def test_path_escaping_the_asset_root_is_refused(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.pt").write_bytes(b"x")
    manifest = _manifest(root, [_entry("voice", "..\\outside.pt", b"x")])

    assert _refusal(manifest, root, ["voice"]).reason == AssetRefusal.PATH_ESCAPE


def test_one_bad_asset_refuses_the_whole_set(tmp_path):
    (tmp_path / "a.pt").write_bytes(b"a")
    (tmp_path / "b.pt").write_bytes(b"wrong")
    manifest = _manifest(tmp_path, [_entry("a", "a.pt", b"a"), _entry("b", "b.pt", b"b")])

    error = _refusal(manifest, tmp_path, ["a", "b"])

    assert error.asset_id == "b"


def test_refusal_is_a_provider_error_so_callers_can_fall_back(tmp_path):
    manifest = _manifest(tmp_path, [])

    with pytest.raises(ProviderError):
        verify_assets(manifest, tmp_path, ["voice"])
