"""Kokoro-82M worker: newline-delimited JSON over stdin/stdout.

Runs under a dedicated interpreter that has the `kokoro` package; Core never
imports it. Core passes manifest-verified local files, so nothing is
downloaded at run time.

UNVERIFIED against a real Kokoro install: this repository's CI and the
audit machine have no `kokoro` package or weights. The protocol, chunking
and stop handling are covered by `tests/fixtures/fake_kokoro_worker.py`,
which speaks the same protocol. The `kokoro` API calls below follow the
upstream 0.9.x `KModel` / `KPipeline` interface and must be confirmed by a
real synthesis run before anyone relies on them.

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
import queue
import re
import sys
import threading
import wave
from array import array
from pathlib import Path
from typing import Any

SAMPLE_RATE = 24_000
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _reader(commands: queue.Queue[dict[str, Any] | None]) -> None:
    for line in sys.stdin:
        commands.put(json.loads(line))
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


def _stop_requested(commands: queue.Queue[dict[str, Any] | None]) -> bool | None:
    """True on `stop`, None on EOF, False otherwise."""
    try:
        pending = commands.get_nowait()
    except queue.Empty:
        return False
    if pending is None:
        return None
    return pending.get("command") == "stop"


def _speak(
    pipeline: Any,
    voice_path: str,
    request: dict[str, Any],
    commands: queue.Queue[dict[str, Any] | None],
) -> bool:
    request_id = request["id"]
    output_dir = Path(request["output_dir"])
    sentences = [s for s in _SENTENCE_SPLIT.split(str(request["text"]).strip()) if s]
    for index, sentence in enumerate(sentences):
        stop = _stop_requested(commands)
        if stop is None:
            return False
        if stop:
            _emit({"id": request_id, "status": "stopped"})
            return True
        samples: list[float] = []
        for result in pipeline(sentence, voice=voice_path, speed=1.0):
            samples.extend(_segment_audio(result).detach().cpu().flatten().tolist())
        if not samples:
            continue
        path = output_dir / f"chunk-{request_id}-{index}.wav"
        _write_wav(path, samples)
        _emit(
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
    _emit({"id": request_id, "status": "completed"})
    return True


def main() -> int:
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
    while True:
        request = commands.get()
        if request is None:
            return 0
        command = request.get("command")
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
                if not _speak(pipeline, args.voice_path, request, commands):
                    return 0
        except Exception:
            # Never leak engine internals over the protocol; Core maps this to UNAVAILABLE.
            _emit({"id": request.get("id"), "status": "error", "kind": "engine"})


if __name__ == "__main__":
    raise SystemExit(main())
