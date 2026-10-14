"""Configuration for tests that run the genuine Kokoro package and weights (opt-in).

    $env:REVA_RUN_KOKORO_REAL = "1"
    $env:REVA_KOKORO_PYTHON   = "D:\\reva-venvs\\kokoro\\Scripts\\python.exe"
    $env:REVA_ASSET_ROOT      = "F:\\reva-assets"

The interpreter must have `kokoro` installed (versions pinned in
`tools/voice/kokoro-requirements.txt`); the asset root must hold the three manifest-listed files.
Nothing here downloads anything. Without these variables the real tests are SKIPPED, and a skip
is never reported as a pass.
"""

from __future__ import annotations

import os
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

import pytest

from reva_core.voice.kokoro_provider import KokoroAssetIds, KokoroSpeechProvider

ENABLE_VAR = "REVA_RUN_KOKORO_REAL"
PYTHON_VAR = "REVA_KOKORO_PYTHON"
ASSET_ROOT_VAR = "REVA_ASSET_ROOT"

REAL_IDS = KokoroAssetIds(
    config="models.tts.kokoro-82m.config",
    model="models.tts.kokoro-82m.model",
    voice="models.tts.kokoro-82m.voice.af_heart",
)


@dataclass(frozen=True)
class RealKokoro:
    python: Path
    asset_root: Path
    manifest: Path


def real_kokoro() -> RealKokoro:
    """The real configuration, or `pytest.skip` with the exact reason it is unavailable."""
    if os.environ.get(ENABLE_VAR) != "1":
        pytest.skip(f"real Kokoro tests are opt-in: set {ENABLE_VAR}=1")
    python = os.environ.get(PYTHON_VAR)
    root = os.environ.get(ASSET_ROOT_VAR)
    if not python or not Path(python).is_file():
        pytest.skip(f"{PYTHON_VAR} must name the Kokoro interpreter")
    if not root or not Path(root).is_dir():
        pytest.skip(f"{ASSET_ROOT_VAR} must name the asset root")
    manifest = Path(root) / "assets.manifest.json"
    if not manifest.is_file():
        pytest.skip("no assets.manifest.json under the asset root")
    return RealKokoro(python=Path(python), asset_root=Path(root), manifest=manifest)


def make_provider(
    real: RealKokoro, output_dir: Path, *, manifest: Path | None = None, **overrides: object
) -> KokoroSpeechProvider:
    options: dict[str, object] = {
        "python_exe": real.python,
        "manifest_path": manifest or real.manifest,
        "asset_root": real.asset_root,
        "asset_ids": REAL_IDS,
        "output_dir": output_dir,
        "ready_timeout_seconds": 120.0,
        "chunk_timeout_seconds": 60.0,
    }
    options.update(overrides)
    return KokoroSpeechProvider(**options)  # type: ignore[arg-type]


@dataclass(frozen=True)
class WavStats:
    sample_rate: int
    channels: int
    sample_width: int
    seconds: float
    peak: float
    rms: float


def wav_stats(path: Path) -> WavStats:
    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        samples = array("h")
        samples.frombytes(frames)
        count = max(1, len(samples))
        peak = max((abs(s) for s in samples), default=0) / 32768
        rms = (sum(s * s for s in samples) / count) ** 0.5 / 32768
        return WavStats(
            sample_rate=wav.getframerate(),
            channels=wav.getnchannels(),
            sample_width=wav.getsampwidth(),
            seconds=wav.getnframes() / wav.getframerate(),
            peak=peak,
            rms=rms,
        )
