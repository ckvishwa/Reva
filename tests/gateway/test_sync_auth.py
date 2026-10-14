"""Who may sync (AR-DATA-002/003/004/007/015): mutual authentication on every request.

Unauthenticated access, replayed and stale requests, tampering, scope and privacy switch, and
revocation in the middle of a session all fail closed. The Core API's bearer token is not a way in.
"""

from __future__ import annotations

import json

import pytest

from reva_core.audit.events import AuditOutcome
from reva_core.gateway.protocol import (
    HEADER_DEVICE,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
)
from reva_core.storage.repositories.audit_repository import AuditRepository
from tests.gateway.conftest import Env
from tests.gateway.phone import Phone

SYNC_PATHS = ("/sync/push", "/sync/pull", "/sync/ack")


def _paired(env: Env) -> Phone:
    env.enable()
    phone = env.new_phone()
    env.pair(phone)
    return phone


def _unauthorized(reply) -> None:
    assert reply.status == 401 and reply.json() == {"error": "unauthorized"}, (
        reply.status,
        reply.body,
    )


# ------------------------------------------------------------------------- unauthenticated access


@pytest.mark.parametrize("path", SYNC_PATHS)
def test_no_credentials_no_service(env: Env, path: str) -> None:
    phone = _paired(env)
    _unauthorized(phone.post(path, {"domain": "finance", "cursor": 0, "limit": 10}))


@pytest.mark.parametrize("path", SYNC_PATHS)
def test_garbage_credentials_are_refused_with_one_uniform_answer(env: Env, path: str) -> None:
    phone = _paired(env)
    good_nonce = "n" * 22
    for headers in (
        {HEADER_DEVICE: "x"},
        {
            HEADER_DEVICE: phone.device_id or "",
            HEADER_TIMESTAMP: "soon",
            HEADER_NONCE: good_nonce,
            HEADER_SIGNATURE: "AA",
        },
        {
            HEADER_DEVICE: phone.device_id or "",
            HEADER_TIMESTAMP: str(int(env.clock[0])),
            HEADER_NONCE: "short",
            HEADER_SIGNATURE: "AA",
        },
        {
            HEADER_DEVICE: phone.device_id or "",
            HEADER_TIMESTAMP: str(int(env.clock[0])),
            HEADER_NONCE: good_nonce,
            HEADER_SIGNATURE: "!!!",
        },
        {
            HEADER_DEVICE: phone.device_id or "",
            HEADER_TIMESTAMP: str(int(env.clock[0])),
            HEADER_NONCE: good_nonce,
            HEADER_SIGNATURE: "AAAA",
        },
        {
            HEADER_DEVICE: "0" * 36,
            HEADER_TIMESTAMP: str(int(env.clock[0])),
            HEADER_NONCE: good_nonce,
            HEADER_SIGNATURE: "AAAA",
        },
    ):
        _unauthorized(phone.post(path, {"domain": "finance"}, headers=headers))


def test_an_unknown_device_and_a_revoked_one_look_the_same_from_outside(env: Env) -> None:
    phone = _paired(env)
    stranger = env.new_phone("Stranger")
    stranger.host, stranger.port, stranger.gateway_sha256 = (
        phone.host,
        phone.port,
        phone.gateway_sha256,
    )
    stranger.device_id = "00000000-0000-7000-8000-000000000000"
    stranger.pc_signing_key = phone.pc_signing_key
    one = stranger.signed("/sync/pull", {"domain": "finance", "limit": 5}, verify_reply=False)
    env.client.post(f"/v1/devices/{phone.device_id}/revoke", headers=env.headers)
    two = phone.signed("/sync/pull", {"domain": "finance", "limit": 5}, verify_reply=False)
    assert (one.status, one.body) == (two.status, two.body)


def test_another_phones_signature_does_not_work_under_my_device_id(env: Env) -> None:
    env.enable()
    first, second = env.new_phone("First"), env.new_phone("Second")
    env.pair(first)
    env.pair(second)
    reply = second.signed(
        "/sync/pull",
        {"domain": "finance", "limit": 5},
        device_id=first.device_id,
        verify_reply=False,
    )
    _unauthorized(reply)


# ----------------------------------------------------------------- replay, staleness, tampering


