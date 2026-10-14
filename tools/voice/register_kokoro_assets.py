"""Record the three Kokoro-82M files in an asset manifest, hashing the real files.

    python tools/voice/register_kokoro_assets.py --asset-root F:\\reva-assets
    python tools/voice/register_kokoro_assets.py --asset-root F:\\reva-assets \\
        --subset-out docs/voice/kokoro-assets.manifest.json

Adds or replaces exactly three entries (config, model weights, `af_heart` voice) in
`<asset-root>/assets.manifest.json` and leaves every other entry as it was. Hashes and sizes
come from the files on disk; nothing is typed by hand. `--subset-out` also writes a manifest that
holds only these three entries, which is the part that is safe to keep in git (the full manifest
names private recordings and stays under the asset root).

The license text is what the model card declares. This tool records it; it does not approve it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
SOURCE = (
    f"hexgrad/Kokoro-82M @ {REVISION} (huggingface.co), downloaded 2026-10-14; "
    "runs under kokoro==0.9.4, misaki==0.9.4, torch==2.14.1 (tools/voice/kokoro-requirements.txt)"
)
LICENSE = (
    "Apache-2.0 as declared by the model card (README.md beside the files). The card lists "
    "training audio under permissive terms including CC BY 3.0 and CC BY 4.0 sources, which ask "
    "for attribution; the card is kept next to the weights for that reason."
)
RELATIVE_DIR = Path("models") / "tts" / "kokoro" / "1.0"

_FILES: tuple[tuple[str, str, str, str], ...] = (
    (
        "models.tts.kokoro-82m.config",
        "config.json",
        "Kokoro-82M model configuration (vocab, hyper-parameters).",
        "tts_model",
    ),
    (
        "models.tts.kokoro-82m.model",
        "kokoro-v1_0.pth",
        "Kokoro-82M v1.0 weights (82M parameters).",
        "tts_model",
    ),
    (
        "models.tts.kokoro-82m.voice.af_heart",
        "voices/af_heart.pt",
        "Voice pack af_heart (American English, female), the REVA default voice.",
        "tts_model",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def build_entries(asset_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for asset_id, name, note, kind in _FILES:
        path = asset_root / RELATIVE_DIR / Path(*name.split("/"))
        if not path.is_file():
            raise SystemExit(f"missing file: {path}")
        entries.append(
            {
                "id": asset_id,
                "kind": kind,
                "path": str(Path("models") / "tts" / "kokoro" / "1.0" / Path(*name.split("/"))),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
                "engine": "kokoro",
                "version": f"1.0 ({REVISION[:7]})",
                "language": ["en"],
                "source": SOURCE,
                "license": LICENSE,
                "provenance_status": "licensed",
                "notes": note,
            }
        )
    return entries


def merge(manifest: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    replaced = {entry["id"] for entry in entries}
    kept = [a for a in manifest.get("assets", []) if a.get("id") not in replaced]
    manifest["assets"] = kept + entries
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--subset-out", type=Path, default=None)
    args = parser.parse_args()

    entries = build_entries(args.asset_root)
    manifest_path = args.asset_root / "assets.manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    else:
        manifest = {"manifest_version": "1.0", "asset_root": str(args.asset_root), "assets": []}
    manifest_path.write_text(
        json.dumps(merge(manifest, entries), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"updated {manifest_path} ({len(entries)} Kokoro entries)")

    if args.subset_out is not None:
        subset = {"manifest_version": "1.0", "asset_root": "<asset_root>", "assets": entries}
        args.subset_out.parent.mkdir(parents=True, exist_ok=True)
        args.subset_out.write_text(json.dumps(subset, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.subset_out}")
    for entry in entries:
        print(f"{entry['id']}  {entry['bytes']} bytes  sha256={entry['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
