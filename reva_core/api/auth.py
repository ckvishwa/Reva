"""Local Core API authentication.

Every `/v1/*` domain endpoint requires `Authorization: Bearer <token>`
where `<token>` matches `CoreLifecycle.local_token` (see
`reva_core/security/local_token.py`). Comparison is constant-time.
`/health` and `/version` remain unauthenticated — they expose no user
data, secrets, configuration, or operationally sensitive detail.

A failed attempt is recorded as an `authentication_failed` audit event
(never containing the token or header value) and returns a generic
401 — the response never reveals whether a token was missing,
malformed, or simply wrong.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from reva_core.api.correlation import resolve_correlation_id
from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger
from reva_core.shared.time import utc_now
from reva_core.storage.repositories.audit_repository import AuditRepository

logger = get_logger("api.auth")

_BEARER_PREFIX = "Bearer "


def bearer_token_matches(authorization: str | None, expected: str) -> bool:
    """True only when `authorization` is `Bearer <expected>`. Fails closed on anything else.

    Shared by the HTTP dependency and the WebSocket handshake. Compares bytes in constant time:
    `hmac.compare_digest` raises TypeError for a str with non-ASCII characters, and a client
    controls the header, so a str comparison would turn a hostile header into a skipped audit
    record or a 500.
    """
    if not authorization or not expected or not authorization.startswith(_BEARER_PREFIX):
        return False
    provided = authorization[len(_BEARER_PREFIX) :].strip()
    if not provided:
        return False
    try:
        return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
    except (UnicodeError, TypeError):
        return False


def build_auth_dependency(lifecycle: CoreLifecycle) -> Callable[..., Awaitable[str]]:
    async def require_local_token(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    ) -> str:
        correlation_id = resolve_correlation_id(x_correlation_id)
        request.state.correlation_id = correlation_id

        if not bearer_token_matches(authorization, lifecycle.local_token):
            _record_auth_failure(lifecycle, correlation_id, path=request.url.path)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

        return correlation_id

    return require_local_token


def record_auth_failure(lifecycle: CoreLifecycle, correlation_id: str, *, path: str) -> None:
    """Public hook for transports that cannot use the HTTP dependency (WebSocket)."""
    _record_auth_failure(lifecycle, correlation_id, path=path)


def _record_auth_failure(lifecycle: CoreLifecycle, correlation_id: str, *, path: str) -> None:
    try:
        AuditRepository(lifecycle.connection).insert(
            AuditEvent(
                id=new_id(),
                category=AuditEventCategory.SYSTEM,
                action="authentication_failed",
                outcome=AuditOutcome.DENIED,
                correlation_id=correlation_id,
                metadata={"path": path},
                occurred_at=utc_now(),
            )
        )
    except StorageError:
        # Auth enforcement must never depend on audit persistence
        # succeeding — the 401 above already happened regardless.
        logger.warning(
            "failed to record authentication_failed audit event",
            extra={"correlation_id": correlation_id},
        )