def test_a_replayed_request_is_refused(env: Env) -> None:
    phone = _paired(env)
    stamp = int(env.clock[0])
    first = phone.signed(
        "/sync/pull", {"domain": "finance", "limit": 5}, nonce="r" * 22, timestamp=stamp
    )
    assert first.status == 200
    again = phone.signed(
        "/sync/pull",
        {"domain": "finance", "limit": 5},
        nonce="r" * 22,
        timestamp=stamp,
        verify_reply=False,
    )
    _unauthorized(again)
    fresh = phone.signed("/sync/pull", {"domain": "finance", "limit": 5})
    assert fresh.status == 200


def test_a_replayed_batch_with_a_new_nonce_changes_nothing(env: Env) -> None:
    phone = _paired(env)
    env.add_account(phone.kernel)
    env.add_expense(phone.kernel, "tx-phone-001", -1200)
    assert phone.push().status == 200
    digest = env.pc_kernel().projection_digest()
    events = env.pc_kernel().event_count()

    phone.kernel.reset_peer_cursors(phone.pc_kernel_id)  # the phone lost its ack and resends all
    again = phone.push()
    body = again.json()
    assert again.status == 200 and body["applied"] == 0 and body["duplicates"] == 2
    assert env.pc_kernel().projection_digest() == digest and env.pc_kernel().event_count() == events


def test_old_and_future_timestamps_are_refused_but_small_drift_is_fine(env: Env) -> None:
    phone = _paired(env)
    now = int(env.clock[0])
    body = {"domain": "finance", "limit": 5}
    for stamp in (now - 121, now + 121, now - 3600):
        _unauthorized(phone.signed("/sync/pull", body, timestamp=stamp, verify_reply=False))
    for stamp in (now - 100, now + 100):
        assert phone.signed("/sync/pull", body, timestamp=stamp).status == 200


def test_a_nonce_cannot_be_replayed_after_the_clock_moves_a_little(env: Env) -> None:
    phone = _paired(env)
    stamp = int(env.clock[0])
    assert (
        phone.signed(
            "/sync/pull", {"domain": "finance", "limit": 1}, nonce="q" * 22, timestamp=stamp
        ).status
        == 200
    )
    env.clock[0] += 60
    again = phone.signed(
        "/sync/pull",
        {"domain": "finance", "limit": 1},
        nonce="q" * 22,
        timestamp=stamp,
        verify_reply=False,
    )
    _unauthorized(again)


def test_a_body_changed_after_signing_is_refused(env: Env) -> None:
    phone = _paired(env)
    _unauthorized(
        phone.signed(
            "/sync/pull", {"domain": "finance", "limit": 5}, tamper_body=True, verify_reply=False
        )
    )


def test_a_signature_for_one_path_is_not_valid_for_another(env: Env) -> None:
    phone = _paired(env)
    stamp, nonce = int(env.clock[0]), "p" * 22
    data = {"domain": "finance", "limit": 5}
    body = json.dumps(data).encode()
    from reva_core.gateway import protocol

    signature = phone.sign(
        protocol.request_message("POST", "/sync/pull", stamp, nonce, body, phone.gateway_sha256)
    )
    reply = phone.request(
        "POST",
        "/sync/push",
        body,
        {
            HEADER_DEVICE: phone.device_id or "",
            HEADER_TIMESTAMP: str(stamp),
            HEADER_NONCE: nonce,
            HEADER_SIGNATURE: protocol.b64u(signature),
        },
    )
    _unauthorized(reply)


def test_an_answer_not_signed_by_the_paired_pc_is_detected_by_the_phone(env: Env) -> None:
    from tests.gateway.phone import BadResponseSignature

    phone = _paired(env)
    phone.pc_signing_key = env.new_phone("Impostor").public  # the phone expects another PC key
    with pytest.raises(BadResponseSignature):
        phone.signed("/sync/pull", {"domain": "finance", "limit": 5})


# ---------------------------------------------------------------------------- revocation


