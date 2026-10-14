"""Fake Kokoro worker speaking the real worker's JSON-lines protocol.

Commands (one JSON object per stdin line):
  health                      -> {"status": "ready", ...}
  speak {text, language, output_dir}
                              -> N x {"status": "chunk", ...}, then {"status": "completed"}
  stop                        -> aborts the running speak with {"status": "stopped"}

Text switches the behavior under test:
  "slow"   many 50 ms chunks, so a stop can land mid-stream
  "hang"   one chunk, then ignores stop forever (forces the kill fallback)
  "crash"  one chunk, then the process dies
  other    three quick chunks

If a second `speak` arrives while one is still running the worker writes an
`overlap-detected` marker: the provider must have stopped the first one.
"""

from __future__ import annotations

import argparse
import json
import math
import queue
import struct
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any

SAMPLE_RATE = 24_000
CHUNK_MS = 100


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _write_chunk(path: Path) -> None:
    frames = int(SAMPLE_RATE * CHUNK_MS / 1000)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for i in range(frames):
            wav.writeframesraw(
                struct.pack("<h", int(1200 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE)))
            )


def _reader(commands: queue.Queue[dict[str, Any] | None]) -> None:
    for line in sys.stdin:
        commands.put(json.loads(line))
    commands.put(None)


def _speak(request: dict[str, Any], commands: queue.Queue[dict[str, Any] | None]) -> bool:
    request_id = request["id"]
    text = request["text"]
    output_dir = Path(request["output_dir"])
    if text == "slow":
        count, delay = 40, 0.05
    elif text in {"hang", "crash"}:
        count, delay = 1, 0.0
    else:
        count, delay = 3, 0.01

    for index in range(count):
        try:
            pending = commands.get_nowait()
        except queue.Empty:
            pending = {}
        if pending is None:
            return False
        if pending.get("command") == "speak":
            (output_dir / "overlap-detected").write_text("overlap", encoding="utf-8")
        if pending.get("command") == "stop" and text != "hang":
            _emit({"id": request_id, "status": "stopped"})
            return True
        if delay:
            time.sleep(delay)
        path = output_dir / f"chunk-{request_id}-{index}.wav"
        _write_chunk(path)
        _emit(
            {
                "id": request_id,
                "status": "chunk",
                "index": index,
                "output_path": str(path),
                "sample_rate": SAMPLE_RATE,
                "duration_ms": CHUNK_MS,
                "final": index == count - 1,
            }
        )
        if text == "crash":
            sys.exit(9)
    if text == "hang":
        time.sleep(60)
    _emit({"id": request_id, "status": "completed"})
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("--config-path", "--model-path", "--voice-path", "--voice", "--device"):
        parser.add_argument(name, default="")
    args = parser.parse_args()

    commands: queue.Queue[dict[str, Any] | None] = queue.Queue()
    threading.Thread(target=_reader, args=(commands,), daemon=True).start()
    while True:
        request = commands.get()
        if request is None:
            return 0
        if request["command"] == "health":
            _emit(
                {
                    "id": request["id"],
                    "status": "ready",
                    "voice": args.voice,
                    "sample_rate": SAMPLE_RATE,
                }
            )
        elif request["command"] == "speak" and not _speak(request, commands):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
