"""`/v1/settings/cloud`: the opt-in switch, per-domain consent and the API key (B1.7).

The key is write-only here: it goes to Windows Credential Manager and is never returned, logged or
put in an audit record. Cloud can be switched on only while a key is stored, so "on" always means
"will really call the hosted model".

Deliberately does NOT use `from __future__ import annotations`; see the note at the top of
`routes.py` about FastAPI and closure dependencies.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from reva_core.api.auth import build_auth_dependency
from reva_core.api.versioned import VersionedRequest
from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.providers.cloud import DISCLOSURE, HOSTED_DOMAINS, CloudSettings
from reva_core.security.credential_store import SecretStoreError, check_secret
from reva_core.shared.errors import StorageError
from reva_core.shared.ids import new_id
from reva_core.shared.logging import get_logger
from reva_core.shared.time import utc_now
from reva_core.storage.repositories.audit_repository import AuditRepository

logger = get_logger("api.cloud_settings")

_KEY_PREFIX = "sk-ant-"
_MIN_KEY_CHARS = 20


class CloudSettingsResponse(BaseModel):
    schema_version: str = "2.0"
    enabled: bool
    domains: dict[str, bool]
    key_configured: bool
    model: str
    timeout_seconds: float
    disclosure: dict[str, object]


class CloudSettingsUpdate(VersionedRequest):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    domains: dict[str, bool] | None = None


async def _read_key(request: Request) -> str:
    invalid = HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_key")
    try:
        body = await request.json()
    except ValueError as exc:
        raise invalid from exc
    value = body.get("api_key") if isinstance(body, dict) and set(body) == {"api_key"} else None
    if not isinstance(value, str):
        raise invalid
    key = value.strip()
    try:
        check_secret(key)
    except SecretStoreError as exc:
        raise invalid from exc
    if not key.startswith(_KEY_PREFIX) or len(key) < _MIN_KEY_CHARS:
        raise invalid
    return key


def build_cloud_settings_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)

    def _key_configured() -> bool:
        try:
            return bool(lifecycle.anthropic_secret_store.read())
        except SecretStoreError:
            return False

    def _view(settings: CloudSettings) -> CloudSettingsResponse:
        return CloudSettingsResponse(
            enabled=settings.enabled,
            domains=settings.domains,
            key_configured=_key_configured(),
            model=lifecycle.settings.cloud_model,
            timeout_seconds=lifecycle.settings.cloud_timeout_seconds,
            disclosure=DISCLOSURE,
        )

    def _audit(correlation_id: str, action: str, **metadata: object) -> None:
        try:
            AuditRepository(lifecycle.connection).insert(
                AuditEvent(
                    id=new_id(),
                    category=AuditEventCategory.SYSTEM,
                    action=action,
                    outcome=AuditOutcome.SUCCESS,
                    correlation_id=correlation_id,
                    metadata=metadata,  # never the key
                    occurred_at=utc_now(),
                )
            )
        except StorageError:
            logger.warning("cloud settings audit event could not be written")

    @router.get("/settings/cloud", response_model=CloudSettingsResponse)
    async def get_cloud_settings(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> CloudSettingsResponse:
        return _view(lifecycle.cloud_settings_store.load())

    @router.put("/settings/cloud", response_model=CloudSettingsResponse)
    async def put_cloud_settings(
        payload: CloudSettingsUpdate,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> CloudSettingsResponse:
        unknown = [name for name in (payload.domains or {}) if name not in HOSTED_DOMAINS]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown_domain"
            )
        store = lifecycle.cloud_settings_store
        settings = store.load()
        if payload.enabled is True and not _key_configured():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="key_required")
        if payload.enabled is not None:
            settings.enabled = payload.enabled
        for name, allowed in (payload.domains or {}).items():
            settings.domains[name] = allowed
        store.save(settings)
        for name, allowed in (payload.domains or {}).items():
            lifecycle.privacy_settings.set_hosted_model(name, allowed)  # mirror into the domain
        _audit(
            header_correlation_id,
            "cloud_settings_changed",
            enabled=settings.enabled,
            domains_on=sorted(name for name, on in settings.domains.items() if on),
        )
        return _view(settings)

    @router.put("/settings/cloud/key", response_model=CloudSettingsResponse)
    async def put_cloud_key(
        request: Request,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> CloudSettingsResponse:
        # The body is read by hand: a framework validation error would echo the rejected value,
        # which here is an API key.
        key = await _read_key(request)
        try:
            lifecycle.anthropic_secret_store.write(key)
        except SecretStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="secret_store_unavailable"
            ) from exc
        _audit(header_correlation_id, "cloud_key_stored")
        return _view(lifecycle.cloud_settings_store.load())

    @router.delete("/settings/cloud/key", response_model=CloudSettingsResponse)
    async def delete_cloud_key(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> CloudSettingsResponse:
        try:
            lifecycle.anthropic_secret_store.delete()
        except SecretStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="secret_store_unavailable"
            ) from exc
        store = lifecycle.cloud_settings_store
        settings = store.load()
        settings.enabled = False  # no key, no cloud
        store.save(settings)
        _audit(header_correlation_id, "cloud_key_removed")
        return _view(settings)

    return router