def test_a_device_revoked_in_the_middle_of_a_session_is_cut_off_at_once(env: Env) -> None:
    phone = _paired(env)
    env.add_account(env.pc_kernel())
    reply, report = phone.pull()
    assert reply.status == 200 and report.applied == 1

    revoked = env.client.post(f"/v1/devices/{phone.device_id}/revoke", headers=env.headers)
    assert revoked.status_code == 200 and revoked.json()["changed"] is True

    env.add_expense(env.pc_kernel(), "tx-after-0001", -500)
    for path, data in (
        ("/sync/pull", {"domain": "finance", "limit": 5}),
        (
            "/sync/push",
            {
                "domain": "finance",
                "events_json": "[]",
                "cursor_from": 0,
                "cursor_to": 0,
                "count": 0,
            },
        ),
        ("/sync/ack", {"domain": "finance", "cursor": 1}),
    ):
        _unauthorized(phone.signed(path, data, verify_reply=False))
    (peer,) = env.pc_kernel().list_peers()
    assert peer.status == "revoked"
    (device,) = env.client.get("/v1/devices", headers=env.headers).json()["devices"]
    assert device["status"] == "revoked" and device["revoked_at"]


def test_revocation_between_admission_steps_still_stops_the_request(env: Env) -> None:
    """`precheck` runs before the body is read, `dispatch` after. A revoke in between must win."""
    from reva_core.gateway import protocol
    from reva_core.gateway.service import GatewayError

    phone = _paired(env)
    service = env.manager._service  # noqa: SLF001
    body = json.dumps({"domain": "finance", "limit": 5}).encode()
    stamp, nonce = int(env.clock[0]), "z" * 22
    signature = phone.sign(
        protocol.request_message("POST", "/sync/pull", stamp, nonce, body, phone.gateway_sha256)
    )
    service.precheck(device_id=phone.device_id, timestamp=str(stamp), nonce=nonce, remote="t")
    env.manager.revoke(phone.device_id)
    with pytest.raises(GatewayError) as refused:
        service.dispatch(
            lambda grant: service.pull(grant, {"domain": "finance", "limit": 5}),
            device_id=phone.device_id,
            timestamp=str(stamp),
            nonce=nonce,
            signature=protocol.b64u(signature),
            method="POST",
            path="/sync/pull",
            body=body,
            remote="t",
        )
    assert (refused.value.code, refused.value.status) == ("unauthorized", 401)


def test_revoking_twice_is_harmless_and_unknown_devices_are_404(env: Env) -> None:
    phone = _paired(env)
    url = f"/v1/devices/{phone.device_id}/revoke"
    assert env.client.post(url, headers=env.headers).json()["changed"] is True
    assert env.client.post(url, headers=env.headers).json()["changed"] is False
    assert (
        env.client.post("/v1/devices/no-such-device/revoke", headers=env.headers).status_code == 404
    )


def test_revoking_works_with_the_gateway_switched_off(env: Env) -> None:
    phone = _paired(env)
    env.client.patch("/v1/devices/gateway", json={"enabled": False}, headers=env.headers)
    assert (
        env.client.post(f"/v1/devices/{phone.device_id}/revoke", headers=env.headers).status_code
        == 200
    )
    assert env.pc_kernel().list_peers()[0].status == "revoked"


def test_a_request_in_flight_finishes_before_revoke_returns(env: Env) -> None:
    """Admission and the Kernel call share one lock with revoke: no request survives a revoke."""
    import threading

    phone = _paired(env)
    service = env.manager._service  # noqa: SLF001
    inside, release = threading.Event(), threading.Event()
    results: list[str] = []

    def slow_pull() -> None:
        original = service.pull

        def held(grant, payload):
            inside.set()
            release.wait(5)
            return original(grant, payload)

        service.pull = held
        try:
            reply = phone.signed(
                "/sync/pull", {"domain": "finance", "limit": 5}, verify_reply=False
            )
            results.append(f"pull:{reply.status}")
        finally:
            service.pull = original

    t = threading.Thread(target=slow_pull)
    t.start()
    assert inside.wait(5)
    revoker = threading.Thread(
        target=lambda: (env.manager.revoke(phone.device_id), results.append("revoked"))
    )
    revoker.start()
    revoker.join(0.3)
    assert revoker.is_alive(), "revoke waits for the admitted request"
    release.set()
    t.join(5)
    revoker.join(5)
    assert results == ["pull:200", "revoked"]
    _unauthorized(phone.signed("/sync/pull", {"domain": "finance", "limit": 5}, verify_reply=False))


