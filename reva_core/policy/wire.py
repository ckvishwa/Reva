"""How an `ActionView` looks on the wire: the same shape for HTTP responses and session events."""

from __future__ import annotations

from typing import Any

from reva_core.policy.broker import ActionView

FINAL = frozenset({"verified", "failed", "unknown", "denied", "expired", "refused"})


def view_to_dict(view: ActionView, *, with_order: bool) -> dict[str, Any]:
    """The order (signed grant) is included only when the caller is the one who must act on it."""
    body: dict[str, Any] = {
        "action_id": view.action_id,
        "capability": view.capability,
        "tier": view.tier,
        "status": view.status,
        "reason": view.reason,
        "target_device_id": view.target_device,
        "created": view.created,
        "deadline": view.deadline,
        "speak": view.speak,
        "clarification": view.clarification,
        "evidence_kind": view.evidence_kind,
        "prompt": view.prompt,
        "order": None,
    }
    if with_order and view.order is not None:
        body["order"] = {
            "grant": view.order.grant.to_dict(),
            "signature": view.order.signature,
            "capability": view.order.capability,
            "args": dict(view.order.args),
            "target_device_id": view.order.target_device,
        }
    return body
