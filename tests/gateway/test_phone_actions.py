"""C2: a phone asks the PC to act (AR-AND-008, AR-AGT-007/016, ADR-008, AC-009).

The phone sends a signed request; the PC's broker decides; a click on THIS PC approves anything
sensitive; the PC's executor does the work and reports evidence; only then does the phone hear
"done". These tests cover the refusals: no scope, an action outside the allowlist, a stale,
replayed, duplicated or substituted request, another phone's request, a revoked phone, and every
way a phone might try to approve for itself.
"""

from __future__ import annotations

import json
import secrets
import threading
from typing import Any

import pytest

from reva_core.gateway.service import _proposal_id
from reva_core.policy.authorize import Proposal
from tests.gateway.conftest import Env
from tests.gateway.phone import Phone

CALC = {"app_key": "calculator"}
SECRET_KEYS = ("order", "grant", "signature", "grant_id")


def _request_id() -> str:
    return secrets.token_urlsafe(18)


def _paired(env: Env, *, open_apps: bool = True, close_apps: bool = True) -> tuple[Phone, str]:
    env.enable()
    phone = env.new_phone()
    device_id = env.pair(phone)
    if open_apps or close_apps:
        _allow(env, device_id, open_apps=open_apps, close_apps=close_apps)
    return phone, device_id


def _allow(env: Env, device_id: str, *, open_apps: bool, close_apps: bool) -> None:
    reply = env.client.patch(
        f"/v1/devices/{device_id}/pc-access",
        json={"open_apps": open_apps, "close_apps": close_apps},
        headers=env.headers,
    )
    assert reply.status_code == 200, reply.text


def _ask(
    env: Env,
    phone: Phone,
    capability: str = "windows.app.open",
    args: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    age: int = 0,
    **kwargs: Any,
):
    body = {
        "request_id": request_id or _request_id(),
        "capability": capability,
        "args": CALC if args is None else args,
        "issued_at": int(env.clock[0]) - age,
    }
    reply = phone.signed("/actions/propose", body, **kwargs)
    return body["request_id"], reply


def _status(phone: Phone, request_id: str):
    return phone.signed("/actions/status", {"request_id": request_id})


def _inbox(env: Env, wait: float = 0.0) -> dict[str, Any]:
    reply = env.client.get(f"/v1/devices/requests?wait={wait}", headers=env.headers)
    assert reply.status_code == 200, reply.text
    body: dict[str, Any] = reply.json()
    return body


def _ledger_kinds(env: Env) -> list[str]:
    broker = env.lifecycle.broker
    assert broker is not None
    return [row.kind for row in broker.ledger.recent(500)]


def _no_secrets(reply) -> None:
    text = reply.body.decode()
    for key in SECRET_KEYS:
        assert f'"{key}"' not in text, f"{key} must never reach a phone"


def _report(env: Env, order: dict[str, Any], status: str, evidence: dict[str, str] | None):
    body: dict[str, Any] = {"grant_id": order["grant"]["grant_id"], "status": status}
    if evidence is not None:
        body["evidence"] = evidence
    return env.client.put(
        f"/v1/actions/{order['grant']['action_id']}", json=body, headers=env.headers
    )


# ------------------------------------------------------------------------------- scope and upgrade


def test_a_phone_paired_without_action_scopes_can_ask_for_nothing(env: Env) -> None:
    phone, _ = _paired(env, open_apps=False, close_apps=False)

    _, reply = _ask(env, phone)

    assert reply.status == 403 and reply.json() == {"error": "out_of_scope"}
    assert _ledger_kinds(env) == []
    assert _inbox(env)["items"] == []


