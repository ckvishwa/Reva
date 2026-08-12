"""Chatterbox TTS provider via an isolated stdin/stdout worker.

The heavy Chatterbox/Torch runtime intentionally does not import here.
Core launches a dedicated Python interpreter configured by the operator,
then speaks newline-delimited JSON to `reva_core.voice.chatterbox_worker`.
"""

from __future__ import annotations

import asyncio
import json
import wave
from asyncio.subprocess import PIPE
from pathlib import Path
from typing import Any

from reva_core.models.tts import SUPPORTED_TTS_LANGUAGES, SynthesizedAudio, TextToSpeechProvider
from reva_core.shared.errors import ProviderError, ProviderErrorKind, ValidationError
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger

logger = get_logger("models.chatterbox_tts")

_MAX_TEXT_CHARS = 800
_EXPECTED_SAMPLE_RATE = 24_000
_PROVIDER_NAME = "chatterbox_multilingual_worker"


class ChatterboxWorkerTTSProvider(TextToSpeechProvider):
    """Serial, lazy-starting adapter around the local Chatterbox worker."""

    def __init__(
        self,
        *,
        python_exe: Path,
        reference_wav: Path,
        model_id: str,
        device: str,
        output_dir: Path,
        default_language: str = "en",
        ready_timeout_seconds: float = 60.0,
        synthesis_timeout_seconds: float = 120.0,
        worker_module: str = "reva_core.voice.chatterbox_worker",
    ) -> None:
        self._python_exe = python_exe
        self._reference_wav = reference_wav
        self._model_id = model_id
        self._device = device
        self._output_dir = output_dir
        self._default_language = default_language
        self._ready_timeout_seconds = ready_timeout_seconds
        self._synthesis_timeout_seconds = synthesis_timeout_seconds
        self._worker_module = worker_module
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio:
        clean_text = _validate_text(text)
        resolved_language = _validate_language(language or self._default_language)
        async with self._lock:
            try:
                return await self._synthesize_once(clean_text, resolved_language)
            except ProviderError as exc:
                if exc.kind != ProviderErrorKind.UNAVAILABLE:
                    raise
                logger.warning("tts worker unavailable; restarting once")
                await self.shutdown()
                return await self._synthesize_once(clean_text, resolved_language)

    async def shutdown(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _synthesize_once(self, text: str, language: str) -> SynthesizedAudio:
        process = await self._ensure_worker_ready()
        output_path = self._new_output_path()
        request: dict[str, object] = {
            "id": new_id(),
            "command": "synthesize",
            "text": text,
            "language": language,
            "output_path": str(output_path),
        }
        response = await self._round_trip(
            process, request, timeout_seconds=self._synthesis_timeout_seconds
        )
        if response.get("status") != "completed":
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker synthesis failed")
        returned_path = _path_from_response(response)
        validated_path = _validate_under_directory(returned_path, self._output_dir)
        sample_rate, duration_ms = _validate_wav(validated_path)
        response_sample_rate = int(response.get("sample_rate", sample_rate))
        response_duration_ms = int(response.get("duration_ms", duration_ms))
        if response_sample_rate != sample_rate:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "TTS worker sample rate mismatch"
            )
        if response_duration_ms <= 0:
            raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "TTS worker duration invalid")
        return SynthesizedAudio(
            path=validated_path,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            language=language,
            provider=_PROVIDER_NAME,
        )

    async def _ensure_worker_ready(self) -> asyncio.subprocess.Process:
        if self._process is not None and self._process.returncode is None:
            return self._process
        _validate_configuration(self._python_exe, self._reference_wav)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        args = [
            str(self._python_exe),
            "-m",
            self._worker_module,
            "--reference-wav",
            str(self._reference_wav),
            "--model-id",
            self._model_id,
            "--device",
            self._device,
        ]
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=PIPE,
                stdout=PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "TTS worker failed to start"
            ) from exc

        ready = await self._round_trip(
            self._process,
            {"id": new_id(), "command": "health"},
            timeout_seconds=self._ready_timeout_seconds,
        )
        if ready.get("status") != "ready":
            await self.shutdown()
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker did not become ready")
        return self._process

    async def _round_trip(
        self,
        process: asyncio.subprocess.Process,
        request: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if process.stdin is None or process.stdout is None or process.returncode is not None:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker is not running")
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
            raw_line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout_seconds)
        except TimeoutError as exc:
            await self.shutdown()
            raise ProviderError(ProviderErrorKind.TIMEOUT, "TTS worker timed out") from exc
        except (BrokenPipeError, ConnectionResetError) as exc:
            await self.shutdown()
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker pipe closed") from exc
        if not raw_line:
            await self.shutdown()
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker exited")
        try:
            response = json.loads(raw_line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            await self.shutdown()
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "TTS worker returned non-JSON"
            ) from exc
        if not isinstance(response, dict):
            raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "TTS worker response invalid")
        if response.get("id") != request["id"]:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "TTS worker response id mismatch"
            )
        if response.get("status") == "error":
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker reported failure")
        return response

    def _new_output_path(self) -> Path:
        return self._output_dir / f"tts-{new_id()}.wav"


def _validate_configuration(python_exe: Path, reference_wav: Path) -> None:
    if not python_exe.is_file():
        raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS Python interpreter is unavailable")
    if not reference_wav.is_file():
        raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS reference audio is unavailable")


def _validate_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise ValidationError("TTS text must not be empty")
    if len(stripped) > _MAX_TEXT_CHARS:
        raise ValidationError(f"TTS text must be at most {_MAX_TEXT_CHARS} characters")
    return stripped


def _validate_language(language: str) -> str:
    normalized = language.strip().lower()
    if normalized not in SUPPORTED_TTS_LANGUAGES:
        raise ValidationError("TTS language must be 'en' or 'te'")
    return normalized


def _path_from_response(response: dict[str, Any]) -> Path:
    value = response.get("output_path")
    if not isinstance(value, str) or not value:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "TTS worker did not return output path"
        )
    return Path(value)


def _validate_under_directory(path: Path, directory: Path) -> Path:
    resolved_path = path.resolve()
    resolved_directory = directory.resolve()
    try:
        resolved_path.relative_to(resolved_directory)
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "TTS worker returned path outside output dir"
        ) from exc
    return resolved_path


def _validate_wav(path: Path) -> tuple[int, int]:
    if not path.is_file():
        raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "TTS worker output file missing")
    try:
        with wave.open(str(path), "rb") as wav:
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
    except wave.Error as exc:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "TTS worker output is not WAV"
        ) from exc
    if sample_rate != _EXPECTED_SAMPLE_RATE:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "TTS worker WAV sample rate invalid"
        )
    if frames <= 0:
        raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "TTS worker WAV has no audio")
    return sample_rate, int((frames / sample_rate) * 1000)
