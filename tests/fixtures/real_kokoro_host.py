"""A stand-in for Core that owns the REAL Kokoro provider, for hard-kill tests.

Usage: python -m tests.fixtures.real_kokoro_host <workdir>

Needs the variables listed in `tests/fixtures/real_kokoro.py`. Prints one JSON line with the
worker pid once the real model is loaded, then waits to be killed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from tests.fixtures.real_kokoro import make_provider, real_kokoro


async def _main(workdir: Path) -> None:
    provider = make_provider(real_kokoro(), workdir / "speech")
    await provider.health()
    print(json.dumps({"pid": provider.worker_pid}), flush=True)
    await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(_main(Path(sys.argv[1])))
