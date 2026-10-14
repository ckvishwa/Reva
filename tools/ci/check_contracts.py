"""Contracts lane: validate every schema in contracts/ and keep it in sync with the spec pack.

Usage: python tools/ci/check_contracts.py [repo_root]
Exit code 0 when everything is valid, 1 otherwise. Requires the `jsonschema` package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema.validators import validator_for

SPEC_DIR = Path("docs/spec/REVA_v2.0/08_CONTRACTS")
CONTRACTS_DIR = Path("contracts")


def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def check(root: Path) -> list[str]:
    errors: list[str] = []
    contracts = root / CONTRACTS_DIR
    spec = root / SPEC_DIR

    schemas = sorted(contracts.glob("*.schema.json"))
    if not schemas:
        errors.append(f"no *.schema.json files found in {CONTRACTS_DIR}")

    ids: dict[str, str] = {}
    for path in schemas:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            validator_for(schema).check_schema(schema)
        except Exception as exc:  # noqa: BLE001 - report every bad schema
            errors.append(f"{path.name}: invalid JSON Schema: {exc}")
            continue
        schema_id = schema.get("$id")
        if schema_id:
            if schema_id in ids:
                errors.append(f"{path.name}: $id {schema_id} already used by {ids[schema_id]}")
            ids[schema_id] = path.name

    for path in sorted(contracts.glob("*.json")):
        if path.name.endswith(".schema.json"):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{path.name}: invalid JSON: {exc}")

    if spec.is_dir():
        ours = {p.name for p in contracts.iterdir() if p.is_file() and p.name != "README.md"}
        theirs = {p.name for p in spec.iterdir() if p.is_file()}
        for name in sorted(ours ^ theirs):
            errors.append(f"{name}: present in only one of contracts/ and {SPEC_DIR}")
        for name in sorted(ours & theirs):
            if _normalised(contracts / name) != _normalised(spec / name):
                errors.append(f"{name}: contracts/ and {SPEC_DIR} differ")
    else:
        errors.append(f"{SPEC_DIR} is missing")
    return errors


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    errors = check(root)
    for line in errors:
        print(f"FAIL {line}")
    count = len(list((root / CONTRACTS_DIR).glob("*.schema.json")))
    print(f"checked {count} schemas, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