def test_the_owner_upgrades_an_already_paired_phone_on_this_pc_and_can_take_it_back(
    env: Env,
) -> None:
    phone, device_id = _paired(env, open_apps=False, close_apps=False)
    listed = env.client.get("/v1/devices", headers=env.headers).json()["devices"][0]
    assert listed["actions"] == {"open_apps": False, "close_apps": False}
    assert listed["scopes"] == ["finance"]

    _allow(env, device_id, open_apps=True, close_apps=False)
    _, opened = _ask(env, phone)
    _, closed = _ask(env, phone, "windows.app.close")
    listed = env.client.get("/v1/devices", headers=env.headers).json()["devices"][0]

    assert opened.status == 200 and closed.status == 403
    assert listed["actions"] == {"open_apps": True, "close_apps": False}
    assert "finance" in listed["scopes"]  # the sync scope is untouched
    _allow(env, device_id, open_apps=False, close_apps=False)
    _, again = _ask(env, phone)
    assert again.status == 403


def test_only_the_owners_pc_can_change_scopes_and_only_for_an_active_phone(env: Env) -> None:
    phone, device_id = _paired(env, open_apps=False, close_apps=False)

    no_token = env.client.patch(
        f"/v1/devices/{device_id}/pc-access", json={"open_apps": True, "close_apps": True}
    )
    unknown = env.client.patch(
        "/v1/devices/00000000-0000-7000-8000-000000000000/pc-access",
        json={"open_apps": True, "close_apps": True},
        headers=env.headers,
    )
    over_the_gateway = phone.signed(
        f"/v1/devices/{device_id}/pc-access", {"open_apps": True, "close_apps": True}
    )
    env.client.post(f"/v1/devices/{device_id}/revoke", headers=env.headers)
    revoked = env.client.patch(
        f"/v1/devices/{device_id}/pc-access",
        json={"open_apps": True, "close_apps": True},
        headers=env.headers,
    )

    assert no_token.status_code in (401, 403)
    assert unknown.status_code == 404
    assert over_the_gateway.status == 404
    assert revoked.status_code == 404


def test_the_phone_can_not_ask_for_anything_outside_the_allowlist(env: Env) -> None:
    phone, _ = _paired(env)
    forbidden_here = [
        ("windows.ui.invoke", {"target": "x"}),
        ("memory.remember", {"content": "x"}),
        ("finance.add_transaction", {"amount": 1, "currency": "USD", "category": "x", "note": "y"}),
        ("assistant.undo", {"target_action_id": "a" * 20}),
        ("android.app.open", {"app_key": "x"}),
        ("shell.run", {}),
        ("finance.transfer", {}),
        ("", {}),
        ("windows.app.OPEN", CALC),
    ]

    for capability, args in forbidden_here:
        _, reply = _ask(env, phone, capability, args)
        assert reply.status == 403 and reply.json() == {"error": "capability_not_allowed"}, (
            capability
        )

    assert _ledger_kinds(env) == []


# --------------------------------------------------------------------------- open (T1) end to end


def test_open_is_granted_to_the_pc_and_the_phone_hears_done_only_after_the_executor_reports(
    env: Env,
) -> None:
    phone, _ = _paired(env)

    request_id, asked = _ask(env, phone)
    waiting = _status(phone, request_id).json()
    items = _inbox(env)["items"]

    assert asked.status == 200
    body = asked.json()
    assert body["status"] == "granted" and body["tier"] == "T1"
    assert body["speak"] is None, "a grant is a request, not a result"
    _no_secrets(asked)
    assert waiting["status"] == "granted" and waiting["speak"] is None
    assert len(items) == 1 and items[0]["order"] is not None and items[0]["from"] == phone.name
    order = items[0]["order"]
    assert order["capability"] == "windows.app.open" and order["args"] == CALC
    assert _inbox(env)["items"] == [], "an order is handed to the executor once"

    reported = _report(
        env, order, "verified", {"kind": "process_started", "ref": "pid:4412 window:0x30a2"}
    )
    done = _status(phone, request_id)

    assert reported.status_code == 200
    assert done.json()["status"] == "verified" and done.json()["speak"] == "Opened Calculator."
    _no_secrets(done)


