"""Wake-word evaluation (MASTER-LOOP B1.6): false accepts per hour and miss rate.

Two engines are compared on the same audio: Porcupine (hash-listed `.ppn`, AccessKey from the
environment variable `PICOVOICE_ACCESS_KEY` or Windows Credential Manager) and openWakeWord with a
custom "Hey Reva" model. Neither engine is installed or enabled by this script, and the wake word
stays default OFF in REVA: this only measures.

Audio you provide (16 kHz mono 16-bit WAV, any file names):
    --negatives DIR   about 1 hour of speech and room noise that does NOT contain "Hey Reva"
    --positives DIR   50 short clips of you saying "Hey Reva" (varied distance, speed, background)

    python tools/voice/wake_eval.py --engine porcupine --ppn F:\\reva-assets\\wake\\hey-reva.ppn \\
        --negatives D:\\reva-bench\\negatives --positives D:\\reva-bench\\positives
    python tools/voice/wake_eval.py --engine openwakeword \\
        --model F:\\reva-assets\\wake\\hey_reva.onnx --negatives ... --positives ...

The scoring itself (`score`) is pure and tested; the engine adapters are thin and need the engine
installed and, for Porcupine, the AccessKey.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import wave
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class WakeScore:
    engine: str
    negative_hours: float
    false_accepts: int
    false_accepts_per_hour: float
    positives: int
    detected: int
    miss_rate: float


def score(
    engine: str, negative_seconds: float, false_accepts: int, positives: int, detected: int
) -> WakeScore:
    hours = negative_seconds / 3600
    return WakeScore(
        engine=engine,
        negative_hours=round(hours, 3),
        false_accepts=false_accepts,
        false_accepts_per_hour=round(false_accepts / hours, 3) if hours else 0.0,
        positives=positives,
        detected=detected,
        miss_rate=round(1 - detected / positives, 3) if positives else 0.0,
    )


def read_pcm(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as handle:
        if (
            handle.getframerate() != SAMPLE_RATE
            or handle.getnchannels() != 1
            or handle.getsampwidth() != 2
        ):
            raise ValueError(f"{path.name}: needs 16 kHz mono 16-bit PCM")
        raw = handle.readframes(handle.getnframes())
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


def frames(samples: list[int], size: int) -> Iterator[list[int]]:
    for offset in range(0, len(samples) - size + 1, size):
        yield samples[offset : offset + size]


Detector = Callable[[list[int]], bool]


def _porcupine(ppn: Path) -> tuple[Detector, int, Callable[[], None]]:
    import pvporcupine  # type: ignore[import-not-found]

    key = os.environ.get("PICOVOICE_ACCESS_KEY")
    if not key:
        raise SystemExit("Set PICOVOICE_ACCESS_KEY for this run (not stored by this script).")
    engine = pvporcupine.create(access_key=key, keyword_paths=[str(ppn)])
    return (lambda frame: engine.process(frame) >= 0), engine.frame_length, engine.delete


def _openwakeword(model: Path) -> tuple[Detector, int, Callable[[], None]]:
    import numpy as np  # type: ignore[import-not-found]
    from openwakeword.model import Model  # type: ignore[import-not-found]

    engine = Model(wakeword_models=[str(model)])

    def detect(frame: list[int]) -> bool:
        scores = engine.predict(np.array(frame, dtype=np.int16))
        return any(value >= 0.5 for value in scores.values())

    return detect, 1280, engine.reset


def run(detect: Detector, frame_size: int, files: list[Path]) -> tuple[float, int, list[bool]]:
    """Seconds of audio, total detections, and per-file 'detected at least once'."""
    seconds = 0.0
    detections = 0
    per_file: list[bool] = []
    for path in files:
        samples = read_pcm(path)
        seconds += len(samples) / SAMPLE_RATE
        hit = 0
        for frame in frames(samples, frame_size):
            if detect(frame):
                hit += 1
        detections += hit
        per_file.append(hit > 0)
    return seconds, detections, per_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["porcupine", "openwakeword"], required=True)
    parser.add_argument("--ppn", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--negatives", type=Path, required=True)
    parser.add_argument("--positives", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.engine == "porcupine":
        if args.ppn is None:
            parser.error("--ppn is required for porcupine")
        detect, size, close = _porcupine(args.ppn)
    else:
        if args.model is None:
            parser.error("--model is required for openwakeword")
        detect, size, close = _openwakeword(args.model)
    try:
        negatives = sorted(args.negatives.glob("*.wav"))
        positives = sorted(args.positives.glob("*.wav"))
        seconds, false_accepts, _ = run(detect, size, negatives)
        _, _, per_file = run(detect, size, positives)
    finally:
        close()
    result = score(args.engine, seconds, false_accepts, len(positives), sum(per_file))
    print(json.dumps(asdict(result), indent=2))
    if args.out:
        args.out.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
