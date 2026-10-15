"""Speech-to-text benchmark on the owner's own microphone (MASTER-LOOP B1.4).

Step 1, record (needs the desk mic; `pip install sounddevice` in any Python):
    python tools/voice/stt_benchmark.py record --out D:\\reva-bench\\wavs

    It shows each of the 50 sentences in docs/voice/stt-benchmark-script.txt, you press Enter,
    read it aloud, press Enter again. Files are 16 kHz mono WAV named 01.wav ... 50.wav. Any other
    recorder works too if it writes files with those names.

Step 2, score (Core's Python, faster-whisper installed):
    python tools/voice/stt_benchmark.py score --wavs D:\\reva-bench\\wavs \\
        --models tiny base small [--download] [--out docs/voice/stt-benchmark.json]

    Reports word error rate (WER, after lower-casing and spelling out numbers the same way on both
    sides) and latency per clip with the model already loaded, per model. `--download` lets
    faster-whisper fetch a model that is not cached yet; without it a missing model is skipped.

Nothing here touches Core or its data directory.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs" / "voice" / "stt-benchmark-script.txt"
SAMPLE_RATE = 16_000

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def spell_number(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, rest = divmod(n, 10)
        return _TENS[tens] + (f" {_ONES[rest]}" if rest else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {spell_number(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return f"{spell_number(thousands)} thousand" + (f" {spell_number(rest)}" if rest else "")


def normalise(text: str) -> list[str]:
    """Lower case, digits spelled out, punctuation gone: so '$12' and 'twelve dollars' agree."""
    text = text.lower().replace("%", " percent ")
    text = re.sub(r"\$\s*(\d[\d,]*(?:\.\d+)?)", r"\1 dollars", text)
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    text = re.sub(r"(\d+)\.(\d+)", lambda m: f"{m.group(1)} point {m.group(2)}", text)
    text = re.sub(
        r"\d+",
        lambda m: spell_number(int(m.group(0))) if int(m.group(0)) < 10**6 else m.group(0),
        text,
    )
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return text.split()


def word_errors(reference: list[str], hypothesis: list[str]) -> int:
    """Word-level edit distance."""
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        current = [i]
        for j, hyp in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1]


def wer(pairs: list[tuple[str, str]]) -> float:
    errors = words = 0
    for reference, hypothesis in pairs:
        ref = normalise(reference)
        errors += word_errors(ref, normalise(hypothesis))
        words += len(ref)
    return errors / words if words else 0.0


def load_script() -> list[str]:
    lines = [line.strip() for line in SCRIPT.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


@dataclass
class ModelResult:
    model: str
    clips: int
    wer: float
    latency_p50_s: float
    latency_p95_s: float
    real_time_factor: float
    skipped: str | None = None


def record(out: Path) -> int:
    try:
        import sounddevice
    except ImportError:
        print("pip install sounddevice first (any Python), then run this again.")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    sentences = load_script()
    for index, sentence in enumerate(sentences, 1):
        path = out / f"{index:02d}.wav"
        if path.exists():
            continue
        input(f"\n[{index}/{len(sentences)}] {sentence}\n  Enter to start, read it, Enter to stop ")
        frames: list[bytes] = []

        def callback(indata, _frames, _time, _status, sink=frames):  # type: ignore[no-untyped-def]
            sink.append(bytes(indata))

        with sounddevice.RawInputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=callback
        ):
            input()
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(b"".join(frames))
    print(f"\nrecorded {len(sentences)} clips in {out}")
    return 0


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def score(
    wavs: Path, models: list[str], download: bool, vocabulary: str | None
) -> list[ModelResult]:
    from faster_whisper import WhisperModel

    sentences = load_script()
    clips = [(wavs / f"{i:02d}.wav", sentence) for i, sentence in enumerate(sentences, 1)]
    present = [(path, text) for path, text in clips if path.is_file()]
    results: list[ModelResult] = []
    for name in models:
        model_id = name if "/" in name else f"Systran/faster-whisper-{name}"
        try:
            model = WhisperModel(
                model_id, device="cpu", compute_type="int8", local_files_only=not download
            )
        except Exception as exc:
            results.append(ModelResult(name, 0, 0, 0, 0, 0, skipped=type(exc).__name__))
            continue
        model.transcribe(str(present[0][0]), beam_size=5)  # warm-up, not scored
        pairs: list[tuple[str, str]] = []
        latencies: list[float] = []
        audio_seconds = 0.0
        for path, reference in present:
            started = time.perf_counter()
            segments, _ = model.transcribe(
                str(path), beam_size=5, vad_filter=False, initial_prompt=vocabulary
            )
            text = " ".join(segment.text.strip() for segment in segments)
            latencies.append(time.perf_counter() - started)
            audio_seconds += _duration(path)
            pairs.append((reference, text))
        latencies.sort()
        results.append(
            ModelResult(
                model=name,
                clips=len(present),
                wer=round(wer(pairs), 4),
                latency_p50_s=round(statistics.median(latencies), 3),
                latency_p95_s=round(
                    latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 3
                ),
                real_time_factor=round(sum(latencies) / audio_seconds, 3) if audio_seconds else 0.0,
            )
        )
        print(f"{name}: WER {results[-1].wer:.1%}, p50 {results[-1].latency_p50_s}s", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--out", type=Path, required=True)
    sc = sub.add_parser("score")
    sc.add_argument("--wavs", type=Path, required=True)
    sc.add_argument("--models", nargs="+", default=["tiny", "base", "small"])
    sc.add_argument("--download", action="store_true")
    sc.add_argument("--no-vocabulary", action="store_true")
    sc.add_argument("--out", type=Path, default=ROOT / "docs" / "voice" / "stt-benchmark.json")
    args = parser.parse_args()
    if args.command == "record":
        return record(args.out)
    sys.path.insert(0, str(ROOT))
    from reva_core.voice.vocabulary import build_vocabulary_prompt

    vocabulary = None if args.no_vocabulary else build_vocabulary_prompt()
    results = score(args.wavs, args.models, args.download, vocabulary)
    report = {
        "run_at_utc": datetime.now(UTC).isoformat(),
        "script": str(SCRIPT.relative_to(ROOT)),
        "vocabulary_prompt": vocabulary,
        "results": [r.__dict__ for r in results],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
