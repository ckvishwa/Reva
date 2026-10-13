"""`/v1/devices/*` on the loopback Core API: the Devices page's controls for the pairing gateway.

These routes use the Core bearer token like every other `/v1/*` route. The phone never calls them
and never sees that token; it talks only to the gateway app (reva_core/gateway/app.py).

Deliberately does NOT use `from __future__ import annotations`; see the note in
`reva_core/api/routes.py` about FastAPI and closure dependencies.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from reva_core.api.auth import build_auth_dependency
from reva_core.domains.service import DomainRequestError
from reva_core.gateway.manager import GatewayStateError
from reva_core.gateway.server import GatewayListenError
from reva_core.orchestration.lifecycle import CoreLifecycle


class GatewaySetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(pattern=r"^\d{6}$")


def build_devices_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1/devices")
    require_token = build_auth_dependency(lifecycle)

    def guarded(fn: Any) -> Any:
        try:
            return fn()
        except GatewayStateError as exc:
            raise DomainRequestError(exc.code, exc.status) from exc
        except GatewayListenError as exc:
            raise DomainRequestError("gateway_unavailable", 409, str(exc)) from exc

    @router.get("")
    def list_devices(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        gateway = lifecycle.gateway
        return {"gateway": gateway.status(), "devices": gateway.devices()}

    @router.patch("/gateway")
    def set_gateway(
        body: GatewaySetting,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        return {"gateway": guarded(lambda: lifecycle.gateway.set_enabled(body.enabled))}

    @router.post("/pairing")
    def open_pairing(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        result: dict[str, Any] = guarded(lifecycle.gateway.open_pairing)
        return result

    @router.post("/pairing/approve")
    def approve_pairing(
        body: Approval,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        result: dict[str, Any] = guarded(
            lambda: lifecycle.gateway.approve_pairing(body.fingerprint)
        )
        return result

    @router.post("/pairing/deny")
    def deny_pairing(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        guarded(lifecycle.gateway.deny_pairing)
        return {"denied": True}

    @router.post("/{device_id}/revoke")
    def revoke_device(
        device_id: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        changed = guarded(lambda: lifecycle.gateway.revoke(device_id))
        return {"device_id": device_id, "revoked": True, "changed": changed}

    return router