def test_re_pairing_after_a_revoke_resets_the_cursors_and_resends_everything(env: Env) -> None:
    phone = _paired(env)
    env.add_account(env.pc_kernel())
    env.add_expense(env.pc_kernel(), "tx-pc-000001", -700)
    phone.pull()
    env.add_expense(phone.kernel, "tx-ph-000001", -800, account="acct-main-1")
    phone.push()
    (peer,) = env.pc_kernel().list_peers()
    assert peer.send_cursor > 0 and peer.recv_cursor > 0

    env.client.post(f"/v1/devices/{phone.device_id}/revoke", headers=env.headers)
    old_id = phone.device_id
    env.pair(phone)
    assert phone.device_id != old_id, "a re-pair is a new grant"
    (peer,) = env.pc_kernel().list_peers()
    assert peer.status == "active" and (peer.send_cursor, peer.recv_cursor) == (0, 0)
    (phone_peer,) = phone.kernel.list_peers()
    assert (phone_peer.send_cursor, phone_peer.recv_cursor) == (0, 0)

    reply, report = phone.pull()
    data = reply.json()
    assert data["cursor_from"] == 0 and data["count"] >= 2
    assert report.duplicates == data["count"] and report.applied == 0, (
        "the phone already held it all"
    )
    # And the revoked grant stays dead.
    _unauthorized(
        phone.signed(
            "/sync/pull", {"domain": "finance", "limit": 5}, device_id=old_id, verify_reply=False
        )
    )


# ---------------------------------------------------------------------------- scope and privacy


def test_a_request_for_another_domain_is_out_of_scope(env: Env) -> None:
    phone = _paired(env)
    for domain in ("memory", "health", "personal", ""):
        reply = phone.signed("/sync/pull", {"domain": domain, "limit": 5}, verify_reply=False)
        assert (reply.status, reply.json()["error"]) == (403, "out_of_scope")


def test_the_finance_sync_switch_is_enforced_on_send_and_receive(env: Env) -> None:
    phone = _paired(env)
    env.add_account(phone.kernel)
    env.client.patch("/v1/domains/finance/privacy", json={"sync": False}, headers=env.headers)
    pulled = phone.signed("/sync/pull", {"domain": "finance", "limit": 5}, verify_reply=False)
    assert (pulled.status, pulled.json()["error"]) == (403, "sync_disabled")
    batch = phone.kernel.sync_export(phone.pc_kernel_id, 10)
    pushed = phone.signed(
        "/sync/push",
        {
            "domain": "finance",
            "events_json": batch.events_json,
            "cursor_from": 0,
            "cursor_to": batch.cursor_to,
            "count": batch.count,
        },
        verify_reply=False,
    )
    assert (pushed.status, pushed.json()["error"]) == (403, "sync_disabled")
    assert env.pc_kernel().event_count() == 0

    env.client.patch("/v1/domains/finance/privacy", json={"sync": True}, headers=env.headers)
    assert phone.push().status == 200


def test_events_that_fail_kernel_verification_are_refused_whole(env: Env) -> None:
    phone = _paired(env)
    env.add_account(phone.kernel)
    batch = phone.kernel.sync_export(phone.pc_kernel_id, 10)
    events = json.loads(batch.events_json)
    events[0]["payload"]["name"] = "Tampered"
    reply = phone.signed(
        "/sync/push",
        {
            "domain": "finance",
            "events_json": json.dumps(events),
            "cursor_from": 0,
            "cursor_to": batch.cursor_to,
            "count": batch.count,
        },
        verify_reply=False,
    )
    assert (reply.status, reply.json()["error"]) == (403, "sync_rejected")
    assert env.pc_kernel().event_count() == 0


def test_an_ack_beyond_the_pcs_log_is_refused(env: Env) -> None:
    phone = _paired(env)
    reply = phone.signed("/sync/ack", {"domain": "finance", "cursor": 10_000}, verify_reply=False)
    assert (reply.status, reply.json()["error"]) == (422, "bad_request")


