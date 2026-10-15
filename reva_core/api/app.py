"""FastAPI app.

`/health` and `/version` are unauthenticated (no user data, secrets,
configuration, or operationally sensitive detail crosses them).
Everything under `/v1/*` requires local authentication — see
`reva_core/api/auth.py`.

Two exception handlers keep every error response the same safe shape
regardless of what failed: no stack trace, no database path, no
secret ever reaches a client.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from reva_core import __version__
from reva_core.api.actions import build_actions_router
from reva_core.api.apps import build_apps_router
from reva_core.api.cloud_settings import build_cloud_settings_router
from reva_core.api.privacy import build_privacy_router
from reva_core.api.routes import build_router
from reva_core.api.telemetry import build_telemetry_router
from reva_core.api.voice_sessions import build_voice_session_router
from reva_core.domains.routes import build_domains_router
from reva_core.domains.service import DomainRequestError
from reva_core.gateway.routes import build_devices_router
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.error_codes import code_for
from reva_core.shared.errors import StorageError
from reva_core.shared.logging import get_logger

logger = get_logger("api")


def create_app(lifecycle: CoreLifecycle) -> FastAPI:
    voice_router, voice_sessions = build_voice_session_router(lifecycle)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        warming = _start_voice_warm_up(lifecycle)
        yield
        if warming is not None:
            warming.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await warming
        # Release every open voice session (and its mic/turn state) on shutdown.
        await voice_sessions.close_all()

    app = FastAPI(title="REVA Core", version=__version__, lifespan=lifespan)
    app.include_router(build_router(lifecycle))
    app.include_router(build_domains_router(lifecycle))
    app.include_router(build_devices_router(lifecycle))
    app.include_router(build_cloud_settings_router(lifecycle))
    app.include_router(build_privacy_router(lifecycle))
    app.include_router(build_telemetry_router(lifecycle))
    app.include_router(build_actions_router(lifecycle))
    app.include_router(build_apps_router(lifecycle))
    app.include_router(voice_router)
    app.state.voice_sessions = voice_sessions

    @app.get("/health")
    def health() -> dict[str, Any]:
        return lifecycle.health().model_dump(mode="json")

    @app.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    max_json_bytes = 1024 * 1024
    big_body_paths = ("/v1/voice/transcriptions", "/v1/domains/")

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next: Any) -> Any:
        """One megabyte for JSON. Audio uploads and domain imports have their own, larger limits."""
        length = request.headers.get("content-length", "")
        path = request.url.path
        exempt = path.startswith(big_body_paths[0]) or (
            path.startswith(big_body_paths[1]) and path.endswith("/import")
        )
        if length.isdigit() and int(length) > max_json_bytes and not exempt:
            return error_body(request, "payload_too_large", 413)
        return await call_next(request)

    def error_body(request: Request, error: str, status: int, **extra: Any) -> JSONResponse:
        """The one error shape: `error` (as always), `code` (taxonomy), `correlation_id`."""
        content: dict[str, Any] = {
            "error": error,
            "code": code_for(error, status).value,
            "correlation_id": getattr(request.state, "correlation_id", None),
        }
        content.update({k: v for k, v in extra.items() if v})
        if status >= 500:
            lifecycle.telemetry.record("http.error", code=content["code"])
        return JSONResponse(status_code=status, content=content)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return error_body(request, str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Field names only. FastAPI's default body echoes the offending input, which could be a
        # key or a note; this one never does.
        first = exc.errors()[0] if exc.errors() else {}
        location = [
            str(part)
            for part in first.get("loc", ())
            if part not in ("body", "query") and not isinstance(part, int)
        ]
        field = location[-1] if location else None
        if field == "schema_version":
            return error_body(request, "unsupported_schema_version", 422, field=field)
        return error_body(request, "validation_error", 422, field=field)

    @app.exception_handler(DomainRequestError)
    async def domain_error_handler(request: Request, exc: DomainRequestError) -> JSONResponse:
        # Codes and field names only: never record contents, paths or key material.
        return error_body(request, exc.code, exc.status, detail=exc.detail, field=exc.field)

    @app.exception_handler(StorageError)
    async def storage_error_handler(request: Request, exc: StorageError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.error(
            "unhandled storage error", exc_info=exc, extra={"correlation_id": correlation_id}
        )
        return error_body(request, "internal_error", 500)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.error("unhandled exception", exc_info=exc, extra={"correlation_id": correlation_id})
        return error_body(request, "internal_error", 500)

    return app


def _start_voice_warm_up(lifecycle: CoreLifecycle) -> asyncio.Task[None] | None:
    """Load the voice in the background so the first sentence does not wait for the model.

    Startup never waits for it, a failure is only logged, and it is cancelled on shutdown.
    """
    warm = getattr(lifecycle.text_to_speech_provider, "warm", None)
    if warm is None or not lifecycle.settings.tts_warm_on_start:
        return None

    async def run() -> None:
        try:
            ready = await warm()
            logger.info("voice warm-up finished", extra={"ready": bool(ready)})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("voice warm-up failed")

    return asyncio.get_running_loop().create_task(run())
