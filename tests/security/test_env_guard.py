"""The pytest environment guard, unit-tested and proven in a spawned pytest child."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tests.env_guard import check_env

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = "tests/unit/test_settings.py"


def _run_child(env_overrides: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "REVA_DATA_DIR"}
    env.update(env_overrides)
    return subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_check_env_accepts_temp_data_dir_and_localhost_urls(tmp_path):
    env = {
        "REVA_DATA_DIR": str(tmp_path),
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "REVA_DB_URL": "sqlite:///x.db",
    }
    assert check_env(env) == []


@pytest.mark.parametrize(
    "env",
    [
        {"REVA_DATA_DIR": str(Path.home() / "reva-data")},
        {"REVA_DATA_DIR": "./data"},
        {"DATABASE_URL": "postgresql://u:p@db.example.com/prod"},
        {"SUPABASE_URL": "https://abcd.supabase.co"},
        {"REVA_SYNC_DATABASE_URL": "postgres://10.0.0.5/reva"},
    ],
)
def test_check_env_rejects_unsafe_values(env):
    assert check_env(env)


def test_check_env_rejects_the_temp_root_itself():
    assert check_env({"REVA_DATA_DIR": tempfile.gettempdir()})


def test_child_pytest_refuses_a_non_temp_data_dir(tmp_path):
    result = _run_child({"REVA_DATA_DIR": str(Path.home() / "reva-data")}, tmp_path)
    assert result.returncode != 0
    assert "environment guard failed" in (result.stdout + result.stderr)


def test_child_pytest_refuses_a_remote_database_url(tmp_path):
    result = _run_child(
        {"REVA_DATA_DIR": str(tmp_path), "DATABASE_URL": "postgresql://u:p@db.example.com/prod"},
        tmp_path,
    )
    assert result.returncode != 0
    assert "non-local host" in (result.stdout + result.stderr)


def test_child_pytest_runs_with_a_temp_data_dir_and_localhost_url(tmp_path):
    result = _run_child(
        {"REVA_DATA_DIR": str(tmp_path), "DATABASE_URL": "postgresql://u:p@127.0.0.1/test"},
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_child_pytest_without_data_dir_gets_a_private_temp_dir(tmp_path):
    result = _run_child({}, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
