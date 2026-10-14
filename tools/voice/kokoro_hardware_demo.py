"""Speak and interrupt with the integrated REVA Kokoro provider, and write timing artifacts.

    python tools/voice/kokoro_hardware_demo.py speak     [--runs N]
    python tools/voice/kokoro_hardware_demo.py interrupt [--runs N]
    python tools/voice/kokoro_hardware_demo.py all       [--runs N]

Common options: --sink speaker|null (default speaker), --gain 0.0..1.0, --device N, --out DIR.
Configuration comes from the environment, the same values Core's settings use:

    REVA_KOKORO_PYTHON   interpreter that has the `kokoro` package
    REVA_ASSET_ROOT      folder with assets.manifest.json and the manifest-listed Kokoro files

The provider is built exactly as Core builds it (`build_tts_registry` + `RegistryTTS`), so the
manifest check, the worker process and `stop` are the production ones. The speaker sink needs
`sounddevice` in the interpreter that runs this script (`pip install sounddevice`); it timestamps
audio at the device's DAC clock, which is what "first audible sample" and "silence" mean here.
With --sink null nothing is played, and every metric that needs a speaker is recorded as null
(NOT_MEASURED), never estimated.

Writes timings.json, timings.csv and report.html into --out (default: a new folder under the
system temp directory) and prints the PowerShell line that opens the report.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from array import array
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from voice_timing import write_artifacts  # noqa: E402

from reva_core.config.settings import load_settings  # noqa: E402
from reva_core.providers.tts import RegistryTTS, build_tts_registry  # noqa: E402

GREETING = "Hello! I'm Reva. My voice system is online and working."
LONG_TEXT = (
    "This is a longer sentence that keeps speaking while the interruption is requested. "
    "It continues with a second sentence so there is plenty of audio left to cut off. "
    "A third sentence follows, and then a fourth, because the stop must land mid-speech. "
    "Finally a fifth sentence ends the passage."
)
NEXT_TEXT = "The next utterance plays normally."
SAMPLE_RATE = 24_000


def mono() -> float:
    return time.monotonic()


def ms(start: float | None, end: float | None) -> float | None:
    return None if start is None or end is None else (end - start) * 1000.0


# --------------------------------------------------------------------------------------- sinks


class NullSink:
    """Plays nothing. Anything that needs a speaker stays None (NOT_MEASURED)."""

    name = "null"
    measures_audible = False

    def __init__(self) -> None:
        self.overlap_events = 0
        self._last_epoch: int | None = None
        self._queued = False
        self.first_audible_at: float | None = None
        self.first_enqueued_at: float | None = None
        self.first_callback_at: float | None = None
        self.first_dac_offset: float | None = None
        self.silence_at: float | None = None
        self.completed_at: float | None = None
        self.resumed_frames = 0

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    def arm(self) -> None:
        self.first_audible_at = self.silence_at = self.completed_at = None
        self.first_enqueued_at = self.first_callback_at = self.first_dac_offset = None
        self.resumed_frames = 0

    def enqueue(self, pcm: bytes, epoch: int, *, final: bool) -> None:
        if self.first_enqueued_at is None:
            self.first_enqueued_at = mono()
        if self._queued and self._last_epoch not in (None, epoch):
            self.overlap_events += 1
        self._last_epoch, self._queued = epoch, not final

    def flush(self) -> None:
        self._queued = False

    def idle(self) -> bool:
        return True


class SpeakerSink:
    """Plays 24 kHz mono through the default output device and records DAC-clock times."""

    name = "speaker"
    measures_audible = True

    def __init__(self, gain: float, device: int | None) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415 - optional, only the speaker sink needs it
        except ImportError as exc:
            raise SystemExit("the speaker sink needs sounddevice: pip install sounddevice") from exc
        self._sd = sd
        self._gain = gain
        self._device = device
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._final_queued = False
        self._last_epoch: int | None = None
        self._flush_pending = False
        self._after_silence = False
        self._armed = True
        self._stream: Any = None
        self.host_api: str | None = None
        self.overlap_events = 0
        self.first_audible_at: float | None = None
        self.first_enqueued_at: float | None = None
        self.first_callback_at: float | None = None
        self.first_dac_offset: float | None = None
        self.silence_at: float | None = None
        self.completed_at: float | None = None
        self.resumed_frames = 0

    def _host_api(self) -> str:
        sd = self._sd
        index = self._device if self._device is not None else sd.default.device[1]
        return str(sd.query_hostapis(sd.query_devices(index)["hostapi"])["name"])

    def start(self) -> None:
        sd = self._sd
        # WASAPI shared mode runs at the device's mix rate; let PortAudio convert from 24 kHz.
        extra = (
            sd.WasapiSettings(auto_convert=True) if self._host_api() == "Windows WASAPI" else None
        )
        self._stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=self._device,
            latency="low",
            extra_settings=extra,
            callback=self._callback,
        )
        self.host_api = self._host_api()
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def arm(self) -> None:
        with self._lock:
            self._armed = True
            self._after_silence = False
            self._flush_pending = False
            self._final_queued = False
            self.first_audible_at = self.silence_at = self.completed_at = None
            self.first_enqueued_at = self.first_callback_at = self.first_dac_offset = None
            self.resumed_frames = 0

    def enqueue(self, pcm: bytes, epoch: int, *, final: bool) -> None:
        with self._lock:
            if self.first_enqueued_at is None:
                self.first_enqueued_at = mono()
            if self._buffer and self._last_epoch not in (None, epoch):
                self.overlap_events += 1
            self._last_epoch = epoch
            self._buffer.extend(pcm)
            self._final_queued = final

    def flush(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._flush_pending = True

    def idle(self) -> bool:
        with self._lock:
            return not self._buffer

    def _callback(self, outdata: Any, frames: int, time_info: Any, status: Any) -> None:
        now = mono()
        dac_offset = time_info.outputBufferDacTime - time_info.currentTime
        need = frames * 2
        with self._lock:
            data = bytes(self._buffer[:need])
            del self._buffer[:need]
            sounding = any(data)
            if sounding:
                if self._armed:
                    self._armed = False
                    self.first_audible_at = now + dac_offset
                    self.first_callback_at = now
                    self.first_dac_offset = dac_offset
                if self._after_silence:
                    self.resumed_frames += len(data) // 2
                if not self._buffer and self._final_queued and self.completed_at is None:
                    self.completed_at = now + dac_offset + (len(data) // 2) / SAMPLE_RATE
            elif self._flush_pending:
                self._flush_pending = False
                self._after_silence = True
                self.silence_at = now + dac_offset
        block = data.ljust(need, b"\0")
        if self._gain != 1.0:
            samples = array("h")
            samples.frombytes(block)
            block = array("h", (int(s * self._gain) for s in samples)).tobytes()
        outdata[:] = block


# ------------------------------------------------------------------------------------- helpers


def kokoro_worker_pids() -> list[int]:
    script = (
        "Get-CimInstance Win32_Process | Where-Object "
        "{ $_.CommandLine -like '*reva_core.voice.kokoro_worker*' -and $_.ProcessId -ne $PID } | "
        "ForEach-Object { $_.ProcessId }"
    )
    done = subprocess.run(  # noqa: S603, S607 - fixed query, no user input
        [shutil.which("powershell") or "powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return [int(line) for line in done.stdout.split() if line.strip().isdigit()]


def read_pcm(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as wav:
        return wav.readframes(wav.getnframes()), wav.getnframes() / wav.getframerate()


def build_tts(data_dir: Path) -> RegistryTTS:
    python = os.environ.get("REVA_KOKORO_PYTHON")
    root = os.environ.get("REVA_ASSET_ROOT")
    if not python or not root:
        raise SystemExit("set REVA_KOKORO_PYTHON and REVA_ASSET_ROOT (see the module docstring)")
    settings = load_settings(
        _env_file=None,
        data_dir=data_dir,
        kokoro_python=Path(python),
        asset_root=Path(root),
        tts_provider="kokoro",
        tts_ready_timeout_seconds=120.0,
    )
    registry = build_tts_registry(settings, data_dir / "speech")
    return RegistryTTS(registry, preferred="kokoro")


async def utter(
    tts: RegistryTTS, sink: NullSink | SpeakerSink, text: str, epoch: int, text_ready: float
) -> dict[str, Any]:
    """Speak `text` through the provider into `sink` and return its timing record."""
    provider = await tts.require_interruptible()
    sink.arm()
    dispatched = mono()
    first_generated: float | None = None
    audio_seconds = 0.0
    chunks = 0
    async for chunk in provider.speak(text, language="en", turn_epoch=epoch):
        if first_generated is None:
            first_generated = mono()
        pcm, seconds = read_pcm(chunk.path)
        chunk.path.unlink(missing_ok=True)
        audio_seconds += seconds
        chunks += 1
        sink.enqueue(pcm, epoch, final=chunk.final)
    synth_done = mono()
    deadline = mono() + audio_seconds + 3.0
    while sink.measures_audible and sink.completed_at is None and mono() < deadline:
        await asyncio.sleep(0.01)
    synthesis_ms = ms(dispatched, synth_done)
    return {
        "text_ready_to_dispatch_ms": ms(text_ready, dispatched),
        "first_audio_generated_ms": ms(text_ready, first_generated),
        "first_audible_after_text_ms": ms(text_ready, sink.first_audible_at),
        "generated_to_enqueued_ms": ms(first_generated, sink.first_enqueued_at),
        "enqueued_to_callback_ms": ms(sink.first_enqueued_at, sink.first_callback_at),
        "device_latency_ms": (
            None if sink.first_dac_offset is None else sink.first_dac_offset * 1000.0
        ),
        "synthesis_ms": synthesis_ms,
        "audio_seconds": audio_seconds,
        "real_time_factor": (synthesis_ms / 1000.0) / audio_seconds if audio_seconds else None,
        "natural_completion_after_text_ms": ms(text_ready, sink.completed_at),
        "chunks": chunks,
        "overlap_events": sink.overlap_events,
    }


# ------------------------------------------------------------------------------------ commands


async def run_speak(
    tts: RegistryTTS, sink: NullSink | SpeakerSink, runs: int
) -> list[dict[str, Any]]:
    print("loading the model (not timed) ...", flush=True)
    provider = await tts.require_interruptible()
    await provider.health()
    results = []
    for index in range(1, runs + 1):
        text_ready = mono()
        record = await utter(tts, sink, GREETING, epoch=index, text_ready=text_ready)
        record["orphan_processes"] = None
        results.append(record)
        print(
            f"speak {index}/{runs}: first audio generated "
            f"{_show(record['first_audio_generated_ms'])} ms, first audible "
            f"{_show(record['first_audible_after_text_ms'])} ms, RTF "
            f"{_show(record['real_time_factor'], 2)}",
            flush=True,
        )
        await asyncio.sleep(0.5)
    return results


async def run_interrupt(
    tts: RegistryTTS, sink: NullSink | SpeakerSink, runs: int
) -> list[dict[str, Any]]:
    provider = await tts.require_interruptible()
    await provider.health()
    results = []
    epoch = 1000
    for index in range(1, runs + 1):
        epoch += 2
        sink.arm()
        delivered_after_stop: list[float] = []
        stop_called: list[float] = []

        async def long_utterance(
            current: int = epoch,
            stopped: list[float] = stop_called,
            late: list[float] = delivered_after_stop,
        ) -> None:
            async for chunk in provider.speak(LONG_TEXT, language="en", turn_epoch=current):
                pcm, _ = read_pcm(chunk.path)
                chunk.path.unlink(missing_ok=True)
                if stopped:
                    late.append(mono())
                    continue
                sink.enqueue(pcm, current, final=chunk.final)

        task = asyncio.create_task(long_utterance())
        deadline = mono() + 15
        while sink.first_audible_at is None and sink.measures_audible and mono() < deadline:
            await asyncio.sleep(0.005)
        if not sink.measures_audible:
            await asyncio.sleep(1.2)  # no speaker to wait on: let synthesis get under way
        await asyncio.sleep(0.4)  # speech is now audible and still has audio queued

        called = mono()
        stop_called.append(called)
        sink.flush()  # the player goes quiet locally ...
        await tts.stop(turn_epoch=epoch + 1)  # ... and the production Stop reaches the provider
        returned = mono()
        await asyncio.wait_for(task, timeout=15)
        await asyncio.sleep(1.5)  # old audio must not resume

        record_stop = {
            "stop_return_ms": ms(called, returned),
            "stop_to_silence_ms": ms(called, sink.silence_at),
            "chunks_after_stop": len(delivered_after_stop),
            "resumed_frames_after_silence": sink.resumed_frames if sink.measures_audible else None,
        }
        started = mono()
        follow = await utter(tts, sink, NEXT_TEXT, epoch=epoch + 1, text_ready=started)
        workers = len(kokoro_worker_pids())
        results.append(
            {
                **record_stop,
                "next_first_audible_ms": follow["first_audible_after_text_ms"],
                "next_first_audio_generated_ms": follow["first_audio_generated_ms"],
                "overlap_events": sink.overlap_events,
                "worker_processes_during_run": workers,
                "orphan_processes": None,
            }
        )
        print(
            f"interrupt {index}/{runs}: stop returned {_show(record_stop['stop_return_ms'])} ms, "
            f"silence {_show(record_stop['stop_to_silence_ms'])} ms, chunks after stop "
            f"{record_stop['chunks_after_stop']}, next audible "
            f"{_show(follow['first_audible_after_text_ms'])} ms",
            flush=True,
        )
    return results


def _show(value: float | None, digits: int = 0) -> str:
    return "NOT_MEASURED" if value is None else f"{value:.{digits}f}"


async def main_async(args: argparse.Namespace) -> int:
    out = (
        Path(args.out)
        if args.out
        else Path(tempfile.gettempdir())
        / "reva-voice-timing"
        / (dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ"))
    )
    sink: NullSink | SpeakerSink = (
        NullSink() if args.sink == "null" else SpeakerSink(args.gain, args.device)
    )
    speak_runs: list[dict[str, Any]] = []
    interrupt_runs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="reva-voice-demo-") as scratch:
        tts = build_tts(Path(scratch))
        sink.start()
        try:
            if args.command in ("speak", "all"):
                speak_runs = await run_speak(tts, sink, args.runs)
            if args.command in ("interrupt", "all"):
                interrupt_runs = await run_interrupt(tts, sink, args.runs)
        finally:
            sink.close()
            await tts.shutdown()
        await asyncio.sleep(1.0)
        orphans = len(kokoro_worker_pids())
    for run in (*speak_runs, *interrupt_runs):
        run["orphan_processes"] = orphans
    meta = {
        "date_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "command": args.command,
        "runs": args.runs,
        "sink": sink.name,
        "gain": args.gain if sink.name == "speaker" else None,
        "audio_api": getattr(sink, "host_api", None),
        "device": args.device,
        "host": platform.platform(),
        "python": sys.version.split()[0],
        "provider": "kokoro af_heart (Kokoro-82M v1.0) via build_tts_registry/RegistryTTS",
        "orphan_check": "Kokoro worker processes alive after shutdown",
    }
    paths = write_artifacts(out, meta, speak_runs, interrupt_runs)
    print(f"\norphan Kokoro processes after shutdown: {orphans}")
    print(f"timing artifacts: {out}")
    print(f'open the report:  Start-Process "{paths["html"]}"')
    return 0 if orphans == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["speak", "interrupt", "all"])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--sink", choices=["speaker", "null"], default="speaker")
    parser.add_argument("--gain", type=float, default=1.0)
    parser.add_argument("--device", type=int, default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if not 0.0 <= args.gain <= 1.0:
        raise SystemExit("--gain must be between 0.0 and 1.0")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
