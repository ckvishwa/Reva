"""The gateway's own ASGI app: seven POST routes and nothing else (ARD-500 section 2, AR-DATA-006).

It shares no router, dependency, token or exception handler with the loopback Core API, and it never
sees the Core bearer token. Every other path, method or content type gets a bare error before any
logic runs. Interactive docs and the OpenAPI document are switched off.

    POST /pair/start     phone -> PC   code + public key + proof of possession
    POST /pair/complete  phone -> PC   signed poll for the approval result
    POST /sync/push      phone -> PC   signed events from the phone
    POST /sync/pull      phone -> PC   next signed events for the phone (+ key directory)
    POST /sync/ack       phone -> PC   cursor the phone has applied
    POST /actions/propose phone -> PC  a request for the PC to act (an allowlisted capability)
    POST /actions/status  phone -> PC  what became of that request, from the Core's own record
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from reva_core.gateway import protocol
from reva_core.gateway.identity import GatewayIdentity
from reva_core.gateway.pairing import PairingError, PairingManager
from reva_core.gateway.service import GatewayError, GatewayService
from reva_core.gateway.store import Grant
from reva_core.gateway.trace import TraceMiddleware

MAX_BODY_BYTES = 9 * 1024 * 1024
MAX_PAIRING_BODY_BYTES = 16 * 1024  # unauthenticated callers get a small buffer


def build_gateway_app(
    service: GatewayService,
    pairing: PairingManager,
    identity: GatewayIdentity,
    trace_sink: Callable[[str], None] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="REVA pairing gateway",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,  # /sync/push/ is not /sync/push: no redirects, no near-misses
    )
    if trace_sink is not None:  # diagnostics only: ids and timings, never headers or bodies
        app.add_middleware(TraceMiddleware, sink=trace_sink)

    def remote_of(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    async def read_json(
        request: Request, limit: int = MAX_BODY_BYTES
    ) -> tuple[bytes, dict[str, Any]]:
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise GatewayError("unsupported_media_type", 415)
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            raise GatewayError("too_large", 413)
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise GatewayError("too_large", 413)
            chunks.append(chunk)
        body = b"".join(chunks)
        try:
            parsed = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise GatewayError("bad_request", 400) from exc
        if not isinstance(parsed, dict):
            raise GatewayError("bad_request", 400)
        return body, parsed

    def plain(status: int, body: dict[str, Any]) -> JSONResponse:
        return JSONResponse(status_code=status, content=body)

    # ------------------------------------------------------------------------ pairing

    @app.post("/pair/start")
    async def pair_start(request: Request) -> Response:
        remote = remote_of(request)
        await run_in_threadpool(service.check_not_rate_limited, remote)
        _, data = await read_json(request, MAX_PAIRING_BODY_BYTES)
        try:
            session_id = await run_in_threadpool(
                lambda: pairing.start(
                    code=_text(data, "code"),
                    name=_text(data, "name"),
                    platform=_text(data, "platform"),
                    public_key=_binary(data, "public_key"),
                    kernel_ids=_mapping(data, "kernel_devices"),
                    proof=_binary(data, "proof"),
                )
            )
        except PairingError as exc:
            service.note_failure(remote)
            raise GatewayError(exc.code, exc.status) from exc
        return plain(200, {"session_id": session_id})

    @app.post("/pair/complete")
    async def pair_complete(request: Request) -> Response:
        remote = remote_of(request)
        await run_in_threadpool(service.check_not_rate_limited, remote)
        _, data = await read_json(request, MAX_PAIRING_BODY_BYTES)
        try:
            status, body = await run_in_threadpool(
                lambda: pairing.complete(
                    session_id=_text(data, "session_id"),
                    nonce=_text(data, "nonce"),
                    proof=_binary(data, "proof"),
                )
            )
        except PairingError as exc:
            if exc.code not in ("denied", "code_expired"):
                service.note_failure(remote)
            raise GatewayError(exc.code, exc.status) from exc
        return plain(status, body)

    # ---------------------------------------------------------------------------- sync

    async def authenticated(
        request: Request, op: Callable[[Grant, dict[str, Any]], dict[str, Any]]
    ) -> Response:
        remote = remote_of(request)
        nonce = request.headers.get(protocol.HEADER_NONCE, "")
        device_id = request.headers.get(protocol.HEADER_DEVICE, "")
        timestamp = request.headers.get(protocol.HEADER_TIMESTAMP, "")
        await run_in_threadpool(
            lambda: service.precheck(
                device_id=device_id, timestamp=timestamp, nonce=nonce, remote=remote
            )
        )
        body, data = await read_json(request)
        result = await run_in_threadpool(
            lambda: service.dispatch(
                lambda grant: op(grant, data),
                device_id=device_id,
                timestamp=timestamp,
                nonce=nonce,
                signature=request.headers.get(protocol.HEADER_SIGNATURE, ""),
                method=request.method,
                path=request.url.path,
                body=body,
                remote=remote,
            )
        )
        payload = json.dumps(result, separators=(",", ":")).encode("utf-8")
        signature = identity.sign(protocol.response_message(nonce, 200, payload))
        return Response(
            content=payload,
            media_type="application/json",
            headers={protocol.HEADER_RESPONSE_SIGNATURE: protocol.b64u(signature)},
        )

    @app.post("/sync/push")
    async def sync_push(request: Request) -> Response:
        return await authenticated(request, service.push)

    @app.post("/sync/pull")
    async def sync_pull(request: Request) -> Response:
        return await authenticated(request, service.pull)

    @app.post("/sync/ack")
    async def sync_ack(request: Request) -> Response:
        return await authenticated(request, service.ack)

    # ----------------------------------------------------------------------- actions (C2)

    @app.post("/actions/propose")
    async def actions_propose(request: Request) -> Response:
        return await authenticated(request, service.act_propose)

    @app.post("/actions/status")
    async def actions_status(request: Request) -> Response:
        return await authenticated(request, service.act_status)

    # ------------------------------------------------------------------------- errors

    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
        request.state.reason = exc.code  # read by the optional trace; the client gets the same code
        return plain(exc.status, {"error": exc.code})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Unknown path or wrong method: no detail, no hint about what does exist.
        return plain(exc.status_code, {"error": "not_found" if exc.status_code == 404 else "error"})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        return plain(500, {"error": "internal_error"})

    return app


def _text(data: dict[str, Any], key: str, limit: int = 512) -> str:
    value = data.get(key)
    if not isinstance(value, str) or len(value) > limit:
        raise GatewayError("bad_request", 422)
    return value


def _binary(data: dict[str, Any], key: str) -> bytes:
    try:
        return protocol.b64u_decode(_text(data, key, limit=4096))
    except ValueError as exc:
        raise GatewayError("bad_request", 422) from exc


def _mapping(data: dict[str, Any], key: str) -> dict[str, str]:
    value = data.get(key)
    if (
        not isinstance(value, dict)
        or len(value) > 8
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
    ):
        raise GatewayError("bad_request", 422)
    return dict(value)
