"""A stand-in for Core that owns a Kokoro provider, for hard-kill tests.

Usage: python -m tests.fixtures.tts_host <workdir> [--no-job] [--exit-cleanly]

Prints one JSON line with the worker pid once the provider is healthy, then
waits. `--no-job` disables the kill-on-close job object (the control case:
without it, killing this process must leave the worker behind).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from reva_core.voice.kokoro_provider import KokoroSpeechProvider
from reva_core.voice.supervised_worker import ProcessJob
from tests.fixtures.kokoro_assets import IDS, write_assets


async def _main(workdir: Path, *, no_job: bool, exit_cleanly: bool) -> None:
    if no_job:
        ProcessJob.assign = lambda self, pid: False  # type: ignore[method-assign]
    root = workdir / "assets"
    manifest = write_assets(root)
    provider = KokoroSpeechProvider(
        python_exe=Path(sys.executable),
        manifest_path=manifest,
        asset_root=root,
        asset_ids=IDS,
        output_dir=workdir / "speech",
        worker_module="tests.fixtures.fake_kokoro_worker",
        ready_timeout_seconds=10.0,
    )
    await provider.health()
    print(json.dumps({"pid": provider.worker_pid}), flush=True)
    if exit_cleanly:
        await provider.shutdown()
        return
    await asyncio.sleep(120)


if __name__ == "__main__":
    asyncio.run(
        _main(
            Path(sys.argv[1]),
            no_job="--no-job" in sys.argv,
            exit_cleanly="--exit-cleanly" in sys.argv,
        )
    )
