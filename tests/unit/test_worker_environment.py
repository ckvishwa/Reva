"""TTS workers run with a minimal, offline environment, not Core's whole environment."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from reva_core.voice.supervised_worker import SupervisedWorker, worker_environment

_SECRETS = {
    "REVA_LOCAL_TOKEN": "local-token-value",
    "ANTHROPIC_API_KEY": "sk-ant-not-real",
    "PICOVOICE_ACCESS_KEY": "pico-not-real",
    "HF_TOKEN": "hf-not-real",
    "HTTPS_PROXY": "http://proxy.invalid:8080",
    "PYTHONSTARTUP": "C:/ide/pythonrc.py",
    "PYTHONPATH": "C:/somewhere",
}


def test_secrets_and_python_hooks_are_not_passed_on() -> None:
    base = {"PATH": "C:/Windows", "SYSTEMROOT": "C:/Windows", "TEMP": "C:/tmp", **_SECRETS}
    env = worker_environment(base)
    for name in _SECRETS:
        assert name not in env
    assert env["PATH"] == "C:/Windows"
    assert env["SYSTEMROOT"] == "C:/Windows"
    assert env["TEMP"] == "C:/tmp"


def test_the_worker_is_told_to_stay_offline() -> None:
    env = worker_environment({"PATH": "C:/Windows"})
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_names_are_matched_case_insensitively_like_windows() -> None:
    env = worker_environment({"Path": "C:/Windows", "SystemRoot": "C:/Windows", "Hf_Token": "x"})
    assert "C:/Windows" in env.values()
    assert not any(name.lower() == "hf_token" for name in env)


def test_launch_hands_the_worker_exactly_that_environment(tmp_path: Path) -> None:
    async def scenario() -> list[str]:
        worker = await SupervisedWorker.launch(
            [
                sys.executable,
                "-c",
                "import json, os; print(json.dumps({'names': sorted(os.environ)}), flush=True)",
            ],
            job=None,
            env={**worker_environment({"PATH": "C:/Windows", "SYSTEMROOT": "C:/Windows"})},
            cwd=tmp_path,
        )
        try:
            message = await worker.read_message()
            assert message is not None
            names: list[str] = message["names"]
            return names
        finally:
            await worker.terminate()

    names = {n.upper() for n in asyncio.run(scenario())}
    assert "REVA_LOCAL_TOKEN" not in names
    assert "HF_HUB_OFFLINE" in names
