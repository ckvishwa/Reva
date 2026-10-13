"""Test-environment guard: tests never touch real data (CLAUDE.md rule 5).

`check_env` is pure so it can be unit tested; the root `conftest.py` enforces it
before any test is collected.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DATA_DIR_VAR = "REVA_DATA_DIR"


def _is_db_url_var(name: str) -> bool:
    upper = name.upper()
    return upper in {
        "DATABASE_URL",
        "SUPABASE_URL",
        "POSTGRES_URL",
        "POSTGRESQL_URL",
    } or upper.endswith(("_DATABASE_URL", "_DB_URL"))


def check_env(environ: Mapping[str, str], temp_root: Path | None = None) -> list[str]:
    """Return a list of problems; empty means the environment is safe for tests."""
    problems: list[str] = []
    root = (temp_root or Path(tempfile.gettempdir())).resolve()

    data_dir = environ.get(DATA_DIR_VAR)
    if data_dir:
        resolved = Path(data_dir).resolve()
        if resolved == root or root not in resolved.parents:
            problems.append(
                f"{DATA_DIR_VAR} must be a directory inside the temp dir {root}, got {resolved}"
            )

    for name, value in environ.items():
        if not value or not _is_db_url_var(name):
            continue
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        # `sqlite:///file` has no host and is a local file; anything with a host must be local.
        if host and host not in LOCAL_HOSTS:
            problems.append(
                f"{name} points at a non-local host ({host}); tests may only use localhost"
            )
    return problems