def test_a_verified_report_without_evidence_is_unknown_never_done(env: Env) -> None:
    phone, _ = _paired(env)
    request_id, _ = _ask(env, phone)
    order = _inbox(env)["items"][0]["order"]

    _report(env, order, "verified", {"kind": "process_started", "ref": "ok"})
    after = _status(phone, request_id).json()

    assert after["status"] == "unknown"
    assert "opened" not in (after["speak"] or "").lower()


def test_a_failure_the_phone_hears_is_a_failure(env: Env) -> None:
    phone, _ = _paired(env)
    request_id, _ = _ask(env, phone)
    order = _inbox(env)["items"][0]["order"]

    _report(env, order, "failed", None)

    after = _status(phone, request_id).json()
    assert (
        after["status"] == "failed" and after["speak"] == "That didn't work. Nothing was changed."
    )


def test_an_unknown_app_or_extra_arguments_are_refused_before_anything_is_granted(env: Env) -> None:
    phone, _ = _paired(env)

    for args in ({"app_key": "format-c"}, {}, {"app_key": "calculator", "path": "C:\\x.exe"}):
        _, reply = _ask(env, phone, args=args)
        assert reply.status == 200
        assert reply.json()["status"] == "refused" and reply.json()["reason"] == "INVALID_ARGS"

    assert _inbox(env)["items"] == []


def test_oversized_or_malformed_requests_are_422(env: Env) -> None:
    phone, _ = _paired(env)
    cases: list[dict[str, Any]] = [
        {"request_id": "short", "capability": "windows.app.open", "args": CALC, "issued_at": 1},
        {"request_id": _request_id(), "capability": 5, "args": CALC, "issued_at": 1},
        {"request_id": _request_id(), "capability": "windows.app.open", "args": [], "issued_at": 1},
        {"request_id": _request_id(), "capability": "windows.app.open", "args": CALC},
        {
            "request_id": _request_id(),
            "capability": "windows.app.open",
            "args": {"app_key": "x" * 5000},
            "issued_at": int(env.clock[0]),
        },
    ]

    for body in cases:
        assert phone.signed("/actions/propose", body).status == 422, body

    assert _ledger_kinds(env) == []


# ---------------------------------------------------------- close (T2): the click is on the PC


def test_a_phone_request_to_close_waits_for_a_click_on_this_pc_and_never_a_phone_tap(
    env: Env,
) -> None:
    phone, device_id = _paired(env)
    request_id, asked = _ask(env, phone, "windows.app.close")
    card = _inbox(env)["items"][0]
    action_id = card["action_id"]

    assert asked.json()["status"] == "awaiting_approval" and asked.json()["tier"] == "T2"
    assert card["order"] is None and card["prompt"] == "Close Calculator? Approve it on screen."
    _no_secrets(asked)

    # A spoken yes, a made-up "phone" screen and the phone's own device id are not this PC's click.
    broker = env.lifecycle.broker
    spoken = env.client.post(
        f"/v1/actions/{action_id}/approval",
        json={"decision": "approve", "via": "speech"},
        headers=env.headers,
    )
    from_phone = broker.approve(action_id, via="tap", device=device_id)
    assert spoken.json()["status"] == "awaiting_approval"
    assert from_phone.status == "awaiting_approval" and from_phone.order is None
    assert _status(phone, request_id).json()["status"] == "awaiting_approval"
    # The gateway has no route for approving at all.
    assert phone.signed("/actions/approve", {"request_id": request_id}).status == 404
    assert (
        phone.signed("/actions/status", {"request_id": request_id, "approve": True}).status == 200
    )
    assert _status(phone, request_id).json()["status"] == "awaiting_approval"

    clicked = env.client.post(
        f"/v1/actions/{action_id}/approval",
        json={"decision": "approve", "via": "click"},
        headers=env.headers,
    ).json()
    assert clicked["status"] == "granted" and clicked["order"] is not None
    assert _status(phone, request_id).json()["speak"] is None

    _report(env, clicked["order"], "verified", {"kind": "process_exited", "ref": "pid:77 exited"})
    done = _status(phone, request_id).json()
    assert done["status"] == "verified" and done["speak"] == "Closed Calculator."


