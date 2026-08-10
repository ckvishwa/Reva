#!/usr/bin/env python3
"""Manual troubleshooting helper: create a scratch SQLite DB, run
migrations, print the resulting schema version, then run again against
the same file to prove idempotence. Exits non-zero on any failure.

Usage (PowerShell):
    python scripts/verify_bootstrap.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reva_core.storage.bootstrap import initialize_database  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "reva.db"

        conn, version = initialize_database(db_path)
        conn.close()
        print(f"first bootstrap: schema_version={version}")

        conn, version_again = initialize_database(db_path)
        conn.close()
        print(f"restart bootstrap: schema_version={version_again}")

        if version != version_again:
            print("FAIL: schema version changed on restart", file=sys.stderr)
            return 1

        print("OK: bootstrap is idempotent")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
