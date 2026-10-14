"""The Kokoro worker's stdout carries the JSON protocol and nothing else.

Real Kokoro (0.9.x) prints `WARNING: Defaulting repo_id to hexgrad/Kokoro-82M` to stdout while it
loads. Any non-JSON line on that pipe makes Core refuse the worker, so the worker must keep the
library's output off the protocol channel. These tests run the real worker module against a stub
`kokoro` package that is noisy on purpose; the real package is covered by the opt-in tests in
`tests/integration/test_kokoro_real.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_NOISY_KOKORO = textwrap.dedent(
    """
    import sys

    class _Tensor:
        def detach(self): return self
        def cpu(self): return self
        def flatten(self): return self
        def tolist(self): return [0.0, 0.25, -0.25, 0.0] * 600

    class _Result:
        audio = _Tensor()

    class KModel:
        def __init__(self, config, model):
            print("WARNING: Defaulting repo_id to hexgrad/Kokoro-82M", flush=True)
        def to(self, device): return self
        def eval(self): return self

    class KPipeline:
        def __init__(self, lang_code, model):
            print("WARNING: another library line on stdout", flush=True)
        def __call__(self, text, voice, speed):
            print("loading voice " + voice, flush=True)
            yield _Result()
    """
)


def _run_worker(tmp_path: Path, commands: list[dict[str, object]]) -> list[str]:
    stub = tmp_path / "stub"
    (stub / "kokoro").mkdir(parents=True)
    (stub / "kokoro" / "__init__.py").write_text(_NOISY_KOKORO, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(stub), "PYTHONIOENCODING": "utf-8"}
    stdin = "".join(json.dumps(c) + "\n" for c in commands)
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed module, temp stub package
        [
            sys.executable,
            "-m",
            "reva_core.voice.kokoro_worker",
            "--config-path",
            str(tmp_path / "config.json"),
            "--model-path",
            str(tmp_path / "model.pth"),
            "--voice-path",
            str(tmp_path / "voice.pt"),
        ],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def test_library_noise_never_reaches_the_protocol_channel(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    lines = _run_worker(
        tmp_path,
        [
            {"command": "health", "id": "h1"},
            {"command": "speak", "id": "s1", "text": "Hello there.", "output_dir": str(out_dir)},
        ],
    )

    messages = []
    for line in lines:
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:  # pragma: no cover - the failure being guarded against
            pytest.fail(f"non-JSON line on the protocol channel: {line!r}")
    statuses = [(m.get("id"), m.get("status")) for m in messages]
    assert ("h1", "ready") in statuses


def test_the_noise_is_kept_on_stderr_not_lost(tmp_path: Path) -> None:
    stub = tmp_path / "stub"
    (stub / "kokoro").mkdir(parents=True)
    (stub / "kokoro" / "__init__.py").write_text(_NOISY_KOKORO, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(stub)}
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed module, temp stub package
        [
            sys.executable,
            "-m",
            "reva_core.voice.kokoro_worker",
            "--config-path",
            "c",
            "--model-path",
            "m",
            "--voice-path",
            "v",
        ],
        input=json.dumps({"command": "health", "id": "h1"}) + "\n",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=60,
        check=False,
    )
    assert "Defaulting repo_id" not in done.stdout
    assert "Defaulting repo_id" in done.stderr
