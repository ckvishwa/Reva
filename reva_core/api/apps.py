"""`/v1/apps` and `/v1/activity`: the Apps & Actions page and the Activity page (B3c).

`/v1/apps` is the allowlist the owner controls. The Windows app reports what it found in the Start
Menu (`PUT /v1/apps/discovered`); those apps wait there until the owner approves one with the
spoken names they want (`PUT /v1/apps/{key}`). Approving only adds a key, a display name and
aliases to what REVA may be asked to open or close: launch targets stay on the PC, so no request can
name a program or a path. The list is local to this PC (Bearer token), like everything under /v1.

`/v1/activity` lists the action ledger for the owner to read.

No `from __future__ import annotations`: see the note at the top of `routes.py`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from reva_core.api.auth import build_auth_dependency
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.policy import activity
from reva_core.policy.apps import AppCatalogError


class DiscoveredApp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=32)
    display_name: str = Field(min_length=1, max_length=60)


class DiscoveredRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apps: list[DiscoveredApp] = Field(max_length=500)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=8)


def build_apps_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)

    def listing() -> dict[str, Any]:
        catalog = lifecycle.apps
        return {
            "apps": [
                {
                    "key": a.key,
                    "display_name": a.display_name,
                    "aliases": list(a.aliases),
                    "builtin": a.builtin,
                }
                for a in catalog.apps()
            ],
            "waiting": [{"key": k, "display_name": n} for k, n in catalog.waiting()],
        }

    @router.get("/apps")
    async def list_apps(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        return listing()

    @router.put("/apps/discovered")
    async def report_discovered(
        payload: DiscoveredRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        lifecycle.apps.report_discovered([(a.key, a.display_name) for a in payload.apps])
        return listing()

    @router.put("/apps/{key}")
    async def approve_app(
        key: str,
        payload: ApproveRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        try:
            lifecycle.apps.approve(key, payload.display_name, payload.aliases)
        except AppCatalogError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return listing()

    @router.delete("/apps/{key}")
    async def remove_app(
        key: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        try:
            lifecycle.apps.remove(key)
            lifecycle.apps.dismiss(key)
        except AppCatalogError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return listing()

    @router.get("/activity")
    async def list_activity(
        header_correlation_id: Annotated[str, Depends(require_token)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        broker = lifecycle.broker
        if broker is None:
            return {"items": []}
        return {
            "items": activity.recent(broker.ledger, lifecycle.apps.display_names(), limit),
        }

    return router
