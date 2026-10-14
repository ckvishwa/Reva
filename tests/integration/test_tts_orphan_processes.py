"""AR-VA-008: zero orphan TTS worker processes after the owner is killed.

These start a real host process and a real worker process and check PIDs.
Windows only: the guarantee comes from a kill-on-close job object.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.process_utils import pid_alive, wait_until_dead

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows-only")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _start_host(workdir: Path, *flags: str) -> tuple[subprocess.Popen[str], int]:
    host = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "tests.fixtures.tts_host", str(workdir), *flags],
        stdout=subprocess.PIPE,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert host.stdout is not None
    line = host.stdout.readline()
    assert line, "host exited before reporting the worker pid"
    return host, int(json.loads(line)["pid"])


def test_killing_the_owner_kills_the_worker(tmp_path):
    host, worker_pid = _start_host(tmp_path)
    try:
        assert pid_alive(worker_pid)
        host.kill()  # TerminateProcess on the host only, not the process tree
        host.wait(timeout=10)

        assert wait_until_dead(worker_pid, 5.0), "worker survived its owner"
    finally:
        if pid_alive(worker_pid):
            os.kill(worker_pid, 9)


def test_control_without_the_job_object_the_worker_would_be_orphaned(tmp_path):
    """Proves the test above can fail: with the guard disabled the worker survives."""
    host, worker_pid = _start_host(tmp_path, "--no-job")
    try:
        host.kill()
        host.wait(timeout=10)

        assert pid_alive(worker_pid), "control invalid: worker died without the job object"
    finally:
        if pid_alive(worker_pid):
            os.kill(worker_pid, 9)
        wait_until_dead(worker_pid, 5.0)


def test_clean_shutdown_leaves_no_worker(tmp_path):
    host, worker_pid = _start_host(tmp_path, "--exit-cleanly")
    try:
        host.wait(timeout=15)

        assert wait_until_dead(worker_pid, 5.0)
    finally:
        if pid_alive(worker_pid):
            os.kill(worker_pid, 9)
