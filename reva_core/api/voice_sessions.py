"""`/v1/voice/sessions` and its WebSocket event stream (ARD-300 §4).

Handlers stay thin: they authenticate, translate control messages into
`VoiceSession` calls, and forward events. All session logic lives in
`reva_core/session/`.

The WebSocket authenticates with the same Bearer token as the HTTP API,
read from the handshake `Authorization` header only. A token in the query
string is never accepted, because URLs end up in logs. A refused handshake
is audited as `authentication_failed`.

Client control messages (JSON text frames): `capture.requested`,
`capture.open`, `capture.denied`, `capture.lost`, `interrupt`, `cancel`,
`ping`, `ptt.down`, `ptt.up`, `ptt.cancel`, `mic.mute`, `mic.unmute`, `playback.finished`
(optionally with the `turn_epoch` of the reply that finished). Anything else, or
an illegal one for the current state, produces a typed `BAD_CONTROL_MESSAGE`
error event and changes nothing.

Microphone audio arrives as binary frames: 16 kHz mono 16-bit little-endian PCM,
at most one second per frame. The reply audio is fetched with
`GET /v1/voice/sessions/{id}/audio/{audio_id}` (same Bearer token) using the
path in the `tts.started` event.

Deliberately does NOT use `from __future__ import annotations`; see the
note at the top of `routes.py` about FastAPI and closure dependencies.
"""

import asyncio
import contextlib
import json
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketDisconnect

from reva_core.api.auth import bearer_token_matches, build_auth_dependency, record_auth_failure
from reva_core.api.correlation import resolve_correlation_id
from reva_core.language.dialogue import FileDialogueStore
from reva_core.language.router import IntentRouter
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.providers.cloud import HybridResponder
from reva_core.session.coordinator import SessionCoordinator, VoiceSession
from reva_core.session.events import SessionErrorCode, SessionEventKind
from reva_core.session.pipeline import TurnPipeline
from reva_core.session.turn_log import TurnRecorder
from reva_core.shared.errors import ValidationError
from reva_core.shared.logging import get_logger

logger = get_logger("api.voice_sessions")

_WS_POLICY_VIOLATION = 1008
# Control messages are tiny JSON objects; anything bigger is refused before it is parsed.
_MAX_CONTROL_CHARS = 4096


class VoiceSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str | None = Field(default=None, min_length=8, max_length=64)


class VoiceSessionResponse(BaseModel):
    schema_version: str = "2.0"
    session_id: str
    state: str
    turn_epoch: int
    turn_id: str
    events_path: str
    deadlines_ms: dict[str, int]


def make_stop_speaking(lifecycle: Any) -> Callable[[str, int], Awaitable[None]]:
    """Hook that silences the active TTS provider when a turn is interrupted."""

    async def stop_speaking(session_id: str, turn_epoch: int) -> None:
        provider = lifecycle.text_to_speech_provider
        stop = getattr(provider, "stop", None)
        if stop is not None:
            await stop(turn_epoch=turn_epoch, scope=session_id)

    return stop_speaking


