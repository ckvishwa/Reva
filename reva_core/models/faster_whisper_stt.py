from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

from reva_core.models.stt import (
    SUPPORTED_STT_LANGUAGES,
    TranscriptionInput,
    TranscriptionResult,
)
from reva_core.shared.errors import ProviderError, ProviderErrorKind, ValidationError


class FasterWhisperSTTProvider:
    def __init__(
        self,
        *,
        model: str,
        device: str,
        compute_type: str,
        timeout_seconds: float,
    ) -> None:
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._timeout_seconds = timeout_seconds
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    async def transcribe(self, audio: TranscriptionInput) -> TranscriptionResult:
        if audio.media_type != "audio/wav":
            raise ValidationError("unsupported audio media type")
        if not audio.path.exists():
            raise ValidationError("audio input does not exist")
        try:
            return await asyncio.wait_for(self._transcribe(audio.path), self._timeout_seconds)
        except TimeoutError as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "STT transcription timed out") from exc

    async def _transcribe(self, path: Path) -> TranscriptionResult:
        model = await self._get_model()
        return await asyncio.to_thread(self._transcribe_sync, model, path)

    async def _get_model(self) -> Any:
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_model)
            return self._model

    def _load_model(self) -> Any:
        try:
            module = importlib.import_module("faster_whisper")
            whisper_model = module.WhisperModel
            return whisper_model(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
                local_files_only=True,
            )
        except ImportError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "faster-whisper is unavailable"
            ) from exc
        except Exception as exc:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "STT model is unavailable") from exc

    def _transcribe_sync(self, model: Any, path: Path) -> TranscriptionResult:
        try:
            segments, info = model.transcribe(
                str(path),
                beam_size=5,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            language = str(getattr(info, "language", "") or "en")
            duration_seconds = float(getattr(info, "duration", 0.0) or 0.0)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "STT transcription failed") from exc

        if not text:
            raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "STT produced no transcript")
        if language not in SUPPORTED_STT_LANGUAGES:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "STT detected unsupported language"
            )
        duration_ms = max(1, int(duration_seconds * 1000))
        return TranscriptionResult(
            text=text,
            language=language,  # type: ignore[arg-type]
            duration_ms=duration_ms,
            provider="faster-whisper",
        )
