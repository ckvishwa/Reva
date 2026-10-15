"""`/v1/settings/privacy`: per-domain sync / devices / hosted-model switches (FR-DOM-006).

One read and one write for all domains. The switches are enforced where the data would leave: the
pairing gateway checks `devices` then `sync` before any replication, and the consent filter checks
`hosted_model` before anything reaches a hosted model (see `domains/privacy_settings.py`).

No `from __future__ import annotations`: see the note at the top of `routes.py`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from reva_core.api.auth import build_auth_dependency
from reva_core.api.versioned import VersionedRequest
from reva_core.orchestration.lifecycle import CoreLifecycle


class PrivacyUpdate(VersionedRequest):
    domains: dict[str, dict[str, Any]]


def build_privacy_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)

    @router.get("/settings/privacy")
    async def get_privacy(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        return {"schema_version": "2.0", "domains": lifecycle.privacy_settings.snapshot()}

    @router.put("/settings/privacy")
    async def put_privacy(
        payload: PrivacyUpdate,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        domains = lifecycle.privacy_settings.update(payload.domains)
        return {"schema_version": "2.0", "domains": domains}

    return router