def build_voice_session_router(
    lifecycle: CoreLifecycle,
) -> tuple[APIRouter, SessionCoordinator]:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)
    dialogue_store = FileDialogueStore(lifecycle.settings.data_dir / "dialogue")
    dialogue_store.migrate_legacy()
    coordinator = SessionCoordinator(
        stop_speaking=make_stop_speaking(lifecycle),
        dialogue_store=dialogue_store,
    )
    pipelines: dict[str, TurnPipeline] = {}
    scratch = lifecycle.settings.data_dir / "tmp" / "voice"
    recorder = TurnRecorder(
        lifecycle.settings.data_dir / "turns", enabled=lifecycle.settings.turn_recording_enabled
    )
    _sweep_scratch(scratch)

    async def local_reply(text: str, correlation_id: str) -> str:
        service = TypedInteractionService(
            lifecycle.connection,
            lifecycle.primary_device_id,
            orchestrator=lifecycle.assistant_orchestrator,
            embedding_provider=lifecycle.embedding_provider,
            embedding_model_id=lifecycle.embedding_model_id,
            ranking_config=lifecycle.ranking_config,
        )
        return (await service.handle_typed_message(text, correlation_id)).reply

    reply_text = HybridResponder(local_reply, lifecycle.cloud_reasoner())

    def attach_pipeline(session: VoiceSession) -> TurnPipeline:
        scratch.mkdir(parents=True, exist_ok=True)
        pipeline = TurnPipeline(
            session,
            stt=lifecycle.speech_to_text_provider,
            tts=lifecycle.text_to_speech_provider,
            respond=reply_text,
            router=IntentRouter(session.dialogue),
            recorder=recorder,
            scratch_dir=scratch,
        )
        pipelines[session.id] = pipeline

        async def release() -> None:
            pipelines.pop(session.id, None)
            await pipeline.close()

        session.add_close_hook(release)
        return pipeline

    @router.post(
        "/voice/sessions",
        response_model=VoiceSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def open_session(
        payload: VoiceSessionRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> VoiceSessionResponse:
        try:
            session = coordinator.open(payload.device_id or lifecycle.primary_device_id)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_sessions"
            ) from exc
        attach_pipeline(session)
        return VoiceSessionResponse(
            session_id=session.id,
            state=session.state.value,
            turn_epoch=session.turn_epoch,
            turn_id=session.turn_id,
            events_path=f"/v1/voice/sessions/{session.id}/events",
            deadlines_ms=coordinator.deadlines.as_millis(),
        )

    @router.delete("/voice/sessions/{session_id}")
    async def close_session(
        session_id: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> Response:
        if not await coordinator.close(session_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/voice/sessions/{session_id}/audio/{audio_id}", response_class=FileResponse)
    async def reply_audio(
        session_id: str,
        audio_id: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> FileResponse:
        pipeline = pipelines.get(session_id)
        path = pipeline.audio.path(audio_id) if pipeline is not None else None
        if path is None or not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="audio_not_found")
        return FileResponse(path, media_type="audio/wav", filename="reva-reply.wav")

    @router.websocket("/voice/sessions/{session_id}/events")
    async def session_events(websocket: WebSocket, session_id: str) -> None:
        if not _authenticated(lifecycle, websocket):
            record_auth_failure(
                lifecycle, resolve_correlation_id(None), path="/v1/voice/sessions/*/events"
            )
            await websocket.close(code=_WS_POLICY_VIOLATION)
            return
        session = coordinator.get(session_id)
        if session is None:
            await websocket.close(code=_WS_POLICY_VIOLATION)
            return

        await websocket.accept()
        subscription = session.subscribe()
        sender = asyncio.create_task(_forward_events(websocket, subscription))
        receiver = asyncio.create_task(
            _read_controls(websocket, session, pipelines.get(session_id))
        )
        try:
            await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            session.unsubscribe(subscription)
            for task in (sender, receiver):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            # A dropped connection must never leave the mic or a turn dangling.
            await session.cancel()
            with contextlib.suppress(RuntimeError):
                await websocket.close()

    return router, coordinator


def _authenticated(lifecycle: CoreLifecycle, websocket: WebSocket) -> bool:
    return bearer_token_matches(websocket.headers.get("authorization"), lifecycle.local_token)


async def _forward_events(websocket: WebSocket, subscription: Any) -> None:
    async for event in subscription:
        await websocket.send_text(event.model_dump_json())


async def _read_controls(
    websocket: WebSocket, session: VoiceSession, pipeline: TurnPipeline | None
) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                if pipeline is not None:
                    await pipeline.on_audio(message["bytes"])
                else:
                    _bad_control(session)
            elif message.get("text") is not None:
                await _handle_control(session, message["text"], pipeline)
    except WebSocketDisconnect:
        return


async def _handle_control(session: VoiceSession, raw: str, pipeline: TurnPipeline | None) -> None:
    handlers: dict[str, Callable[[], Awaitable[None]]] = {
        "capture.requested": session.start,
        "capture.open": session.capture_opened,
        "capture.denied": session.capture_denied,
        "capture.lost": session.capture_lost,
        "interrupt": session.interrupt,
        "cancel": session.cancel,
        "ping": _noop,
    }
    if len(raw) > _MAX_CONTROL_CHARS:
        _bad_control(session)
        return
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        message = None
    kind = message.get("type") if isinstance(message, dict) else None
    if pipeline is not None and isinstance(message, dict):
        epoch = message.get("turn_epoch")
        handlers.update(
            {
                "ptt.down": pipeline.on_ptt_down,
                "ptt.up": pipeline.on_ptt_up,
                "ptt.cancel": pipeline.on_ptt_cancel,
                "mic.mute": _sync(lambda: pipeline.set_muted(True)),
                "mic.unmute": _sync(lambda: pipeline.set_muted(False)),
                "playback.finished": _playback(pipeline, epoch),
            }
        )
    handler = handlers.get(kind) if isinstance(kind, str) else None
    if handler is None:
        _bad_control(session)
        return
    try:
        await handler()
    except ValidationError:
        _bad_control(session)


def _sync(action: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    async def run() -> None:
        action()

    return run


def _playback(pipeline: TurnPipeline, epoch: Any) -> Callable[[], Awaitable[None]]:
    async def run() -> None:
        await pipeline.on_playback_finished(epoch if isinstance(epoch, int) else None)

    return run


def _sweep_scratch(directory: Path) -> None:
    """Remove turn audio left by a crashed run: temporary audio has a bounded life."""
    try:
        for child in directory.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    except OSError:
        return


async def _noop() -> None:
    return None


def _bad_control(session: VoiceSession) -> None:
    session.emit(
        SessionEventKind.ERROR,
        {"code": SessionErrorCode.BAD_CONTROL_MESSAGE.value, "recoverable": True, "stage": None},
    )
