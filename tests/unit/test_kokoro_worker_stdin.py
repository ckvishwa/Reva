"""The Kokoro worker reads stdin without holding a blocking read on a Windows pipe.

On Windows a thread blocked in `ReadFile` on an anonymous pipe makes `import numpy` (and with it
`import torch` and `import kokoro`) hang in the main thread. The worker has exactly that shape:
a reader thread on stdin plus a lazy `import kokoro` on the first `health` command. Found with
the real package; reproduced here with a stub that only imports numpy.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from reva_core.voice import kokoro_worker

REPO_ROOT = Path(__file__).resolve().parents[2]


def _collect(lines: Iterator[str], sink: queue.Queue[str | None]) -> None:
    for line in lines:
        sink.put(line)
    sink.put(None)


def test_lines_arrive_as_they_are_written_and_the_end_is_seen() -> None:
    read_fd, write_fd = os.pipe()
    sink: queue.Queue[str | None] = queue.Queue()
    threading.Thread(
        target=_collect, args=(kokoro_worker.stdin_lines(read_fd), sink), daemon=True
    ).start()
    try:
        os.write(write_fd, b'{"a": 1}\n{"b": 2}\n')
        assert sink.get(timeout=5) == '{"a": 1}\n'
        assert sink.get(timeout=5) == '{"b": 2}\n'

        os.write(write_fd, b'{"c"')  # a partial line is held back, not delivered
        with pytest.raises(queue.Empty):
            sink.get(timeout=0.3)
        os.write(write_fd, b": 3}\n")
        assert sink.get(timeout=5) == '{"c": 3}\n'
    finally:
        os.close(write_fd)
    assert sink.get(timeout=5) is None
    os.close(read_fd)


def test_a_final_line_without_a_newline_is_delivered_at_end_of_input() -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b'{"last": true}')
    os.close(write_fd)
    assert list(kokoro_worker.stdin_lines(read_fd)) == ['{"last": true}']
    os.close(read_fd)


_STUB_IMPORTS_NUMPY = """
import numpy  # the import that hangs while a thread is blocked reading a stdin pipe

class _Tensor:
    def detach(self): return self
    def cpu(self): return self
    def flatten(self): return self
    def tolist(self): return [0.0]

class KModel:
    def __init__(self, config, model): pass
    def to(self, device): return self
    def eval(self): return self

class KPipeline:
    def __init__(self, lang_code, model): pass
    def __call__(self, text, voice, speed): return iter(())
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the pipe/ReadFile hang is Windows-specific")
def test_the_first_command_is_not_stuck_behind_a_heavy_import(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    stub = tmp_path / "stub"
    (stub / "kokoro").mkdir(parents=True)
    (stub / "kokoro" / "__init__.py").write_text(_STUB_IMPORTS_NUMPY, encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed module, temp stub package
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
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(stub)},
    )
    assert process.stdin is not None and process.stdout is not None
    reply: queue.Queue[bytes] = queue.Queue()
    threading.Thread(target=lambda: reply.put(process.stdout.readline()), daemon=True).start()
    try:
        process.stdin.write(json.dumps({"command": "health", "id": "h1"}).encode() + b"\n")
        process.stdin.flush()
        line = reply.get(timeout=30)
        assert json.loads(line)["status"] == "ready"
    finally:
        process.kill()
        process.wait(timeout=10)
