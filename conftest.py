"""Repo-root pytest hooks: environment guard and opt-in suites."""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from tests.env_guard import DATA_DIR_VAR, check_env

_session_data_dir: str | None = None


def pytest_configure(config: pytest.Config) -> None:
    global _session_data_dir
    problems = check_env(os.environ)
    if problems:
        raise pytest.UsageError("REVA test environment guard failed: " + "; ".join(problems))
    if not os.environ.get(DATA_DIR_VAR):
        # No test may fall back to the default ./data directory.
        _session_data_dir = tempfile.mkdtemp(prefix="reva-pytest-")
        os.environ[DATA_DIR_VAR] = _session_data_dir


def pytest_unconfigure(config: pytest.Config) -> None:
    if _session_data_dir:
        os.environ.pop(DATA_DIR_VAR, None)
        shutil.rmtree(_session_data_dir, ignore_errors=True)


def _voice_evals_enabled() -> bool:
    # Opt-in: REVA_RUN_VOICE_EVALS=1, and the audio dependencies must be installed.
    return (
        os.environ.get("REVA_RUN_VOICE_EVALS") == "1"
        and importlib.util.find_spec("soundfile") is not None
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if "voice-evals" in collection_path.parts and not _voice_evals_enabled():
        return True
    return None


def pytest_report_header(config: pytest.Config) -> str | None:
    if not _voice_evals_enabled():
        return "tests/voice-evals skipped (opt in: REVA_RUN_VOICE_EVALS=1 and soundfile installed)"
    return None
