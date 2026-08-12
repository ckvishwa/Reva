from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import wave
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _write_wav(path: Path) -> tuple[int, int]:
    sample_rate = 24_000
    duration_ms = 100
    frames = int(sample_rate * duration_ms / 1000)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(frames):
            sample = int(1200 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wav.writeframesraw(struct.pack("<h", sample))
    return sample_rate, duration_ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-wav", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--device", required=True)
    parser.parse_args()

    for line in sys.stdin:
        request = json.loads(line)
        request_id = request["id"]
        if request["command"] == "health":
            _emit({"id": request_id, "status": "ready"})
            continue
        text = request["text"]
        output_path = Path(request["output_path"])
        if text == "worker-error":
            _emit({"id": request_id, "status": "error", "kind": "internal"})
            continue
        if text == "crash-once":
            marker = output_path.parent / "crash-once-marker"
            if not marker.exists():
                marker.write_text("crashed", encoding="utf-8")
                return 7
        if text == "outside":
            outside_path = output_path.parent.parent / "outside.wav"
            sample_rate, duration_ms = _write_wav(outside_path)
            _emit(
                {
                    "id": request_id,
                    "status": "completed",
                    "sample_rate": sample_rate,
                    "duration_ms": duration_ms,
                    "output_path": str(outside_path),
                }
            )
            continue
        sample_rate, duration_ms = _write_wav(output_path)
        _emit(
            {
                "id": request_id,
                "status": "completed",
                "sample_rate": sample_rate,
                "duration_ms": duration_ms,
                "output_path": str(output_path),
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
