"""Kokoro-82M worker: newline-delimited JSON over stdin/stdout.

Runs under a dedicated interpreter that has the `kokoro` package; Core never
imports it. Core passes manifest-verified local files, so nothing is
downloaded at run time.

Verified against kokoro 0.9.4 + torch 2.14.1 (CPU) with the Kokoro-82M v1.0
weights by `tests/integration/test_kokoro_real.py` (opt-in: it needs the
interpreter and assets named in `docs/voice/kokoro-production.md`). CI has no
`kokoro` package; there the protocol, chunking and stop handling are covered by
`tests/fixtures/fake_kokoro_worker.py` and `tests/unit/test_kokoro_worker_protocol.py`.

stdout is the protocol channel and nothing else may write to it. Kokoro prints
log lines to stdout while it loads, so the real stdout is saved for `_emit`
and `sys.stdout` is pointed at stderr before the library is imported.

Commands:
  health                      load the model, reply {"status": "ready"}
  speak {text, output_dir}    one WAV per sentence: {"status": "chunk", ...}
                              then {"status": "completed"}
  stop                        abort the running speak with {"status": "stopped"}
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import queue
import re
import sys
import threading
import time
import wave
from array import array
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TextIO

SAMPLE_RATE = 24_000
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_END = re.compile(r"[,;:]\s+")

# First-audio budget (S06). Kokoro starts a phrase with a stretch of near-silence; on the first
# chunk of an utterance it is trimmed so nobody waits for silence. A long first sentence is cut at
# its first real clause, so audio starts after one clause is synthesized, not the whole sentence.
LEADING_SILENCE_FLOOR = 0.003  # about -50 dBFS
LEADING_KEEP_MS = 20
FIRST_SENTENCE_MIN_CHARS = 60
CLAUSE_MIN_CHARS = 12
CLAUSE_MAX_CHARS = 80


def trim_leading_silence(samples: list[float]) -> list[float]:
    """Drop the near-silence before the first sound, keeping 20 ms. All-silent audio stays."""
    keep = SAMPLE_RATE * LEADING_KEEP_MS // 1000
    for index, sample in enumerate(samples):
        if abs(sample) >= LEADING_SILENCE_FLOOR:
            return samples[max(0, index - keep) :]
    return samples


def split_for_synthesis(text: str) -> list[str]:
    """Sentences, with a long first sentence cut at its first clause that can stand on its own."""
    sentences = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]
    if not sentences or len(sentences[0]) < FIRST_SENTENCE_MIN_CHARS:
        return sentences
    first = sentences[0]
    for match in _CLAUSE_END.finditer(first):
        clause = first[: match.start() + 1]
        rest = first[match.end() :]
        if CLAUSE_MIN_CHARS <= len(clause) <= CLAUSE_MAX_CHARS and rest.strip():
            return [clause, rest, *sentences[1:]]
    return sentences


_ERROR_BROKEN_PIPE = 109
_ERROR_NO_DATA = 232
_POLL_SECONDS = 0.01
_EXIT_JOIN_SECONDS = 10.0

# The protocol channel. `main()` points sys.stdout at stderr so library output cannot reach it.
_protocol: TextIO = sys.stdout
_emit_lock = threading.Lock()


def _claim_protocol_channel() -> None:
    global _protocol
    _protocol = sys.stdout
    sys.stdout = sys.stderr


def _emit(payload: dict[str, Any]) -> None:
    with _emit_lock:
        _protocol.write(json.dumps(payload) + "\n")
        _protocol.flush()


def _blocking_lines(fd: int, pending: bytes = b"") -> Iterator[str]:
    with open(fd, "rb", closefd=False) as stream:
        data = pending + stream.read() if pending else None
        if data is not None:
            for raw in data.splitlines(keepends=True):
                yield raw.decode("utf-8")
            return
        for raw in stream:
            yield raw.decode("utf-8")


def stdin_lines(fd: int | None = None) -> Iterator[str]:
    """Yield input lines. On a Windows pipe, poll instead of blocking in `ReadFile`.

    A thread parked in a blocking read on an anonymous pipe makes `import numpy` hang in the
    main thread (so `import torch` and `import kokoro` hang too). Peeking for data first means
    no read is ever outstanding. Files and consoles cannot be peeked and are read normally.
    """
    if fd is None:
        fd = sys.stdin.fileno()
    if sys.platform != "win32":
        yield from _blocking_lines(fd)
        return

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(fd)
    pending = b""
    while True:
        available = wintypes.DWORD(0)
        if not kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            if ctypes.get_last_error() in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                break  # the writer closed its end: end of input
            yield from _blocking_lines(fd, pending)
            return
        if available.value == 0:
            time.sleep(_POLL_SECONDS)
            continue
        data = os.read(fd, available.value)
        if not data:
            break
        pending += data
        while (newline := pending.find(b"\n")) >= 0:
            line, pending = pending[: newline + 1], pending[newline + 1 :]
            yield line.decode("utf-8")
    if pending:
        yield pending.decode("utf-8")


def _reader(commands: queue.Queue[dict[str, Any] | None]) -> None:
    for line in stdin_lines():
        if not line.strip():
            continue
        try:
            command = json.loads(line)
        except json.JSONDecodeError:
            _emit({"id": None, "status": "error", "kind": "protocol"})
            continue
        if isinstance(command, dict):
            commands.put(command)
    commands.put(None)


def _load_pipeline(args: argparse.Namespace) -> Any:
    kokoro = importlib.import_module("kokoro")
    model = kokoro.KModel(config=args.config_path, model=args.model_path)
    model = model.to(args.device).eval()
    return kokoro.KPipeline(lang_code="a", model=model)


def _segment_audio(result: Any) -> Any:
    audio = getattr(result, "audio", None)
    return audio if audio is not None else result[2]


def _write_wav(path: Path, samples: list[float]) -> None:
    pcm = array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


class _Utterance:
    """One `speak` request. Exactly one terminal message is ever sent for it."""

    def __init__(self, request_id: Any) -> None:
        self.id = request_id
        self.cancelled = threading.Event()
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ended = False

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def end(self, status: str, **extra: Any) -> bool:
        with self._lock:
            if self._ended:
                return False
            self._ended = True
            _emit({"id": self.id, "status": status, **extra})
            return True

    def emit_chunk(self, payload: dict[str, Any]) -> bool:
        """Send a chunk unless the utterance already ended (stopped, failed)."""
        with self._lock:
            if self._ended or self.cancelled.is_set():
                return False
            _emit(payload)
            return True

    def stop(self) -> None:
        """Acknowledge at once. The sentence being synthesized finishes unseen."""
        self.cancelled.set()
        self.end("stopped")


def _requested_speed(request: dict[str, Any]) -> float:
    try:
        value = float(request.get("speed", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return min(1.2, max(0.8, value)) if value == value else 1.0


def _synthesize(
    pipeline: Any, voice_path: str, request: dict[str, Any], utterance: _Utterance
) -> None:
    request_id = request["id"]
    output_dir = Path(request["output_dir"])
    sentences = split_for_synthesis(str(request["text"]))
    speed = _requested_speed(request)
    try:
        for index, sentence in enumerate(sentences):
            if utterance.cancelled.is_set():
                return
            samples: list[float] = []
            for result in pipeline(sentence, voice=voice_path, speed=speed):
                samples.extend(_segment_audio(result).detach().cpu().flatten().tolist())
            if not samples or utterance.cancelled.is_set():
                continue
            if index == 0:
                samples = trim_leading_silence(samples)
            path = output_dir / f"chunk-{request_id}-{index}.wav"
            _write_wav(path, samples)
            sent = utterance.emit_chunk(
                {
                    "id": request_id,
                    "status": "chunk",
                    "index": index,
                    "output_path": str(path),
                    "sample_rate": SAMPLE_RATE,
                    "duration_ms": int(len(samples) * 1000 / SAMPLE_RATE),
                    "final": index == len(sentences) - 1,
                }
            )
            if not sent:
                path.unlink(missing_ok=True)  # stopped while this sentence was being written
                return
        utterance.end("completed")
    except Exception:
        # Never leak engine internals over the protocol; Core maps this to UNAVAILABLE.
        utterance.end("error", kind="engine")


def main() -> int:
    _claim_protocol_channel()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--voice-path", required=True)
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    commands: queue.Queue[dict[str, Any] | None] = queue.Queue()
    threading.Thread(target=_reader, args=(commands,), daemon=True).start()
    pipeline: Any = None
    active: _Utterance | None = None
    while True:
        request = commands.get()
        if request is None:
            if active is not None and active.running:
                active.stop()
                if active.thread is not None:
                    active.thread.join(timeout=_EXIT_JOIN_SECONDS)
            return 0
        command = request.get("command")
        if command == "stop":
            if active is not None and request.get("id") in (None, active.id):
                active.stop()
            continue
        try:
            if command == "health":
                if pipeline is None:
                    pipeline = _load_pipeline(args)
                _emit(
                    {
                        "id": request["id"],
                        "status": "ready",
                        "voice": args.voice,
                        "sample_rate": SAMPLE_RATE,
                    }
                )
            elif command == "speak":
                if pipeline is None:
                    pipeline = _load_pipeline(args)
                if active is not None and active.thread is not None:
                    # The model is shared: let an interrupted sentence finish before reusing it.
                    active.thread.join()
                active = _Utterance(request["id"])
                active.thread = threading.Thread(
                    target=_synthesize,
                    args=(pipeline, args.voice_path, request, active),
                    daemon=True,
                )
                active.thread.start()
        except Exception:
            # Never leak engine internals over the protocol; Core maps this to UNAVAILABLE.
            _emit({"id": request.get("id"), "status": "error", "kind": "engine"})


if __name__ == "__main__":
    raise SystemExit(main())
