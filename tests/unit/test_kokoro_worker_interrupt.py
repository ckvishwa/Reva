"""The Kokoro worker acknowledges `stop` at once, even in the middle of a sentence.

Real synthesis takes most of a second per sentence. If the worker could only look for `stop`
between sentences, Core's short acknowledgement window would expire and Core would kill the
worker, so the next utterance would wait for a full model reload (about 9 s with the real
model). These tests run the real worker module against a deliberately slow stub `kokoro`.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_SLOW_KOKORO = textwrap.dedent(
    """
    import time

    class _Tensor:
        def detach(self): return self
        def cpu(self): return self
        def flatten(self): return self
        def tolist(self): return [0.1, -0.1] * 1200

    class _Result:
        audio = _Tensor()

    class KModel:
        def __init__(self, config, model): pass
        def to(self, device): return self
        def eval(self): return self

    class KPipeline:
        def __init__(self, lang_code, model): pass
        def __call__(self, text, voice, speed):
            time.sleep(0.6)  # one sentence of "synthesis"
            yield _Result()
    """
)

THREE_SENTENCES = "First sentence here. Second sentence here. Third sentence here."


class _Worker:
    def __init__(self, tmp_path: Path) -> None:
        stub = tmp_path / "stub"
        (stub / "kokoro").mkdir(parents=True)
        (stub / "kokoro" / "__init__.py").write_text(_SLOW_KOKORO, encoding="utf-8")
        self.output_dir = tmp_path / "out"
        self.process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed module, stub
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
        assert self.process.stdin is not None and self.process.stdout is not None
        self.messages: queue.Queue[dict[str, object]] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            self.messages.put(json.loads(raw))

    def send(self, **command: object) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(command).encode() + b"\n")
        self.process.stdin.flush()

    def next(self, timeout: float = 10.0) -> dict[str, object]:
        return self.messages.get(timeout=timeout)

    def next_with_status(self, status: str, timeout: float = 10.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while True:
            message = self.next(max(0.01, deadline - time.monotonic()))
            if message.get("status") == status:
                return message

    def speak(self, request_id: str, text: str = THREE_SENTENCES) -> None:
        self.send(command="speak", id=request_id, text=text, output_dir=str(self.output_dir))

    def close(self) -> None:
        self.process.kill()
        self.process.wait(timeout=10)


@pytest.fixture
def worker(tmp_path: Path):
    w = _Worker(tmp_path)
    w.send(command="health", id="h")
    assert w.next_with_status("ready")["id"] == "h"
    yield w
    w.close()


def test_stop_is_acknowledged_within_a_fraction_of_a_sentence(worker: _Worker) -> None:
    worker.speak("s1")
    assert (
        worker.next_with_status("chunk")["id"] == "s1"
    )  # sentence 1 is out; sentence 2 is running

    sent = time.monotonic()
    worker.send(command="stop", id="s1")
    stopped = worker.next_with_status("stopped", timeout=5)
    elapsed = time.monotonic() - sent

    assert stopped["id"] == "s1"
    assert elapsed < 0.3, f"stop took {elapsed:.2f}s; a sentence takes 0.6s"


def test_nothing_is_sent_after_the_stop_acknowledgement(worker: _Worker) -> None:
    worker.speak("s1")
    worker.next_with_status("chunk")
    worker.send(command="stop", id="s1")
    worker.next_with_status("stopped")

    time.sleep(1.5)  # long enough for the interrupted sentence to finish internally
    leftovers = []
    while True:
        try:
            leftovers.append(worker.messages.get_nowait())
        except queue.Empty:
            break
    assert leftovers == []


def test_the_same_worker_speaks_again_after_a_stop(worker: _Worker) -> None:
    pid = worker.process.pid
    worker.speak("s1")
    worker.next_with_status("chunk")
    worker.send(command="stop", id="s1")
    worker.next_with_status("stopped")

    worker.speak("s2", "Short one.")
    chunk = worker.next_with_status("chunk", timeout=10)
    assert chunk["id"] == "s2"
    assert worker.next_with_status("completed", timeout=10)["id"] == "s2"
    assert worker.process.poll() is None
    assert worker.process.pid == pid


def test_stop_while_idle_changes_nothing(worker: _Worker) -> None:
    worker.send(command="stop", id="nothing-running")
    worker.send(command="health", id="h2")
    assert worker.next_with_status("ready")["id"] == "h2"


def test_closing_stdin_mid_sentence_ends_the_worker(worker: _Worker) -> None:
    worker.speak("s1")
    worker.next_with_status("chunk")
    assert worker.process.stdin is not None
    worker.process.stdin.close()
    assert worker.process.wait(timeout=5) == 0
