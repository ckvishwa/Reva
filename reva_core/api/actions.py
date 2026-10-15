"""`/v1/actions/*`: propose an action, approve it, read it, report what happened (B3, ARD-600).

Exactly three paths, all behind the local Bearer token:

  POST /v1/actions/proposals       a typed proposal from an app (capability + arguments only)
  POST /v1/actions/{id}/approval   the click or tap on this PC that approves or denies a T2 action
  GET  /v1/actions/{id}            status
  PUT  /v1/actions/{id}            the executor's outcome report (needs the grant id it was given)

The broker (`reva_core/policy/broker.py`) does all the deciding; this module only translates. A
proposal from here never carries entity evidence or a hosted-model flag: arguments are checked
against the registry schema, whose enums are exact canonical names. The signed grant comes back only
in the response to the proposal or approval that issued it, never from a GET.

Deliberately does NOT use `from __future__ import annotations`; see the note at the top of
`routes.py` about FastAPI and closure dependencies.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from reva_core.api.auth import build_auth_dependency
from reva_core.api.versioned import VersionedRequest
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.policy.authorize import Proposal
from reva_core.policy.broker import ActionView, Broker, BrokerFull, GrantMismatch, UnknownAction
from reva_core.shared.ids import new_id

LOCAL_DEVICE = "local"


class ProposalRequest(VersionedRequest):
    capability: str = Field(min_length=1, max_length=100)
    args: dict[str, Any]
    proposal_id: str | None = Field(default=None, min_length=8, max_length=64)


class ApprovalRequest(VersionedRequest):
    decision: str = Field(pattern="^(approve|deny)$")
    via: str = Field(default="click", min_length=1, max_length=16)


class EvidenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    ref: str = Field(min_length=1, max_length=200)


class OutcomeRequest(VersionedRequest):
    grant_id: str = Field(min_length=1, max_length=64)
    status: str = Field(pattern="^(attempted|observed|verified|failed|unknown|denied)$")
    evidence: EvidenceBody | None = None


class ActionResponse(BaseModel):
    schema_version: str = "2.0"
    action_id: str
    capability: str
    tier: str
    status: str
    reason: str
    target_device_id: str
    created: str
    deadline: str | None = None
    speak: str | None = None
    clarification: dict[str, Any] | None = None
    evidence_kind: str | None = None
    prompt: str | None = None
    order: dict[str, Any] | None = None


def _response(view: ActionView, *, with_order: bool) -> ActionResponse:
    order = None
    if with_order and view.order is not None:
        order = {
            "grant": view.order.grant.to_dict(),
            "signature": view.order.signature,
            "capability": view.order.capability,
            "args": dict(view.order.args),
            "target_device_id": view.order.target_device,
        }
    return ActionResponse(
        action_id=view.action_id,
        capability=view.capability,
        tier=view.tier,
        status=view.status,
        reason=view.reason,
        target_device_id=view.target_device,
        created=view.created,
        deadline=view.deadline,
        speak=view.speak,
        clarification=view.clarification,
        evidence_kind=view.evidence_kind,
        prompt=view.prompt,
        order=order,
    )


def build_actions_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)

    def broker() -> Broker:
        found = lifecycle.broker
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="actions_unavailable"
            )
        return found

    @router.post(
        "/actions/proposals", response_model=ActionResponse, status_code=status.HTTP_201_CREATED
    )
    async def propose(
        payload: ProposalRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> ActionResponse:
        proposal = Proposal(
            proposal_id=payload.proposal_id or new_id(),
            capability=payload.capability,
            args=payload.args,
            source="ui",
            origin_device=LOCAL_DEVICE,
            target_device=LOCAL_DEVICE,
        )
        try:
            view = broker().propose(proposal)
        except BrokerFull as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_actions"
            ) from exc
        return _response(view, with_order=True)

    @router.post("/actions/{action_id}/approval", response_model=ActionResponse)
    async def approval(
        action_id: str,
        payload: ApprovalRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> ActionResponse:
        try:
            if payload.decision == "deny":
                view = broker().deny(action_id, via=payload.via)
            else:
                # The bearer token belongs to the app on this PC, so the click happened here.
                view = broker().approve(action_id, via=payload.via, device=LOCAL_DEVICE)
        except UnknownAction as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="action_not_found"
            ) from exc
        return _response(view, with_order=True)

    @router.get("/actions/{action_id}", response_model=ActionResponse)
    async def read_action(
        action_id: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> ActionResponse:
        try:
            view = broker().get(action_id)
        except UnknownAction as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="action_not_found"
            ) from exc
        return _response(view, with_order=False)

    @router.put("/actions/{action_id}", response_model=ActionResponse)
    async def report_outcome(
        action_id: str,
        payload: OutcomeRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> ActionResponse:
        evidence = payload.evidence.model_dump() if payload.evidence else None
        try:
            view = broker().report(action_id, payload.grant_id, payload.status, evidence)
        except UnknownAction as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="action_not_found"
            ) from exc
        except GrantMismatch as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="grant_mismatch"
            ) from exc
        return _response(view, with_order=False)

    return router