def test_denying_on_the_pc_is_what_the_phone_hears(env: Env) -> None:
    phone, _ = _paired(env)
    request_id, _ = _ask(env, phone, "windows.app.close")
    action_id = _inbox(env)["items"][0]["action_id"]

    env.client.post(
        f"/v1/actions/{action_id}/approval", json={"decision": "deny"}, headers=env.headers
    )

    after = _status(phone, request_id).json()
    assert after["status"] == "denied" and after["speak"] == "Okay, I won't do that."
    assert _inbox(env)["items"] == []


def test_an_approval_that_waits_too_long_expires_and_nothing_runs(env: Env) -> None:
    phone, _ = _paired(env)
    request_id, _ = _ask(env, phone, "windows.app.close")
    action_id = _inbox(env)["items"][0]["action_id"]
    broker = env.lifecycle.broker
    from datetime import timedelta

    real = broker.clock
    broker.clock = lambda: real() + timedelta(minutes=3)

    after = _status(phone, request_id).json()
    late_click = env.client.post(
        f"/v1/actions/{action_id}/approval",
        json={"decision": "approve", "via": "click"},
        headers=env.headers,
    ).json()

    assert (
        after["status"] == "expired"
        and after["speak"] == "That request timed out, so I didn't do it."
    )
    assert late_click["status"] == "expired" and late_click["order"] is None
    assert _inbox(env)["items"] == []


def test_a_phone_request_shows_in_activity_as_from_the_phone(env: Env) -> None:
    phone, _ = _paired(env)
    _ask(env, phone)

    rows = env.client.get("/v1/activity", headers=env.headers).json()["items"]

    assert rows and rows[0]["from"] == "Phone" and rows[0]["request"].startswith("Open")


# ------------------------------------------------------- stale, replayed, duplicate, substituted


def test_a_request_that_sat_too_long_is_refused_as_expired(env: Env) -> None:
    phone, _ = _paired(env)

    _, old = _ask(env, phone, age=121)
    _, future = _ask(env, phone, age=-31)
    _, fresh = _ask(env, phone, age=119)

    assert old.status == 410 and old.json() == {"error": "request_expired"}
    assert future.status == 410
    assert fresh.status == 200
    assert _ledger_kinds(env).count("proposed") == 1


def test_a_replayed_signed_request_is_refused_and_does_not_act_twice(env: Env) -> None:
    phone, _ = _paired(env)
    nonce = secrets.token_urlsafe(16)
    request_id = _request_id()
    body = {
        "request_id": request_id,
        "capability": "windows.app.open",
        "args": CALC,
        "issued_at": int(env.clock[0]),
    }

    first = phone.signed("/actions/propose", body, nonce=nonce, timestamp=int(env.clock[0]))
    replay = phone.signed("/actions/propose", body, nonce=nonce, timestamp=int(env.clock[0]))

    assert first.status == 200
    assert replay.status == 401 and replay.json() == {"error": "unauthorized"}
    assert len(_inbox(env)["items"]) == 1


def test_sending_the_same_request_again_is_one_action_not_two(env: Env) -> None:
    phone, _ = _paired(env)
    request_id = _request_id()

    _, first = _ask(env, phone, request_id=request_id)
    _, again = _ask(env, phone, request_id=request_id)  # a retry after a dropped connection
    items = _inbox(env)["items"]
    _, third = _ask(env, phone, request_id=request_id)

    assert first.json()["status"] == again.json()["status"] == "granted"
    assert len(items) == 1
    assert _inbox(env)["items"] == []
    assert third.status == 200
    assert _ledger_kinds(env).count("proposed") == 1
    _report(
        env, items[0]["order"], "verified", {"kind": "process_started", "ref": "pid:9 window:0x1"}
    )
    _, after = _ask(env, phone, request_id=request_id)
    assert after.json()["status"] == "verified"
    assert _inbox(env)["items"] == [], "a retry after success must not run it again"


