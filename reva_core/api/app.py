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

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from reva_core import __version__
from reva_core.api.routes import build_router
from reva_core.api.schemas import ErrorResponse
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.errors import StorageError
from reva_core.shared.logging import get_logger

logger = get_logger("api")


def create_app(lifecycle: CoreLifecycle) -> FastAPI:
    app = FastAPI(title="REVA Core", version=__version__)
    app.include_router(build_router(lifecycle))

    @app.get("/health")
    def health() -> dict[str, Any]:
        return lifecycle.health().model_dump(mode="json")

    @app.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        body = ErrorResponse(error=str(exc.detail), correlation_id=correlation_id)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))

    @app.exception_handler(StorageError)
    async def storage_error_handler(request: Request, exc: StorageError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.error(
            "unhandled storage error", exc_info=exc, extra={"correlation_id": correlation_id}
        )
        body = ErrorResponse(error="internal_error", correlation_id=correlation_id)
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.error("unhandled exception", exc_info=exc, extra={"correlation_id": correlation_id})
        body = ErrorResponse(error="internal_error", correlation_id=correlation_id)
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))

    return app
