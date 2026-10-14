"""Build the endpointing fixture clips with the real Kokoro voice (synthetic, nothing private).

    $env:REVA_KOKORO_PYTHON = "D:\\reva-venvs\\kokoro\\Scripts\\python.exe"
    $env:REVA_ASSET_ROOT    = "F:\\reva-assets"
    python tools/voice/make_endpointing_fixtures.py

Writes 16 kHz mono 16-bit WAVs and `expected.json` into `tests/fixtures/endpointing/`. The clips are
committed, so CI never needs Kokoro. `expected.json` records how each clip was assembled (where each
phrase was placed), which is what the tests compare the endpointer's turns against.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reva_core.config.settings import load_settings  # noqa: E402
from reva_core.providers.tts import RegistryTTS, build_tts_registry  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "endpointing"
RATE = 16_000
SOURCE_RATE = 24_000


async def say(tts: RegistryTTS, text: str) -> np.ndarray:
    provider = await tts.require_interruptible()
    parts: list[np.ndarray] = []
    async for chunk in provider.speak(text, language="en", turn_epoch=1, scope="fixtures"):
        with wave.open(str(chunk.path), "rb") as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        chunk.path.unlink(missing_ok=True)
        parts.append(pcm)
    audio = np.concatenate(parts).astype(np.float64)
    # 24 kHz -> 16 kHz by linear interpolation (Kokoro has almost nothing above 8 kHz).
    positions = np.arange(0, len(audio) - 1, SOURCE_RATE / RATE)
    return trim(np.interp(positions, np.arange(len(audio)), audio).astype(np.int16))


def trim(audio: np.ndarray, floor_dbfs: float = -50.0, frame: int = RATE // 50) -> np.ndarray:
    """Cut the silence Kokoro puts before and after a phrase, so the pauses placed between phrases
    are the pauses the clip really has."""
    count = len(audio) // frame
    levels = [
        20
        * np.log10(
            max(
                float(np.sqrt(np.mean(audio[i * frame : (i + 1) * frame].astype(np.float64) ** 2))),
                1.0,
            )
            / 32768
        )
        for i in range(count)
    ]
    voiced = [i for i, level in enumerate(levels) if level >= floor_dbfs]
    if not voiced:
        return audio
    return audio[voiced[0] * frame : (voiced[-1] + 1) * frame]


def silence(ms: int) -> np.ndarray:
    return np.zeros(RATE * ms // 1000, dtype=np.int16)


def hiss(ms: int, dbfs: float = -60.0) -> np.ndarray:
    rng = np.random.default_rng(7)
    peak = 32768 * 10 ** (dbfs / 20)
    return rng.uniform(-peak, peak, RATE * ms // 1000).astype(np.int16)


def write(name: str, pieces: list[tuple[str, np.ndarray]]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    layout, cursor, parts = [], 0, []
    for label, audio in pieces:
        ms = round(len(audio) / RATE * 1000)
        layout.append({"label": label, "start_ms": cursor, "end_ms": cursor + ms})
        parts.append(audio)
        cursor += ms
    clip = np.concatenate(parts)
    with wave.open(str(OUT / name), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(clip.tobytes())
    return {"duration_ms": cursor, "layout": layout}


async def main() -> None:
    python = os.environ.get("REVA_KOKORO_PYTHON")
    root = os.environ.get("REVA_ASSET_ROOT")
    if not python or not root:
        raise SystemExit("set REVA_KOKORO_PYTHON and REVA_ASSET_ROOT")
    with tempfile.TemporaryDirectory(prefix="endpointing-fixtures-") as scratch:
        settings = load_settings(
            _env_file=None,
            data_dir=Path(scratch),
            kokoro_python=Path(python),
            asset_root=Path(root),
            tts_provider="kokoro",
            tts_ready_timeout_seconds=120.0,
        )
        tts = RegistryTTS(
            build_tts_registry(settings, Path(scratch) / "speech"), preferred="kokoro"
        )
        try:
            add = await say(tts, "Add twelve dollars for lunch.")
            actually = await say(tts, "Actually, make it fifteen.")
            budget = await say(tts, "What is my budget left?")
            first_half = await say(tts, "Add twelve dollars")
            second_half = await say(tts, "for lunch.")
        finally:
            await tts.shutdown()

    expected: dict[str, Any] = {
        "two_turns.wav": write(
            "two_turns.wav",
            [
                ("silence", silence(500)),
                ("add", add),
                ("pause", silence(800)),
                ("actually", actually),
                ("silence", silence(1000)),
            ],
        ),
        "short_pause_inside.wav": write(
            "short_pause_inside.wav",
            [
                ("silence", silence(400)),
                ("first_half", first_half),
                ("pause", silence(150)),
                ("second_half", second_half),
                ("silence", silence(1000)),
            ],
        ),
        "single_with_margins.wav": write(
            "single_with_margins.wav",
            [("silence", silence(600)), ("budget", budget), ("silence", silence(1200))],
        ),
        "quiet_room.wav": write("quiet_room.wav", [("hiss_-60dBFS", hiss(2000))]),
    }
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    for name, info in expected.items():
        print(name, info["duration_ms"], "ms")


if __name__ == "__main__":
    asyncio.run(main())