def test_the_same_id_with_different_content_is_refused_not_merged(env: Env) -> None:
    phone, _ = _paired(env)
    request_id = _request_id()
    _ask(env, phone, request_id=request_id)

    _, other_app = _ask(env, phone, args={"app_key": "notepad"}, request_id=request_id)
    _, other_capability = _ask(env, phone, "windows.app.close", request_id=request_id)

    for reply in (other_app, other_capability):
        assert reply.status == 200
        assert reply.json()["status"] == "refused" and reply.json()["reason"] == "STATE_MISMATCH"
    order = _inbox(env)["items"][0]["order"]
    assert order["args"] == CALC, "the original request is untouched"


def test_two_phones_cannot_read_or_overwrite_each_others_requests(env: Env) -> None:
    env.enable()
    first, second = env.new_phone("First"), env.new_phone("Second")
    for phone in (first, second):
        _allow(env, env.pair(phone), open_apps=True, close_apps=True)
    request_id = _request_id()
    _ask(env, first, request_id=request_id)

    stranger_read = _status(second, request_id)
    _, same_id = _ask(env, second, args={"app_key": "notepad"}, request_id=request_id)
    first_status = _status(first, request_id).json()

    assert stranger_read.status == 404 and stranger_read.json() == {"error": "unknown_request"}
    assert same_id.json()["status"] == "granted", "a different phone's id space is separate"
    assert first_status["status"] == "granted"
    orders = [item["order"]["args"] for item in _inbox(env)["items"]]
    assert sorted(o["app_key"] for o in orders) == ["calculator", "notepad"]


def test_an_unknown_request_id_is_404_and_a_malformed_one_422(env: Env) -> None:
    phone, _ = _paired(env)

    assert _status(phone, _request_id()).status == 404
    assert phone.signed("/actions/status", {"request_id": "x"}).status == 422
    assert phone.signed("/actions/status", {}).status == 422


# ------------------------------------------------------------------------------------- revocation


def test_revoking_a_phone_withdraws_what_it_asked_and_the_pc_never_runs_it(env: Env) -> None:
    phone, device_id = _paired(env)
    waiting_id, _ = _ask(env, phone, "windows.app.close")
    open_id, _ = _ask(env, phone)

    env.client.post(f"/v1/devices/{device_id}/revoke", headers=env.headers)

    broker = env.lifecycle.broker
    for request_id in (waiting_id, open_id):  # withdrawn at once, before anyone polls
        view = broker.get(_proposal_id(device_id, request_id))
        assert view.status == "denied" and view.reason == "DEVICE_REVOKED", request_id
        assert view.order is None
    assert _inbox(env)["items"] == []
    assert _ledger_kinds(env).count("denied") == 2
    after = phone.signed("/actions/status", {"request_id": waiting_id}, verify_reply=False)
    assert after.status == 401
    _, again = _ask(env, phone, verify_reply=False)
    assert again.status == 401


def test_an_order_already_in_the_executors_hands_is_not_recalled_but_still_reports(
    env: Env,
) -> None:
    phone, device_id = _paired(env)
    _ask(env, phone)
    order = _inbox(env)["items"][0]["order"]

    env.client.post(f"/v1/devices/{device_id}/revoke", headers=env.headers)
    reported = _report(
        env, order, "verified", {"kind": "process_started", "ref": "pid:12 window:0x9"}
    )

    assert reported.status_code == 200 and reported.json()["status"] == "verified"


# ------------------------------------------------------------------------------ surfaces and limits


def test_the_gateway_has_no_inbox_and_no_approval_the_phone_can_reach(env: Env) -> None:
    phone, _ = _paired(env)
    _, asked = _ask(env, phone, "windows.app.close")
    action_id = _inbox(env)["items"][0]["action_id"]

    for path in (
        "/v1/devices/requests",
        f"/v1/actions/{action_id}/approval",
        f"/v1/actions/{action_id}",
        "/actions/inbox",
        "/actions/approve",
        "/actions/report",
    ):
        for method in ("GET", "POST", "PUT"):
            reply = phone.request(method, path, b"{}")
            assert reply.status in (404, 405), (method, path, reply.status)
    assert asked.status == 200


