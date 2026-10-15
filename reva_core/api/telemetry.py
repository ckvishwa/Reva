"""`/v1/settings/telemetry`: the switch for local, redacted, removable telemetry (AR-CORE-013).

Off by default. `DELETE` removes everything recorded and switches it off. Nothing is ever sent
anywhere: see `reva_core/telemetry/__init__.py`.

No `from __future__ import annotations`: see the note at the top of `routes.py`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from reva_core.api.auth import build_auth_dependency
from reva_core.api.versioned import VersionedRequest
from reva_core.orchestration.lifecycle import CoreLifecycle


class TelemetryUpdate(VersionedRequest):
    enabled: bool


def build_telemetry_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)

    def view() -> dict[str, Any]:
        telemetry = lifecycle.telemetry
        return {
            "schema_version": "2.0",
            "enabled": telemetry.enabled,
            "events_stored": len(telemetry.read()),
            "leaves_this_pc": False,
            "records": "Event names, success flags, durations and error codes only. "
            "Never text, audio, names, amounts or anything from your domains.",
        }

    @router.get("/settings/telemetry")
    async def get_telemetry(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        return view()

    @router.put("/settings/telemetry")
    async def put_telemetry(
        payload: TelemetryUpdate,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        lifecycle.telemetry.set_enabled(payload.enabled)
        return view()

    @router.delete("/settings/telemetry")
    async def delete_telemetry(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        lifecycle.telemetry.remove_all()
        return view()

    return router