@pytest.mark.parametrize(
    "path, data",
    [
        ("/sync/pull", {"domain": "finance", "limit": 0}),
        ("/sync/pull", {"domain": "finance", "limit": 501}),
        ("/sync/pull", {"domain": "finance", "limit": "10"}),
        ("/sync/pull", {"domain": "finance", "limit": True}),
        ("/sync/ack", {"domain": "finance", "cursor": "1"}),
        ("/sync/ack", {"domain": "finance"}),
        (
            "/sync/push",
            {"domain": "finance", "events_json": 5, "cursor_from": 0, "cursor_to": 0, "count": 0},
        ),
        (
            "/sync/push",
            {
                "domain": "finance",
                "events_json": "[]",
                "cursor_from": 0,
                "cursor_to": 0,
                "count": -1,
            },
        ),
        (
            "/sync/push",
            {
                "domain": "finance",
                "events_json": "[]",
                "cursor_from": 3,
                "cursor_to": 1,
                "count": 0,
            },
        ),
    ],
)
def test_malformed_sync_bodies_are_refused(env: Env, path: str, data: dict) -> None:
    phone = _paired(env)
    reply = phone.signed(path, data, verify_reply=False)
    assert reply.status in (422, 400), (reply.status, reply.body)
    assert set(reply.json()) == {"error"}


def test_oversized_and_wrongly_typed_bodies_are_refused_before_parsing(env: Env) -> None:
    phone = _paired(env)
    huge = b'{"x":"' + b"a" * 9_700_000 + b'"}'
    now = str(int(env.clock[0]))
    admitted = {
        HEADER_DEVICE: phone.device_id or "",
        HEADER_TIMESTAMP: now,
        HEADER_NONCE: "h" * 22,
        HEADER_SIGNATURE: "AAAA",
    }
    # A known, active device may send up to 9 MB; beyond that is refused unread.
    assert phone.request("POST", "/sync/pull", huge, admitted).status == 413
    # A stranger never gets the gateway to buffer anything: refused on the headers alone.
    _unauthorized(phone.request("POST", "/sync/pull", huge))
    # Pairing callers are unauthenticated, so their bodies are tiny.
    assert phone.request("POST", "/pair/start", b'{"x":"' + b"a" * 20_000 + b'"}').status == 413
    assert (
        phone.request(
            "POST", "/sync/pull", b"{}", {**admitted, "Content-Type": "text/plain"}
        ).status
        == 415
    )
    assert phone.request("POST", "/sync/pull", b"[1,2]", admitted).status == 400
    assert phone.request("POST", "/sync/pull", b"not json", admitted).status == 400
    assert phone.request("POST", "/sync/pull", b"[" * 200_000, admitted).status == 400, (
        "deep nesting"
    )


def test_repeated_failures_from_one_address_are_rate_limited(env: Env) -> None:
    phone = _paired(env)
    statuses = [phone.post("/sync/pull", {"domain": "finance"}).status for _ in range(25)]
    assert statuses[:20] == [401] * 20 and set(statuses[20:]) == {429}
    env.clock[0] += 61
    assert phone.signed("/sync/pull", {"domain": "finance", "limit": 1}).status == 200


# ---------------------------------------------------------------------------- the security log


def test_denied_requests_are_logged_with_the_device_and_without_secrets(env: Env) -> None:
    phone = _paired(env)
    stamp = int(env.clock[0])
    phone.signed("/sync/pull", {"domain": "finance", "limit": 1}, nonce="a" * 22, timestamp=stamp)
    phone.signed(
        "/sync/pull",
        {"domain": "finance", "limit": 1},
        nonce="a" * 22,
        timestamp=stamp,
        verify_reply=False,
    )
    env.client.post(f"/v1/devices/{phone.device_id}/revoke", headers=env.headers)
    phone.signed("/sync/pull", {"domain": "finance", "limit": 1}, verify_reply=False)

    events = AuditRepository(env.lifecycle.connection).list_recent(100)
    denied = [e for e in events if e.action == "gateway_request_denied"]
    reasons = {e.metadata["reason"] for e in denied}
    assert {"replayed_request", "revoked_device"} <= reasons
    assert all(e.outcome == AuditOutcome.DENIED for e in denied)
    revoked = [e for e in denied if e.metadata["reason"] == "revoked_device"]
    assert revoked[0].actor_device_id == phone.device_id
    dump = json.dumps([e.model_dump(mode="json") for e in events])
    assert "signature" not in dump.lower() and env.lifecycle.local_token not in dump
