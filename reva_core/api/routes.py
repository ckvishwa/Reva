"""Phase 1A `/v1/*` routes.

Handlers stay thin: parse/validate (via `schemas.py`), call
`TypedInteractionService`, translate the result back to a response
contract. No SQL, no domain rules here — that lives in
`orchestration/typed_interaction.py` and `storage/`.

Deliberately does NOT use `from __future__ import annotations`: the
route handlers below are closures over a `require_token` dependency
that is itself a local variable of `build_router()`, not a module
global. With postponed evaluation, FastAPI resolves annotation strings
via `typing.get_type_hints()` against the module's globals only, can't
see that local closure variable, and silently degrades
`Annotated[str, Depends(require_token)]` to an unclassified query
parameter instead of raising — confirmed by reproduction during
Phase 1A development. Keeping annotations eagerly evaluated (this
file's default) sidesteps the bug entirely.
"""

from contextlib import suppress
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from reva_core.api.auth import build_auth_dependency
from reva_core.api.schemas import (
    AuditEventListResponse,
    ExplicitMemoryCreateRequest,
    ExplicitMemoryCreateResponse,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryQueryResponseItem,
    TypedRequest,
    TypedResponse,
    VoiceSpeechRequest,
)
from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.shared.errors import ProviderError, ProviderErrorKind, ValidationError
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.repositories.audit_repository import AuditRepository


def build_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)

    def _service() -> TypedInteractionService:
        return TypedInteractionService(
            lifecycle.connection,
            lifecycle.primary_device_id,
            orchestrator=lifecycle.assistant_orchestrator,
            embedding_provider=lifecycle.embedding_provider,
            embedding_model_id=lifecycle.embedding_model_id,
            ranking_config=lifecycle.ranking_config,
        )

    @router.post("/messages", response_model=TypedResponse)
    async def post_message(
        payload: TypedRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> TypedResponse:
        correlation_id = payload.correlation_id or header_correlation_id
        try:
            result = await _service().handle_typed_message(payload.content, correlation_id)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return TypedResponse(
            correlation_id=correlation_id,
            reply=result.reply,
            memory_created=result.memory_id,
        )

    @router.post(
        "/memories",
        response_model=ExplicitMemoryCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def post_memory(
        payload: ExplicitMemoryCreateRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> ExplicitMemoryCreateResponse:
        correlation_id = payload.correlation_id or header_correlation_id
        try:
            memory = await _service().create_explicit_memory(
                payload.content, payload.category, payload.tags, correlation_id
            )
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return ExplicitMemoryCreateResponse(
            id=memory.id,
            category=memory.category,
            created_at=memory.created_at,
            correlation_id=correlation_id,
        )

    @router.get("/memories", response_model=MemoryQueryResponse)
    async def get_memories(
        header_correlation_id: Annotated[str, Depends(require_token)],
        q: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> MemoryQueryResponse:
        query_request = MemoryQueryRequest(query=q, limit=limit)
        memories = await _service().query_memories(
            query_request.query, query_request.limit, header_correlation_id
        )
        items = tuple(
            MemoryQueryResponseItem(
                id=m.id,
                content=m.content,
                category=m.category,
                source=m.source,
                tags=m.tags,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in memories
        )
        return MemoryQueryResponse(results=items, correlation_id=header_correlation_id)

    @router.get("/audit-events", response_model=AuditEventListResponse)
    async def get_audit_events(
        header_correlation_id: Annotated[str, Depends(require_token)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> AuditEventListResponse:
        events = AuditRepository(lifecycle.connection).list_recent(limit)
        return AuditEventListResponse(events=tuple(events), correlation_id=header_correlation_id)

    @router.post("/voice/speech", response_class=FileResponse)
    async def post_voice_speech(
        payload: VoiceSpeechRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> FileResponse:
        provider = lifecycle.text_to_speech_provider
        _record_voice_speech_audit(
            lifecycle,
            action="voice_speech_requested",
            outcome=AuditOutcome.SUCCESS,
            correlation_id=header_correlation_id,
            metadata={"text_length": len(payload.text), "language": payload.language},
        )
        if provider is None:
            _record_voice_speech_audit(
                lifecycle,
                action="voice_speech_failed",
                outcome=AuditOutcome.FAILURE,
                correlation_id=header_correlation_id,
                metadata={"reason": "unavailable", "language": payload.language},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="voice_unavailable",
            )
        try:
            audio = await provider.synthesize(payload.text, payload.language)
        except ValidationError as exc:
            _record_voice_speech_audit(
                lifecycle,
                action="voice_speech_failed",
                outcome=AuditOutcome.FAILURE,
                correlation_id=header_correlation_id,
                metadata={"reason": "validation", "language": payload.language},
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except ProviderError as exc:
            _record_voice_speech_audit(
                lifecycle,
                action="voice_speech_failed",
                outcome=AuditOutcome.FAILURE,
                correlation_id=header_correlation_id,
                metadata={
                    "provider": "tts",
                    "reason": exc.kind.value,
                    "language": payload.language,
                },
            )
            raise HTTPException(
                status_code=_provider_status(exc.kind),
                detail="voice_unavailable",
            ) from exc

        _record_voice_speech_audit(
            lifecycle,
            action="voice_speech_completed",
            outcome=AuditOutcome.SUCCESS,
            correlation_id=header_correlation_id,
            metadata={
                "provider": audio.provider,
                "language": audio.language,
                "duration_ms": audio.duration_ms,
                "sample_rate": audio.sample_rate,
            },
        )
        return FileResponse(
            audio.path,
            media_type="audio/wav",
            filename="reva-speech.wav",
            background=BackgroundTask(_delete_file, audio.path),
        )

    return router


def _provider_status(kind: ProviderErrorKind) -> int:
    if kind == ProviderErrorKind.TIMEOUT:
        return status.HTTP_504_GATEWAY_TIMEOUT
    if kind == ProviderErrorKind.INVALID_RESPONSE:
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_503_SERVICE_UNAVAILABLE


def _record_voice_speech_audit(
    lifecycle: CoreLifecycle,
    *,
    action: str,
    outcome: AuditOutcome,
    correlation_id: str,
    metadata: dict[str, object],
) -> None:
    AuditRepository(lifecycle.connection).insert(
        AuditEvent(
            id=new_id(),
            category=AuditEventCategory.SYSTEM,
            action=action,
            outcome=outcome,
            correlation_id=correlation_id,
            actor_device_id=lifecycle.primary_device_id,
            metadata=metadata,
            occurred_at=utc_now(),
        )
    )


def _delete_file(path: str | Path) -> None:
    with suppress(OSError):
        Path(path).unlink(missing_ok=True)
