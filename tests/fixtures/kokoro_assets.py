"""Builds a tiny manifest-verified asset set for Kokoro provider tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reva_core.voice.kokoro_provider import KokoroAssetIds

IDS = KokoroAssetIds(config="kokoro.config", model="kokoro.model", voice="kokoro.voice.af_heart")

_FILES = {
    "kokoro.config": ("config.json", b'{"vocab": {}}'),
    "kokoro.model": ("kokoro-v1_0.pth", b"model-weights"),
    "kokoro.voice.af_heart": ("af_heart.pt", b"voice-tensor"),
}


def write_assets(root: Path, *, tamper: str | None = None) -> Path:
    """Write the three files plus a manifest; `tamper` corrupts one file after hashing."""
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for asset_id, (name, data) in _FILES.items():
        (root / name).write_bytes(b"TAMPERED" if asset_id == tamper else data)
        entries.append(
            {
                "id": asset_id,
                "kind": "tts_model",
                "path": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "source": "test",
                "license": "apache-2.0",
                "provenance_status": "licensed",
            }
        )
    manifest = root / "assets.manifest.json"
    manifest.write_text(
        json.dumps({"manifest_version": "1.0", "asset_root": str(root), "assets": entries}),
        encoding="utf-8",
    )
    return manifest
