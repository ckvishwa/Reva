"""Sync through the real gateway: two Kernels, signed events over pinned TLS (AR-DATA-010/011/015).

The same scenarios the hardware check will run by hand: an expense on each side while apart,
reconnect, both match; a delete beats an offline edit; revoke and the next sync fails.
"""

from __future__ import annotations

import json

from tests.gateway.conftest import Env


def _tx_ids(handle) -> list[str]:
    out = handle.query("list_transactions", "{}")
    return sorted(row["id"] for row in json.loads(out.rows_json))


def _amount(handle, ident: str) -> int:
    out = json.loads(
        handle.query("get", json.dumps({"aggregate_type": "transaction", "id": ident})).rows_json
    )
    return int(out[0]["amount_minor"])


def _sync(phone) -> None:
    assert phone.push().status == 200
    reply, _ = phone.pull()
    assert reply.status == 200


def test_an_expense_added_on_each_side_while_apart_ends_up_on_both(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    env.pair(phone)
    env.add_account(env.pc_kernel())
    _sync(phone)

    env.add_expense(env.pc_kernel(), "tx-pc-000001", -1250)
    env.add_expense(phone.kernel, "tx-phone-0001", -4300)
    _sync(phone)

    assert _tx_ids(env.pc_kernel()) == _tx_ids(phone.kernel) == ["tx-pc-000001", "tx-phone-0001"]
    assert env.pc_kernel().projection_digest() == phone.kernel.projection_digest()
    # A second round has nothing left to say.
    reply, report = phone.pull()
    assert reply.json()["count"] == 0 and report.applied == 0


def test_the_phone_resumes_from_its_cursor_after_a_dropped_connection(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    env.pair(phone)
    env.add_account(env.pc_kernel())
    for i in range(3):
        env.add_expense(env.pc_kernel(), f"tx-pc-00000{i}", -100 * (i + 1))
    first = phone.signed("/sync/pull", {"domain": "finance", "limit": 2}).json()
    assert first["count"] == 2
    # No ack arrived: the PC offers the same events again, from the same cursor.
    again = phone.signed("/sync/pull", {"domain": "finance", "limit": 2}).json()
    assert (again["cursor_from"], again["events_json"]) == (
        first["cursor_from"],
        first["events_json"],
    )
    reply, report = phone.pull(limit=500)
    assert reply.status == 200 and report.applied + report.duplicates == 4
    assert phone.kernel.projection_digest() == env.pc_kernel().projection_digest()


def test_a_delete_on_the_pc_beats_an_offline_edit_on_the_phone_ac_018(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    env.pair(phone)
    env.add_account(env.pc_kernel())
    env.add_expense(env.pc_kernel(), "tx-shared-001", -5000)
    _sync(phone)

    for amount in (-5100, -5200, -5300):  # the phone's clock runs ahead while it is offline
        phone.kernel.command(
            "transaction.update", json.dumps({"id": "tx-shared-001", "amount_minor": amount})
        )
    env.pc_kernel().command("transaction.delete", json.dumps({"id": "tx-shared-001"}))
    _sync(phone)
    _sync(phone)

    assert _tx_ids(env.pc_kernel()) == [] and _tx_ids(phone.kernel) == []
    assert env.pc_kernel().projection_digest() == phone.kernel.projection_digest()


def test_conflicting_amount_edits_are_reported_on_both_sides(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    env.pair(phone)
    env.add_account(env.pc_kernel())
    env.add_expense(env.pc_kernel(), "tx-shared-001", -5000)
    _sync(phone)

    env.pc_kernel().command(
        "transaction.update", json.dumps({"id": "tx-shared-001", "amount_minor": -1111})
    )
    phone.kernel.command(
        "transaction.update", json.dumps({"id": "tx-shared-001", "amount_minor": -2222})
    )

    pushed = phone.push()
    assert [c["field"] for c in pushed.json()["conflicts"]] == ["amount_minor"], "the PC is told"
    reply, report = phone.pull()
    assert reply.status == 200 and len(report.conflicts) == 1, "and so is the phone"
    assert _amount(env.pc_kernel(), "tx-shared-001") == _amount(phone.kernel, "tx-shared-001")
    listed = env.client.get("/v1/domains/finance/conflicts", headers=env.headers).json()["items"]
    assert len(listed) == 1


def test_sync_stops_for_a_revoked_phone_and_the_data_already_synced_stays(env: Env) -> None:
    env.enable()
    phone = env.new_phone()
    env.pair(phone)
    env.add_account(env.pc_kernel())
    _sync(phone)
    env.client.post(f"/v1/devices/{phone.device_id}/revoke", headers=env.headers)
    env.add_expense(env.pc_kernel(), "tx-pc-000001", -100)
    env.add_expense(phone.kernel, "tx-phone-0001", -200)
    assert phone.push().status == 401
    assert phone.pull()[0].status == 401
    assert _tx_ids(env.pc_kernel()) == ["tx-pc-000001"], "the phone's expense never reached the PC"
    assert _tx_ids(phone.kernel) == ["tx-phone-0001"], "and the PC's never reached the phone"
    assert len(json.loads(env.pc_kernel().query("list_accounts", "{}").rows_json)) == 1


# ------------------------------------------------------------------------- third-device forwarding


def test_a_second_phone_gets_the_first_phones_events_and_its_key_in_one_response(env: Env) -> None:
    env.enable()
    one, two = env.new_phone("One"), env.new_phone("Two")
    env.pair(one)
    env.pair(two)
    env.add_account(env.pc_kernel())
    _sync(one)
    _sync(two)
    env.add_expense(one.kernel, "tx-one-000001", -900)
    assert one.push().status == 200

    reply = two.signed("/sync/pull", {"domain": "finance", "limit": 500})
    data = reply.json()
    origins = {e["origin_device_id"] for e in json.loads(data["events_json"])}
    assert origins == {one.kernel.device_id()}
    assert [d["device_id"] for d in data["directory"]] == [one.kernel.device_id()]
    assert data["withheld"] == 0

    reply, report = two.pull()
    assert report is not None and _tx_ids(two.kernel) == ["tx-one-000001"]
    assert two.kernel.projection_digest() == env.pc_kernel().projection_digest()


def test_a_phone_is_never_sent_events_from_a_device_it_was_not_told_about(env: Env) -> None:
    env.enable()
    one, two = env.new_phone("One"), env.new_phone("Two")
    env.pair(one)
    env.pair(two)
    env.add_account(env.pc_kernel())
    _sync(one)
    _sync(two)
    env.add_expense(one.kernel, "tx-one-000001", -900)
    assert one.push().status == 200
    env.client.post(f"/v1/devices/{one.device_id}/revoke", headers=env.headers)

    data = two.signed("/sync/pull", {"domain": "finance", "limit": 500}).json()
    assert data["count"] == 0 and data["withheld"] == 1 and data["directory"] == []
    # Phone two's batch is complete and valid; it just does not carry the revoked phone's event.
    reply, report = two.pull()
    assert reply.status == 200 and report.applied == 0
    assert _tx_ids(two.kernel) == []
    assert _tx_ids(env.pc_kernel()) == ["tx-one-000001"], "the PC keeps what it already accepted"


def test_the_directory_only_lists_active_finance_grants_and_never_the_requester(env: Env) -> None:
    env.enable()
    one, two = env.new_phone("One"), env.new_phone("Two")
    env.pair(one)
    env.pair(two)
    env.add_account(one.kernel)
    assert one.push().status == 200
    own = one.signed("/sync/pull", {"domain": "finance", "limit": 500}).json()
    assert own["directory"] == [], "a phone is never told about itself"
    other = two.signed("/sync/pull", {"domain": "finance", "limit": 500}).json()
    assert {d["label"] for d in other["directory"]} == {"One"}
