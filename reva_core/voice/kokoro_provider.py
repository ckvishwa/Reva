"""Kokoro-82M `af_heart` provider: speak / stop / health (AR-VA-008).

Synthesis runs in a supervised worker process (`reva_core.voice.kokoro_worker`).
Three guarantees this module owns:

* **Manifest-bound load** (AR-VA-020). The worker is only launched after the
  config, model and voice files match `assets.manifest.json`. A mismatch
  raises `AssetVerificationError`; the registry then falls back.
* **Epoch-gated audio** (AR-VA-004). Chunks carry the `turn_epoch` they were
  requested under. Epochs are kept per *scope* (a voice session's id), because each session
  numbers its own turns from 0; calls without a scope share the scope "". After
  `stop(turn_epoch=n, scope=s)` returns, nothing older than `n` in scope `s`
  is delivered, and the worker has either acknowledged the stop or been killed,
  so a new request never overlaps the old one.
* **No orphans.** Workers are covered by a kill-on-close job object and are
  terminated on `shutdown()`.

A background pump reads the worker. That is what lets `stop()` complete even
when the consumer is suspended between chunks.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reva_core.models.tts import ProviderHealth, SpeechChunk, SynthesizedAudio
from reva_core.providers.asset_manifest import verify_assets
from reva_core.shared.errors import ProviderError, ProviderErrorKind, ValidationError
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger
from reva_core.voice.supervised_worker import ProcessJob, SupervisedWorker, worker_environment
from reva_core.voice.wav import join_wavs, validate_under_directory, validate_wav

logger = get_logger("voice.kokoro")

PROVIDER_NAME = "kokoro_af_heart"
_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
SAMPLE_RATE = 24_000
_MAX_TEXT_CHARS = 800
_TERMINAL = frozenset({"completed", "stopped", "error", "worker_exit"})


@dataclass(frozen=True)
class KokoroAssetIds:
    """Manifest ids for the three files Kokoro needs."""

    config: str
    model: str
    voice: str

    def all(self) -> tuple[str, str, str]:
        return (self.config, self.model, self.voice)


@dataclass
class _Stream:
    epoch: int
    request_id: str
    worker: SupervisedWorker
    scope: str = ""
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    cancelled: bool = False
    worker_done: asyncio.Event = field(default_factory=asyncio.Event)


class KokoroSpeechProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        python_exe: Path,
        manifest_path: Path,
        asset_root: Path,
        asset_ids: KokoroAssetIds,
        output_dir: Path,
        voice: str = "af_heart",
        device: str = "cpu",
        worker_module: str = "reva_core.voice.kokoro_worker",
        ready_timeout_seconds: float = 60.0,
        chunk_timeout_seconds: float = 30.0,
        stop_ack_timeout_seconds: float = 0.2,
    ) -> None:
        self._python_exe = python_exe
        self._manifest_path = manifest_path
        self._asset_root = asset_root
        self._asset_ids = asset_ids
        self._output_dir = output_dir
        self._voice = voice
        self._device = device
        self._worker_module = worker_module
        self._ready_timeout = ready_timeout_seconds
        self._chunk_timeout = chunk_timeout_seconds
        self._stop_ack_timeout = stop_ack_timeout_seconds

        self._job: ProcessJob | None = None
        self._worker: SupervisedWorker | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._active: _Stream | None = None
        self._epochs: dict[str, int] = {}
        self._ready_lock = asyncio.Lock()
        self._begin_lock = asyncio.Lock()
        self._legacy_lock = asyncio.Lock()

    # ------------------------------------------------------------------ health

    @property
    def worker_pid(self) -> int | None:
        worker = self._worker
        return worker.pid if worker is not None and worker.running else None

    async def health(self) -> ProviderHealth:
        worker = await self._ensure_ready()
        return ProviderHealth(ok=True, detail="ready", voice=self._voice, pid=worker.pid)

    # ------------------------------------------------------------------- speak

    async def speak(
        self,
        text: str,
        *,
        language: str,
        turn_epoch: int,
        scope: str = "",
        speed: float | None = None,
    ) -> AsyncIterator[SpeechChunk]:
        clean = _validate_text(text)
        lang = _validate_language(language)
        stream = await self._begin(clean, lang, turn_epoch, scope, clamp_speed(speed))
        if stream is None:
            return
        index_seen = False
        try:
            while True:
                if stream.cancelled or stream.epoch != self._epoch_of(stream.scope):
                    return
                message = await self._next(stream)
                status = message.get("status")
                if status == "chunk":
                    if stream.cancelled or stream.epoch != self._epoch_of(stream.scope):
                        _delete_quietly(message.get("output_path"))
                        return
                    chunk = self._to_chunk(message, stream.epoch, lang)
                    index_seen = True
                    yield chunk
                elif status in {"completed", "stopped"}:
                    return
                elif status == "worker_exit":
                    if stream.cancelled:
                        return
                    raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker exited")
                else:
                    raise ProviderError(
                        ProviderErrorKind.UNAVAILABLE, "TTS worker reported failure"
                    )
        finally:
            self._finish(stream, had_audio=index_seen)

    async def stop(self, *, turn_epoch: int, scope: str = "") -> None:
        """Invalidate everything in `scope` older than `turn_epoch` and silence that scope's speech.

        Another scope's speech is not touched: one session cannot interrupt another.
        """
        self._epochs[scope] = max(self._epoch_of(scope), turn_epoch)
        await self._cancel_active(scope)

    async def synthesize(
        self, text: str, language: str, *, speed: float | None = None
    ) -> SynthesizedAudio:
        """Legacy `/v1/voice/speech` shape: join every chunk into one WAV."""
        async with self._legacy_lock:
            paths: list[Path] = []
            saw_final = False
            try:
                async for chunk in self.speak(
                    text, language=language, turn_epoch=self._epoch_of(""), speed=speed
                ):
                    paths.append(chunk.path)
                    saw_final = chunk.final
                if not saw_final:
                    raise ProviderError(ProviderErrorKind.UNAVAILABLE, "speech was interrupted")
                destination = self._output_dir / f"tts-{new_id()}.wav"
                sample_rate, duration_ms = join_wavs(paths, destination)
            finally:
                for path in paths:
                    _delete_quietly(path)
        return SynthesizedAudio(
            path=destination,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            language="en",
            provider=PROVIDER_NAME,
        )

    async def shutdown(self) -> None:
        stream = self._active
        if stream is not None:
            stream.cancelled = True
        worker, self._worker = self._worker, None
        pump, self._pump_task = self._pump_task, None
        if worker is not None:
            await worker.terminate(grace_seconds=1.0)
        if pump is not None:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pump
        if self._job is not None:
            self._job.close()
            self._job = None

    # ---------------------------------------------------------------- internals

    def _epoch_of(self, scope: str) -> int:
        return self._epochs.get(scope, 0)

    async def _begin(
        self, text: str, language: str, turn_epoch: int, scope: str = "", speed: float = 1.0
    ) -> _Stream | None:
        if turn_epoch < self._epoch_of(scope):
            logger.info("stale speak ignored")
            return None
        async with self._begin_lock:
            if turn_epoch < self._epoch_of(scope):
                return None
            if turn_epoch > self._epoch_of(scope):
                self._epochs[scope] = turn_epoch
                # A newer turn cancels this scope's older speech; another scope's is left to finish.
                await self._cancel_active(scope)
            # One audio producer: whatever is still speaking (any scope) finishes first.
            await self._wait_for_previous()
            worker = await self._ensure_ready()
            if turn_epoch != self._epoch_of(scope):
                return None
            stream = _Stream(epoch=turn_epoch, request_id=new_id(), worker=worker, scope=scope)
            self._active = stream
            try:
                await worker.send(
                    {
                        "id": stream.request_id,
                        "command": "speak",
                        "text": text,
                        "language": language,
                        "speed": speed,
                        "output_dir": str(self._output_dir),
                    }
                )
            except ProviderError:
                self._active = None
                self._kill(worker)
                raise
            return stream

    async def _wait_for_previous(self) -> None:
        previous = self._active
        if previous is None or previous.worker_done.is_set():
            return
        try:
            await asyncio.wait_for(previous.worker_done.wait(), timeout=self._chunk_timeout)
        except TimeoutError:
            self._kill(previous.worker)

    async def _cancel_active(self, scope: str) -> None:
        stream = self._active
        if stream is None or stream.worker_done.is_set() or stream.scope != scope:
            return
        stream.cancelled = True
        try:
            await stream.worker.send({"id": stream.request_id, "command": "stop"})
        except ProviderError:
            self._kill(stream.worker)
        try:
            await asyncio.wait_for(stream.worker_done.wait(), timeout=self._stop_ack_timeout)
        except TimeoutError:
            logger.warning("tts worker ignored stop; killing it")
            self._kill(stream.worker)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stream.worker_done.wait(), timeout=2.0)
        self._drain(stream)

    def _finish(self, stream: _Stream, *, had_audio: bool) -> None:
        if not stream.worker_done.is_set() and not stream.cancelled:
            # Consumer walked away mid-stream: silence the worker in the background.
            stream.cancelled = True
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self._cancel_stream(stream))
        self._drain(stream)
        if self._active is stream and stream.worker_done.is_set():
            self._active = None

    async def _cancel_stream(self, stream: _Stream) -> None:
        if self._active is stream:
            await self._cancel_active(stream.scope)

    async def _next(self, stream: _Stream) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(stream.queue.get(), timeout=self._chunk_timeout)
        except TimeoutError as exc:
            self._kill(stream.worker)
            raise ProviderError(ProviderErrorKind.TIMEOUT, "TTS worker timed out") from exc

    def _to_chunk(self, message: dict[str, Any], epoch: int, language: str) -> SpeechChunk:
        raw_path = message.get("output_path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "TTS worker did not return output path"
            )
        path = validate_under_directory(Path(raw_path), self._output_dir)
        sample_rate, duration_ms = validate_wav(path, expected_sample_rate=SAMPLE_RATE)
        index = message.get("index")
        if not isinstance(index, int) or index < 0:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "TTS worker chunk index invalid"
            )
        return SpeechChunk(
            turn_epoch=epoch,
            index=index,
            path=path,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            final=bool(message.get("final")),
            language=language,
            provider=PROVIDER_NAME,
        )

    def _drain(self, stream: _Stream) -> None:
        while True:
            try:
                message = stream.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if message.get("status") == "chunk":
                _delete_quietly(message.get("output_path"))

    def _kill(self, worker: SupervisedWorker) -> None:
        worker.kill()
        if self._worker is worker:
            self._worker = None

    async def _ensure_ready(self) -> SupervisedWorker:
        async with self._ready_lock:
            worker = self._worker
            if worker is not None and worker.running:
                return worker
            # Hashing the model is blocking disk work; keep the loop free. The
            # verified paths are handed straight to the worker (there is a short
            # window between verify and load; the files sit in a user-owned dir).
            paths = await asyncio.to_thread(
                verify_assets, self._manifest_path, self._asset_root, self._asset_ids.all()
            )
            if not self._python_exe.is_file():
                raise ProviderError(
                    ProviderErrorKind.UNAVAILABLE, "TTS Python interpreter is unavailable"
                )
            self._output_dir.mkdir(parents=True, exist_ok=True)
            if self._job is None:
                self._job = ProcessJob()
            worker = await SupervisedWorker.launch(
                [
                    str(self._python_exe),
                    "-m",
                    self._worker_module,
                    "--config-path",
                    str(paths[self._asset_ids.config]),
                    "--model-path",
                    str(paths[self._asset_ids.model]),
                    "--voice-path",
                    str(paths[self._asset_ids.voice]),
                    "--voice",
                    self._voice,
                    "--device",
                    self._device,
                ],
                job=self._job,
                env=worker_environment(os.environ),
                # `-m <worker_module>` resolves from here, whatever Core's own cwd is.
                cwd=_PACKAGE_PARENT,
            )
            try:
                await self._handshake(worker)
            except BaseException:
                worker.kill()
                raise
            self._worker = worker
            self._pump_task = asyncio.get_running_loop().create_task(self._pump(worker))
            return worker

    async def _handshake(self, worker: SupervisedWorker) -> None:
        request_id = new_id()
        await worker.send({"id": request_id, "command": "health"})
        try:
            message = await asyncio.wait_for(worker.read_message(), timeout=self._ready_timeout)
        except TimeoutError as exc:
            raise ProviderError(
                ProviderErrorKind.TIMEOUT, "TTS worker did not become ready"
            ) from exc
        if message is None or message.get("id") != request_id or message.get("status") != "ready":
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker did not become ready")

    async def _pump(self, worker: SupervisedWorker) -> None:
        try:
            while True:
                message = await worker.read_message()
                if message is None:
                    break
                self._route(worker, message)
        except ProviderError:
            logger.warning("tts worker sent an unreadable message; killing it")
            worker.kill()
        finally:
            self._on_worker_exit(worker)

    def _route(self, worker: SupervisedWorker, message: dict[str, Any]) -> None:
        stream = self._active
        status = message.get("status")
        if stream is None or stream.worker is not worker or message.get("id") != stream.request_id:
            if status == "chunk":
                _delete_quietly(message.get("output_path"))
            return
        if status == "chunk" and (stream.cancelled or stream.epoch != self._epoch_of(stream.scope)):
            _delete_quietly(message.get("output_path"))
            return
        stream.queue.put_nowait(message)
        if status in _TERMINAL:
            stream.worker_done.set()

    def _on_worker_exit(self, worker: SupervisedWorker) -> None:
        if self._worker is worker:
            self._worker = None
        stream = self._active
        if stream is not None and stream.worker is worker and not stream.worker_done.is_set():
            stream.queue.put_nowait({"status": "worker_exit"})
            stream.worker_done.set()


MIN_SPEED = 0.8
MAX_SPEED = 1.2


def clamp_speed(speed: float | None) -> float:
    """Speaking rate for the worker: 1.0 when unset, never outside a natural range."""
    if speed is None or speed != speed:  # None or NaN
        return 1.0
    return min(MAX_SPEED, max(MIN_SPEED, float(speed)))


def _validate_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise ValidationError("TTS text must not be empty")
    if len(stripped) > _MAX_TEXT_CHARS:
        raise ValidationError(f"TTS text must be at most {_MAX_TEXT_CHARS} characters")
    return stripped


def _validate_language(language: str) -> str:
    if language.strip().lower() != "en":
        raise ValidationError("Kokoro af_heart speaks English only")
    return "en"


def _delete_quietly(raw_path: object) -> None:
    if isinstance(raw_path, (str, Path)) and raw_path:
        with contextlib.suppress(OSError):
            Path(raw_path).unlink(missing_ok=True)
