"""Pairing (AR-DATA-001, AR-DATA-003, AR-AND-007): QR + fingerprint + approval on the PC.

Wrong peer, machine in the middle, expired, replayed and guessed codes all fail closed, and a
refused pairing leaves no grant and no Kernel peer behind.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from reva_core.gateway import protocol
from reva_core.storage.repositories.audit_repository import AuditRepository
from tests.gateway.conftest import Env
from tests.gateway.phone import PinMismatch

SCHEMA = json.loads(
    Path(__file__)
    .resolve()
    .parents[2]
    .joinpath("contracts", "pairing-qr.schema.json")
    .read_text("utf-8")
)


def _devices(env: Env) -> list[dict]:
    return env.client.get("/v1/devices", headers=env.headers).json()["devices"]


def _approve(env: Env, digits: str):
    return env.client.post(
        "/v1/devices/pairing/approve", json={"fingerprint": digits}, headers=env.headers
    )


# ------------------------------------------------------------------------------------ happy path


def test_pairing_registers_the_phone_with_finance_scope_only(env: Env) -> None:
    env.enable()
    phone = env.new_phone("Pixel")
    device_id = env.pair(phone)

    (device,) = _devices(env)
    assert device["device_id"] == device_id and device["status"] == "active"
    assert device["scopes"] == ["finance"] and device["name"] == "Pixel"
    assert device["fingerprint"] == protocol.spki_sha256(phone.public)

    (peer,) = env.pc_kernel().list_peers()
    assert peer.device_id == phone.kernel.device_id()
    assert peer.scopes == ["finance"] and peer.status == "active"
    assert peer.fingerprint == protocol.spki_sha256(phone.public)


def test_the_qr_payload_follows_the_contract(env: Env) -> None:
    env.enable()
    opened = env.open_pairing()
    payload = protocol.parse_qr_text(opened["qr_text"])
    jsonschema.validate(payload, SCHEMA)
    assert payload["gw"] == env.manager.status()["tls_sha256"]
    assert (payload["host"], payload["port"]) == ("127.0.0.1", env.manager.status()["port"])
    assert payload["exp"] == opened["expires_at"] == int(env.clock[0]) + 120


def test_the_qr_contract_rejects_malformed_payloads() -> None:
    good = {
        "v": 1,
        "host": "192.168.1.5",
        "port": 47821,
        "code": "a" * 32,
        "gw": "0" * 64,
        "exp": 1,
    }
    jsonschema.validate(good, SCHEMA)
    for bad in (
        {**good, "extra": 1},
        {**good, "v": 2},
        {**good, "gw": "G" * 64},
        {**good, "code": "short"},
        {**good, "port": 0},
        {**good, "port": 70000},
        {k: v for k, v in good.items() if k != "gw"},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, SCHEMA)


def test_the_fingerprint_is_six_digits_and_bound_to_key_and_session() -> None:
    gw, key, other_key = "ab" * 32, b"phone-key-a", b"phone-key-b"
    first = protocol.fingerprint(gw, key, "session-1")
    assert len(first) == 6 and first.isdigit()
    assert first == protocol.fingerprint(gw, key, "session-1")
    assert first != protocol.fingerprint(gw, other_key, "session-1")
    assert first != protocol.fingerprint(gw, key, "session-2")
    assert first != protocol.fingerprint("cd" * 32, key, "session-1")


def test_the_pc_waits_for_the_user_nothing_is_granted_before_approval(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    started = phone.start_pairing(env.open_pairing()["qr_text"])
    session_id = started.json()["session_id"]
    pending = phone.poll_pairing(session_id)
    assert (pending.status, pending.json()) == (202, {"status": "pending"})
    assert _devices(env) == [] and env.pc_kernel().list_peers() == []
    view = env.pairing_view()
    assert view["state"] == "pending" and view["device_name"] == "Test phone"


def test_denying_ends_the_pairing_without_a_grant(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    session_id = phone.start_pairing(env.open_pairing()["qr_text"]).json()["session_id"]
    assert env.client.post("/v1/devices/pairing/deny", headers=env.headers).status_code == 200
    denied = phone.poll_pairing(session_id)
    assert (denied.status, denied.json()["error"]) == (403, "denied")
    assert _devices(env) == [] and env.pc_kernel().list_peers() == []


def test_approving_needs_the_digits_the_user_compared(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    phone.start_pairing(env.open_pairing()["qr_text"])
    shown = env.pairing_view()["fingerprint"]
    wrong = f"{(int(shown) + 1) % 1_000_000:06d}"
    refused = _approve(env, wrong)
    assert (refused.status_code, refused.json()["error"]) == (409, "fingerprint_mismatch")
    assert _devices(env) == []
    assert _approve(env, shown).status_code == 200
    assert _approve(env, shown).status_code == 409, "a second approval has nothing to approve"


def test_approving_with_nothing_pending_is_refused(env: Env) -> None:
    env.enable()
    reply = _approve(env, "123456")
    assert (reply.status_code, reply.json()["error"]) == (409, "nothing_to_approve")
    env.open_pairing()
    assert _approve(env, "123456").status_code == 409, "an open QR with no phone yet"


def test_fingerprint_must_be_six_digits_in_the_request(env: Env) -> None:
    env.enable()
    for bad in ("12345", "1234567", "abcdef", ""):
        assert _approve(env, bad).status_code == 422


# ------------------------------------------------------------ wrong peer / machine in the middle


def test_a_phone_refuses_a_gateway_whose_tls_key_is_not_in_the_qr(env: Env, other_env: Env) -> None:
    env.enable()
    other_env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    phone.point_at(qr)
    # The attacker's listener answers where the real gateway should be.
    phone.port = other_env.manager.status()["port"]
    with pytest.raises(PinMismatch):
        phone.post("/pair/start", {"code": "x" * 32})
    assert other_env.manager.status()["pairing"] is None, "the attacker never saw the code"


def test_a_man_in_the_middle_who_swaps_the_phone_key_is_caught_by_the_digits(env: Env) -> None:
    env.enable()
    honest, mallory = env.new_phone("Honest"), env.new_phone("Mallory")
    qr = env.open_pairing()["qr_text"]
    # Mallory relays the code to the PC with her own key, hoping the user approves.
    session_id = mallory.start_pairing(qr).json()["session_id"]
    shown_on_pc = env.pairing_view()["fingerprint"]
    on_honest_phone = honest.expected_fingerprint(session_id)
    assert shown_on_pc != on_honest_phone, "the two screens disagree, so the user says no"
    assert _approve(env, on_honest_phone).status_code == 409
    assert _devices(env) == [] and env.pc_kernel().list_peers() == []


def test_proof_of_key_possession_is_required(env: Env) -> None:
    env.enable()
    victim, attacker = env.new_phone("Victim"), env.new_phone("Attacker")
    qr = env.open_pairing()["qr_text"]
    payload = attacker.point_at(qr)
    # The attacker offers the victim's public key but can only sign with her own.
    reply = attacker.start_pairing(qr, public_key=protocol.b64u(victim.public))
    assert (reply.status, reply.json()["error"]) == (403, "bad_proof")
    assert payload["code"] and env.pairing_view()["state"] == "open"


def test_a_phone_cannot_claim_another_devices_kernel_identity(env: Env) -> None:
    env.enable()
    honest, thief = env.new_phone("Honest"), env.new_phone("Thief")
    env.pair(honest)
    qr = env.open_pairing()["qr_text"]
    started = thief.start_pairing(qr, kernel_devices={"finance": honest.kernel.device_id()})
    assert started.status == 200
    refused = _approve(env, env.pairing_view()["fingerprint"])
    assert (refused.status_code, refused.json()["error"]) == (409, "kernel_refused")
    devices = _devices(env)
    assert [d["name"] for d in devices] == ["Honest"], "no grant was left behind for the thief"
    (peer,) = env.pc_kernel().list_peers()
    assert peer.fingerprint == protocol.spki_sha256(honest.public), "the honest key still stands"


@pytest.mark.parametrize(
    "override, error",
    [
        ({"public_key": "AAAA"}, "bad_public_key"),
        ({"name": ""}, "bad_device_name"),
        ({"name": "x" * 81}, "bad_device_name"),
        ({"platform": "windows"}, "bad_platform"),
        ({"kernel_devices": {}}, "bad_kernel_devices"),
        ({"kernel_devices": {"finance": "short"}}, "bad_kernel_devices"),
        (
            {"kernel_devices": {"finance": "ok-device-id-1", "health": "ok-device-id-2"}},
            "bad_kernel_devices",
        ),
    ],
)
def test_malformed_phone_details_are_refused(env: Env, override: dict, error: str) -> None:
    env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    if "public_key" in override:
        # A key that is not P-256 also cannot have signed anything.
        reply = phone.start_pairing(qr, **override)
        assert reply.status in (403, 422)
        return
    reply = phone.start_pairing(qr, **override)
    assert reply.status == 422 and reply.json()["error"] == error


# --------------------------------------------------------------- expired, replayed, guessed codes


def test_an_expired_code_is_refused(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    env.clock[0] += 121
    reply = phone.start_pairing(qr)
    assert (reply.status, reply.json()["error"]) == (410, "code_expired")
    assert env.pairing_view()["state"] == "expired" and _devices(env) == []


def test_a_code_is_good_up_to_its_deadline(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    env.clock[0] += 119
    assert phone.start_pairing(qr).status == 200


def test_waiting_too_long_to_approve_expires_the_pairing(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    session_id = phone.start_pairing(env.open_pairing()["qr_text"]).json()["session_id"]
    shown = env.pairing_view()["fingerprint"]
    env.clock[0] += 121
    assert _approve(env, shown).status_code == 409
    gone = phone.poll_pairing(session_id)
    assert (gone.status, gone.json()["error"]) == (410, "code_expired")
    assert _devices(env) == []


def test_a_code_works_once_a_replay_is_refused(env: Env) -> None:
    env.enable()
    phone, other = env.new_phone(), env.new_phone("Other")
    qr = env.open_pairing()["qr_text"]
    assert phone.start_pairing(qr).status == 200
    again = phone.start_pairing(qr)
    assert (again.status, again.json()["error"]) == (409, "code_used")
    stolen = other.start_pairing(qr)
    assert (stolen.status, stolen.json()["error"]) == (409, "code_used")
    assert env.pairing_view()["device_name"] == "Test phone", (
        "the first phone is still the one waiting"
    )


def test_a_code_cannot_be_reused_after_the_pairing_finished(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    session_id = phone.start_pairing(qr).json()["session_id"]
    _approve(env, env.pairing_view()["fingerprint"])
    phone.poll_pairing(session_id)
    replay = env.new_phone("Late").start_pairing(qr)
    assert (replay.status, replay.json()["error"]) == (409, "code_used")
    assert len(_devices(env)) == 1


def test_opening_a_new_pairing_cancels_the_old_code(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    old = env.open_pairing()["qr_text"]
    env.open_pairing()
    reply = phone.start_pairing(old)
    assert (reply.status, reply.json()["error"]) == (403, "code_invalid")


def test_guessing_codes_locks_the_session(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    statuses = [phone.start_pairing(qr, code=f"{'g' * 21}{i}").status for i in range(5)]
    assert statuses == [403, 403, 403, 403, 429]
    # Even the right code is dead now; the user must open a new pairing.
    locked = phone.start_pairing(qr)
    assert (locked.status, locked.json()["error"]) == (429, "locked")
    assert env.pairing_view()["state"] == "locked"
    fresh = env.open_pairing()["qr_text"]
    assert phone.start_pairing(fresh).status == 200


def test_starting_without_an_open_pairing_is_refused(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    env.client.post("/v1/devices/pairing/deny", headers=env.headers)
    reply = phone.start_pairing(qr)
    assert reply.status == 403 and reply.json()["error"] == "no_open_pairing"


def test_polling_needs_the_phone_key_and_a_fresh_nonce(env: Env) -> None:
    env.enable()
    phone, snoop = env.new_phone(), env.new_phone("Snoop")
    started = phone.start_pairing(env.open_pairing()["qr_text"])
    session_id = started.json()["session_id"]
    snoop.host, snoop.port, snoop.gateway_sha256 = phone.host, phone.port, phone.gateway_sha256
    forged = snoop.poll_pairing(session_id)
    assert (forged.status, forged.json()["error"]) == (403, "bad_proof")
    assert phone.poll_pairing(session_id, nonce="n" * 22).status == 202
    replay = phone.poll_pairing(session_id, nonce="n" * 22)
    assert (replay.status, replay.json()["error"]) == (409, "replayed")
    assert phone.poll_pairing("no-such-session").status == 404


def test_pairing_activity_is_in_the_security_log_without_secrets(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    qr = env.open_pairing()["qr_text"]
    code = protocol.parse_qr_text(qr)["code"]
    env.pair(env.new_phone("Second"))
    log = json.dumps(
        [
            e.model_dump(mode="json")
            for e in AuditRepository(env.lifecycle.connection).list_recent(100)
        ]
    )
    for action in ("gateway_enabled", "pairing_opened", "device_pairing_approved"):
        assert action in log
    assert code not in log and protocol.b64u(phone.public) not in log


def test_two_phones_racing_for_one_code_cannot_both_win(env: Env) -> None:
    import threading

    env.enable()
    qr = env.open_pairing()["qr_text"]
    phones = [env.new_phone(f"Racer {i}") for i in range(6)]
    results: list[int] = []
    gate = threading.Barrier(len(phones))

    def go(phone) -> None:
        gate.wait()
        results.append(phone.start_pairing(qr).status)

    threads = [threading.Thread(target=go, args=(p,)) for p in phones]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert sorted(results) == [200] + [409] * 5, results