def test_the_inbox_needs_the_core_token(env: Env) -> None:
    _paired(env)

    assert env.client.get("/v1/devices/requests").status_code in (401, 403)


def test_the_inbox_long_poll_wakes_when_a_phone_asks(env: Env) -> None:
    phone, _ = _paired(env)
    seq = _inbox(env)["seq"]
    results: list[dict[str, Any]] = []

    waiter = threading.Thread(target=lambda: results.append(_inbox_after(env, seq, 10.0)))
    waiter.start()
    _ask(env, phone)
    waiter.join(timeout=15)

    assert results and results[0]["seq"] > seq and len(results[0]["items"]) == 1


def _inbox_after(env: Env, after: int, wait: float) -> dict[str, Any]:
    reply = env.client.get(f"/v1/devices/requests?after={after}&wait={wait}", headers=env.headers)
    body: dict[str, Any] = reply.json()
    return body


def test_the_inbox_wait_is_capped_and_returns_empty_quickly_when_nothing_happens(env: Env) -> None:
    _paired(env)
    seq = _inbox(env)["seq"]

    body = _inbox_after(env, seq, 0.2)

    assert body["items"] == [] and body["seq"] == seq


def test_many_phones_asking_at_once_never_corrupt_the_broker(env: Env) -> None:
    _, device_id = _paired(env)
    broker = env.lifecycle.broker
    errors: list[BaseException] = []

    def ask(n: int) -> None:
        try:
            for i in range(7):
                broker.propose(
                    Proposal(
                        proposal_id=f"ph-{n:02d}-{i:02d}-" + "a" * 20,
                        capability="windows.app.open",
                        args=CALC,
                        source="phone",
                        origin_device=device_id,
                        target_device="local",
                    ),
                    device_scopes=frozenset({"windows"}),
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=ask, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert len(_inbox(env)["items"]) == 56
    assert _ledger_kinds(env).count("proposed") == 56
    assert _inbox(env)["items"] == []


def test_one_phone_cannot_fill_the_broker_and_starve_this_pcs_own_actions(env: Env) -> None:
    phone, _ = _paired(env)
    first_id, _ = _ask(env, phone, "windows.app.close")
    for _n in range(7):
        assert _ask(env, phone, "windows.app.close")[1].status == 200

    _, ninth = _ask(env, phone, "windows.app.close")
    _, retry = _ask(env, phone, "windows.app.close", request_id=first_id)
    own = env.client.post(
        "/v1/actions/proposals",
        json={"capability": "windows.app.open", "args": CALC},
        headers=env.headers,
    )

    assert ninth.status == 429 and ninth.json() == {"error": "too_many_actions"}
    assert retry.status == 200, "a retry of a request the PC already has is not a new request"
    assert own.status_code == 201, "this PC's own app is not affected"


def test_responses_are_signed_by_the_paired_pc_and_carry_no_secrets(env: Env) -> None:
    phone, _ = _paired(env)

    _, reply = _ask(env, phone)

    assert reply.status == 200
    assert reply.headers.get("x-reva-resp-sig")
    parsed = json.loads(reply.body)
    assert set(parsed) == {
        "request_id", "capability", "tier", "status", "reason", "speak", "prompt", "deadline",
        "evidence_kind",
    }  # fmt: skip


@pytest.mark.parametrize("path", ["/actions/propose", "/actions/status"])
def test_no_credentials_no_service_on_the_action_routes(env: Env, path: str) -> None:
    phone, _ = _paired(env)

    reply = phone.post(path, {"request_id": _request_id()})

    assert reply.status == 401 and reply.json() == {"error": "unauthorized"}
