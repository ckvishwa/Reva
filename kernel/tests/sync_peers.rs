//! Signed LAN sync between paired devices (AR-DATA-010/011/015, AR-DOM-008, AC-008, AC-018).
//! Every test uses throw-away directories and in-memory keys; nothing touches real data.

mod common;

use std::sync::Arc;

use common::{cmd, code, open, rows, MemKeys};
use p256::ecdsa::signature::Signer;
use p256::ecdsa::{Signature, SigningKey};
use p256::pkcs8::EncodePublicKey;
use reva_kernel::{DeviceSigner, DomainHandle, SignerError, SyncBatch};
use serde_json::{json, Value};

struct TestSigner {
    key: SigningKey,
    /// When set, `sign` returns garbage, like a broken Keystore wrapper would.
    broken: bool,
}

impl TestSigner {
    fn new(seed: u8) -> Arc<TestSigner> {
        Arc::new(TestSigner { key: SigningKey::from_slice(&[seed; 32]).unwrap(), broken: false })
    }
    fn public(&self) -> Vec<u8> {
        self.key.verifying_key().to_public_key_der().unwrap().as_bytes().to_vec()
    }
}

impl DeviceSigner for TestSigner {
    fn public_key(&self) -> Result<Vec<u8>, SignerError> {
        Ok(self.public())
    }
    fn sign(&self, message: Vec<u8>) -> Result<Vec<u8>, SignerError> {
        if self.broken {
            return Ok(vec![0x30, 0x00]);
        }
        let signature: Signature = self.key.sign(&message);
        Ok(signature.to_der().as_bytes().to_vec())
    }
}

struct Device {
    _dir: tempfile::TempDir,
    handle: Arc<DomainHandle>,
    signer: Arc<TestSigner>,
}

impl Device {
    fn new(seed: u8) -> Device {
        let dir = tempfile::tempdir().unwrap();
        let handle = open(dir.path(), &MemKeys::new()).unwrap();
        let signer = TestSigner::new(seed);
        handle.set_signer(signer.clone());
        Device { _dir: dir, handle, signer }
    }
    fn id(&self) -> String {
        self.handle.device_id()
    }
    fn trust(&self, other: &Device) {
        self.handle
            .register_peer(other.id(), other.signer.public(), "Test device".into(), vec!["finance".into()])
            .unwrap();
    }
    /// One full exchange in each direction, like the transport would do after the user pairs.
    fn exchange(&self, other: &Device) -> (reva_kernel::ApplyReport, reva_kernel::ApplyReport) {
        let to_other = self.push(other);
        let to_self = other.push(self);
        (to_other, to_self)
    }
    /// Export from `self`, apply on `other`, then acknowledge the cursor.
    fn push(&self, other: &Device) -> reva_kernel::ApplyReport {
        let batch = self.handle.sync_export(other.id(), 500).unwrap();
        let report = other.handle.sync_apply(self.id(), batch.clone()).unwrap();
        self.handle.sync_ack(other.id(), batch.cursor_to).unwrap();
        report
    }
}

fn pair() -> (Device, Device) {
    let (a, b) = (Device::new(1), Device::new(2));
    a.trust(&b);
    b.trust(&a);
    (a, b)
}

fn seed(h: &DomainHandle) {
    cmd(h, "account.create", json!({"id": "acct-main-1", "name": "Main", "currency": "USD"}));
    cmd(
        h,
        "transaction.create",
        json!({"id": "tx-shared-1", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -5000, "description": "Shared"}),
    );
}

fn events_of(batch: &SyncBatch) -> Vec<Value> {
    serde_json::from_str(&batch.events_json).unwrap()
}

fn with_events(batch: &SyncBatch, events: Vec<Value>) -> SyncBatch {
    SyncBatch { events_json: Value::Array(events).to_string(), count: 0, ..batch.clone() }
}

fn tx_count(h: &DomainHandle) -> usize {
    rows(h, "list_transactions", json!({})).len()
}

// ---------------------------------------------------------------- the happy path

#[test]
fn signed_events_replicate_and_both_devices_end_identical() {
    let (a, b) = pair();
    seed(&a.handle);
    cmd(&b.handle, "account.create", json!({"id": "acct-b-0001", "name": "Phone cash", "currency": "USD"}));
    let (to_b, to_a) = a.exchange(&b);
    assert_eq!(to_b.applied, 2, "account + transaction");
    assert_eq!(to_a.applied, 1);
    assert_eq!(a.handle.projection_digest().unwrap(), b.handle.projection_digest().unwrap());
    assert_eq!(rows(&b.handle, "list_transactions", json!({}))[0]["amount_minor"], -5000);
}

#[test]
fn exported_events_carry_a_device_signature_not_the_local_tag() {
    let (a, b) = pair();
    seed(&a.handle);
    let batch = a.handle.sync_export(b.id(), 500).unwrap();
    for event in events_of(&batch) {
        let sig = event["signature"].as_str().unwrap();
        assert!(sig.starts_with("es256:"), "{sig}");
    }
}

// ---------------------------------------------------------------- who may talk (AR-DATA-001/003/004/015)

#[test]
fn an_unpaired_device_cannot_send_or_receive() {
    let (a, _b) = pair();
    let stranger = Device::new(9);
    seed(&a.handle);
    let err = a.handle.sync_export(stranger.id(), 10).unwrap_err();
    assert_eq!(code(&err), "rejected");
    let mut batch = SyncBatch { events_json: "[]".into(), cursor_from: 0, cursor_to: 0, count: 0 };
    batch.events_json = "[]".into();
    let err = a.handle.sync_apply(stranger.id(), batch).unwrap_err();
    assert_eq!(code(&err), "rejected");
}

#[test]
fn a_wrong_peer_signing_with_another_key_is_rejected_and_nothing_applies() {
    let (a, b) = pair();
    let mallory = Device::new(7);
    // Mallory claims to be A: she copies A's device id but holds a different key.
    cmd(&mallory.handle, "account.create", json!({"id": "acct-evil-01", "name": "Evil", "currency": "USD"}));
    mallory.trust(&b);
    let forged = mallory.handle.sync_export(b.id(), 10).unwrap();
    let mut events = events_of(&forged);
    for e in &mut events {
        e["origin_device_id"] = json!(a.id());
    }
    let err = b.handle.sync_apply(a.id(), with_events(&forged, events)).unwrap_err();
    assert_eq!(code(&err), "rejected");
    assert!(rows(&b.handle, "account_balances", json!({})).is_empty());
}

#[test]
fn a_tampered_event_fails_verification() {
    let (a, b) = pair();
    seed(&a.handle);
    let batch = a.handle.sync_export(b.id(), 500).unwrap();
    let mut events = events_of(&batch);
    let tx = events.iter_mut().find(|e| e["aggregate_type"] == "transaction").unwrap();
    tx["payload"]["amount_minor"] = json!(-1);
    let err = b.handle.sync_apply(a.id(), with_events(&batch, events)).unwrap_err();
    assert_eq!(code(&err), "rejected");
    assert_eq!(tx_count(&b.handle), 0);
}

#[test]
fn unsigned_and_locally_tagged_events_are_rejected() {
    let (a, b) = pair();
    seed(&a.handle);
    let local = a.handle.pending_events(100).unwrap(); // carries only the local integrity tag
    let batch =
        SyncBatch { events_json: local.events_json, cursor_from: 0, cursor_to: local.cursor, count: local.count };
    let err = b.handle.sync_apply(a.id(), batch.clone()).unwrap_err();
    assert_eq!(code(&err), "rejected");

    let mut events = events_of(&batch);
    for e in &mut events {
        e["signature"] = json!("");
    }
    let err = b.handle.sync_apply(a.id(), with_events(&batch, events)).unwrap_err();
    assert!(matches!(code(&err), "rejected" | "validation"), "{err}");
    assert_eq!(b.handle.event_count().unwrap(), 0);
}

#[test]
fn one_bad_event_rejects_the_whole_batch() {
    let (a, b) = pair();
    seed(&a.handle);
    let batch = a.handle.sync_export(b.id(), 500).unwrap();
    let mut events = events_of(&batch);
    let last = events.len() - 1;
    events[last]["signature"] = json!("es256:3006020100020100");
    let err = b.handle.sync_apply(a.id(), with_events(&batch, events)).unwrap_err();
    assert_eq!(code(&err), "rejected");
    assert_eq!(b.handle.event_count().unwrap(), 0, "no event of a rejected batch is kept");
}

#[test]
fn a_peer_cannot_inject_events_in_our_name() {
    let (a, b) = pair();
    seed(&b.handle);
    // A sends a batch whose events claim B (the receiver) as origin, with A's valid signature scheme.
    let batch = a.handle.sync_export(b.id(), 10).unwrap();
    let forged = json!({
        "event_schema": "1.0", "event_id": "forged-event-0001", "domain": "finance", "aggregate_type": "account",
        "aggregate_id": "acct-forge-01", "version": 1, "origin_device_id": b.id(), "lamport": 5,
        "kind": "account.created", "created_at": "2026-10-12T00:00:00Z", "tombstone": false,
        "payload": {"name": "Forged", "currency": "USD"}, "signature": "es256:3006020100020100"
    });
    let err = b.handle.sync_apply(a.id(), with_events(&batch, vec![forged])).unwrap_err();
    assert_eq!(code(&err), "rejected");
}

#[test]
fn revoking_a_device_stops_sync_in_both_directions_at_once() {
    let (a, b) = pair();
    seed(&a.handle);
    a.push(&b);
    cmd(&a.handle, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -7000}));
    let pending = a.handle.sync_export(b.id(), 500).unwrap();

    b.handle.revoke_peer(a.id()).unwrap();
    let err = b.handle.sync_apply(a.id(), pending).unwrap_err();
    assert_eq!(code(&err), "rejected");
    assert_eq!(
        rows(&b.handle, "list_transactions", json!({}))[0]["amount_minor"],
        -5000,
        "revoked device changes nothing"
    );
    assert_eq!(code(&b.handle.sync_export(a.id(), 10).unwrap_err()), "rejected");

    a.handle.revoke_peer(b.id()).unwrap();
    assert_eq!(code(&a.handle.sync_export(b.id(), 10).unwrap_err()), "rejected");
    assert_eq!(code(&a.handle.sync_ack(b.id(), 1).unwrap_err()), "rejected");
    let peers = a.handle.list_peers().unwrap();
    assert_eq!(peers[0].status, "revoked");
    assert!(peers[0].revoked_at.is_some());
}

#[test]
fn a_revoked_device_stays_out_even_with_old_valid_batches() {
    let (a, b) = pair();
    seed(&a.handle);
    let old = a.handle.sync_export(b.id(), 500).unwrap();
    b.handle.revoke_peer(a.id()).unwrap();
    let err = b.handle.sync_apply(a.id(), old).unwrap_err();
    assert_eq!(code(&err), "rejected");
    assert_eq!(b.handle.event_count().unwrap(), 0);
}

#[test]
fn re_pairing_after_revocation_is_possible_but_a_key_swap_is_not() {
    let (a, b) = pair();
    let imposter = Device::new(8);
    let err =
        a.handle.register_peer(b.id(), imposter.signer.public(), "Phone".into(), vec!["finance".into()]).unwrap_err();
    assert_eq!(code(&err), "rejected", "an active device's key cannot be replaced silently");

    a.handle.revoke_peer(b.id()).unwrap();
    a.trust(&b);
    assert_eq!(a.handle.list_peers().unwrap()[0].status, "active");
    seed(&a.handle);
    a.push(&b);
    assert_eq!(tx_count(&b.handle), 1);
}

#[test]
fn re_pairing_a_revoked_device_resets_both_cursors_and_resends_everything() {
    let (a, b) = pair();
    seed(&a.handle);
    a.push(&b);
    b.push(&a);
    let before = &a.handle.list_peers().unwrap()[0];
    assert!(before.send_cursor > 0 && before.recv_cursor > 0, "{before:?}");

    a.handle.revoke_peer(b.id()).unwrap();
    assert!(a.handle.list_peers().unwrap()[0].send_cursor > 0, "revoking alone keeps the cursors");
    a.trust(&b);
    let after = &a.handle.list_peers().unwrap()[0];
    assert_eq!((after.send_cursor, after.recv_cursor), (0, 0));
    let batch = a.handle.sync_export(b.id(), 500).unwrap();
    assert_eq!((batch.cursor_from, batch.count), (0, 2), "the whole log is offered again");
    // The peer already holds it all: replaying is harmless.
    let report = b.handle.sync_apply(a.id(), batch).unwrap();
    assert_eq!((report.applied, report.duplicates), (0, 2));
}

#[test]
fn cursors_can_be_reset_explicitly_for_a_paired_peer() {
    let (a, b) = pair();
    seed(&a.handle);
    a.push(&b);
    a.handle.reset_peer_cursors(b.id()).unwrap();
    assert_eq!(a.handle.list_peers().unwrap()[0].send_cursor, 0);
    assert_eq!(code(&a.handle.reset_peer_cursors("unknown-device-1".into()).unwrap_err()), "not_found");
}

#[test]
fn registering_peers_validates_ids_keys_and_scopes() {
    let a = Device::new(1);
    let key = TestSigner::new(2).public();
    let reg = |id: &str, key: Vec<u8>, scopes: Vec<&str>| {
        a.handle.register_peer(id.to_string(), key, "Phone".into(), scopes.into_iter().map(String::from).collect())
    };
    assert_eq!(code(&reg("short", key.clone(), vec!["finance"]).unwrap_err()), "validation");
    assert_eq!(code(&reg(&a.id(), key.clone(), vec!["finance"]).unwrap_err()), "validation");
    assert_eq!(code(&reg("bad id with spaces", key.clone(), vec!["finance"]).unwrap_err()), "validation");
    assert_eq!(code(&reg("device-phone-1", vec![1, 2, 3], vec!["finance"]).unwrap_err()), "validation");
    assert_eq!(code(&reg("device-phone-1", key.clone(), vec![]).unwrap_err()), "validation");
    assert_eq!(code(&reg("device-phone-1", key.clone(), vec!["memory"]).unwrap_err()), "validation");
    assert_eq!(code(&reg("device-phone-1", key.clone(), vec!["finance", "bank"]).unwrap_err()), "validation");
    reg("device-phone-1", key, vec!["finance"]).unwrap();
    let peers = a.handle.list_peers().unwrap();
    assert_eq!(peers[0].fingerprint.len(), 64);
    assert_eq!(peers[0].scopes, vec!["finance".to_string()]);
}

// ---------------------------------------------------------------- replay, duplicates, reorder (AR-DATA-010)

#[test]
fn replaying_a_batch_changes_nothing() {
    let (a, b) = pair();
    seed(&a.handle);
    let batch = a.handle.sync_export(b.id(), 500).unwrap();
    let first = b.handle.sync_apply(a.id(), batch.clone()).unwrap();
    let digest = b.handle.projection_digest().unwrap();
    let count = b.handle.event_count().unwrap();
    for _ in 0..3 {
        let again = b.handle.sync_apply(a.id(), batch.clone()).unwrap();
        assert_eq!(again.applied, 0);
        assert_eq!(again.duplicates, first.applied);
    }
    assert_eq!(b.handle.projection_digest().unwrap(), digest);
    assert_eq!(b.handle.event_count().unwrap(), count);
}

#[test]
fn batches_arriving_in_any_order_and_twice_give_the_same_state() {
    let (a, b) = pair();
    let c = Device::new(3);
    c.trust(&a);
    a.trust(&c);
    seed(&a.handle);
    let mut batches = Vec::new();
    for amount in [-6000, -6500, -7000] {
        batches.push(a.handle.sync_export(b.id(), 500).unwrap());
        let cursor = batches.last().unwrap().cursor_to;
        a.handle.sync_ack(b.id(), cursor).unwrap();
        cmd(&a.handle, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": amount}));
    }
    batches.push(a.handle.sync_export(b.id(), 500).unwrap());

    for batch in &batches {
        b.handle.sync_apply(a.id(), batch.clone()).unwrap();
    }
    for batch in batches.iter().rev().chain(batches.iter()) {
        c.handle.sync_apply(a.id(), batch.clone()).unwrap();
    }
    assert_eq!(a.handle.projection_digest().unwrap(), b.handle.projection_digest().unwrap());
    assert_eq!(a.handle.projection_digest().unwrap(), c.handle.projection_digest().unwrap());
    assert_eq!(rows(&c.handle, "list_transactions", json!({}))[0]["amount_minor"], -7000);
}

#[test]
fn a_batch_that_overlaps_an_earlier_one_applies_each_event_once() {
    let (a, b) = pair();
    seed(&a.handle);
    let first = a.handle.sync_export(b.id(), 2).unwrap();
    b.handle.sync_apply(a.id(), first.clone()).unwrap();
    // The ack was lost: A re-sends from the old cursor, now with everything.
    let all = a.handle.sync_export(b.id(), 500).unwrap();
    assert_eq!(all.cursor_from, first.cursor_from);
    let report = b.handle.sync_apply(a.id(), all.clone()).unwrap();
    assert_eq!(report.duplicates, first.count);
    assert_eq!(report.applied + report.duplicates, all.count);
    assert_eq!(a.handle.projection_digest().unwrap(), b.handle.projection_digest().unwrap());
}

// ---------------------------------------------------------------- cursors (outbox acknowledgment)

#[test]
fn cursors_advance_only_on_ack_and_only_forward() {
    let (a, b) = pair();
    seed(&a.handle);
    let first = a.handle.sync_export(b.id(), 1).unwrap();
    assert_eq!((first.cursor_from, first.count), (0, 1));
    // Without an ack the same events are offered again.
    assert_eq!(a.handle.sync_export(b.id(), 1).unwrap().cursor_to, first.cursor_to);

    a.handle.sync_ack(b.id(), first.cursor_to).unwrap();
    let second = a.handle.sync_export(b.id(), 500).unwrap();
    assert_eq!(second.cursor_from, first.cursor_to);

    a.handle.sync_ack(b.id(), second.cursor_to).unwrap();
    a.handle.sync_ack(b.id(), first.cursor_to).unwrap(); // a late, older ack is harmless
    assert_eq!(a.handle.list_peers().unwrap()[0].send_cursor, second.cursor_to);
    assert_eq!(a.handle.sync_export(b.id(), 500).unwrap().count, 0, "nothing left to send");

    let err = a.handle.sync_ack(b.id(), 10_000).unwrap_err();
    assert_eq!(code(&err), "validation", "an ack cannot reach past our own log");
}

#[test]
fn a_peer_never_receives_its_own_events_back() {
    let (a, b) = pair();
    seed(&a.handle);
    a.push(&b);
    let back = b.handle.sync_export(a.id(), 500).unwrap();
    assert_eq!(back.count, 0);
    assert!(back.cursor_to > 0, "the cursor still moves past the skipped events");
}

#[test]
fn acknowledged_events_leave_the_durable_outbox() {
    let (a, b) = pair();
    seed(&a.handle);
    assert_eq!(a.handle.pending_events(100).unwrap().count, 2);
    a.push(&b);
    assert_eq!(a.handle.pending_events(100).unwrap().count, 0);
}

#[test]
fn a_hub_forwards_signed_events_between_two_phones() {
    let (pc, phone1) = pair();
    let phone2 = Device::new(3);
    pc.trust(&phone2);
    phone2.trust(&pc);
    // Phone 2 must also trust phone 1's key to verify its forwarded events.
    phone2.trust(&phone1);
    cmd(&phone1.handle, "account.create", json!({"id": "acct-p1-001", "name": "Phone 1", "currency": "USD"}));
    phone1.push(&pc);
    pc.push(&phone2);
    assert_eq!(rows(&phone2.handle, "account_balances", json!({})).len(), 1);
    let events = events_of(&pc.handle.sync_export(phone2.id(), 500).unwrap());
    assert!(events.iter().all(|e| e["origin_device_id"] != json!(phone2.id())));
}

// ---------------------------------------------------------------- tombstones (AR-DATA-011, AC-008, AC-018)

#[test]
fn offline_delete_beats_an_edit_made_on_the_other_device_ac_018() {
    let (pc, phone) = pair();
    seed(&pc.handle);
    pc.exchange(&phone);

    // Phone goes offline and edits; the PC deletes meanwhile.
    cmd(
        &phone.handle,
        "transaction.update",
        json!({"id": "tx-shared-1", "amount_minor": -9000, "description": "Edited offline"}),
    );
    cmd(&pc.handle, "transaction.delete", json!({"id": "tx-shared-1"}));

    pc.exchange(&phone);
    assert_eq!(tx_count(&pc.handle), 0, "the expense stays deleted on the PC");
    assert_eq!(tx_count(&phone.handle), 0, "and is deleted on the phone");
    assert_eq!(pc.handle.projection_digest().unwrap(), phone.handle.projection_digest().unwrap());
    let err = phone
        .handle
        .command("transaction.update".into(), json!({"id": "tx-shared-1", "amount_minor": -1}).to_string())
        .unwrap_err();
    assert_eq!(code(&err), "deleted");
}

#[test]
fn the_delete_wins_even_when_the_edit_has_the_higher_clock() {
    let (pc, phone) = pair();
    seed(&pc.handle);
    pc.exchange(&phone);
    // The phone edits many times, so its Lamport clock runs ahead of the PC's delete.
    for amount in [-5100, -5200, -5300, -5400, -5500] {
        cmd(&phone.handle, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": amount}));
    }
    cmd(&pc.handle, "transaction.delete", json!({"id": "tx-shared-1"}));

    // Deliver in both orders on fresh copies of the PC side to prove order does not matter.
    let edit_first = pc.handle.sync_export(phone.id(), 500).unwrap();
    let from_phone = phone.handle.sync_export(pc.id(), 500).unwrap();
    pc.handle.sync_apply(phone.id(), from_phone).unwrap();
    phone.handle.sync_apply(pc.id(), edit_first).unwrap();
    assert_eq!(tx_count(&pc.handle), 0);
    assert_eq!(tx_count(&phone.handle), 0);
    assert_eq!(pc.handle.projection_digest().unwrap(), phone.handle.projection_digest().unwrap());
}

#[test]
fn rebuilding_projections_does_not_resurrect_deleted_records() {
    let (pc, phone) = pair();
    seed(&pc.handle);
    pc.exchange(&phone);
    cmd(&phone.handle, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -9000}));
    cmd(&pc.handle, "transaction.delete", json!({"id": "tx-shared-1"}));
    pc.exchange(&phone);
    let before = pc.handle.projection_digest().unwrap();
    pc.handle.rebuild_projections().unwrap();
    phone.handle.rebuild_projections().unwrap();
    assert_eq!(pc.handle.projection_digest().unwrap(), before);
    assert_eq!(phone.handle.projection_digest().unwrap(), before);
    assert_eq!(tx_count(&pc.handle) + tx_count(&phone.handle), 0);
}

// ---------------------------------------------------------------- Finance conflicts (AR-DOM-008)

#[test]
fn concurrent_amount_edits_surface_as_conflicts_on_both_devices_through_signed_sync() {
    let (pc, phone) = pair();
    seed(&pc.handle);
    pc.exchange(&phone);
    cmd(&pc.handle, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -1111}));
    cmd(&phone.handle, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -2222}));
    let (to_phone, to_pc) = pc.exchange(&phone);
    assert_eq!(to_phone.conflicts.len(), 1);
    assert_eq!(to_pc.conflicts.len(), 1);
    assert_eq!(rows(&pc.handle, "conflicts", json!({})).len(), 1);
    assert_eq!(rows(&phone.handle, "conflicts", json!({})).len(), 1);
    assert_eq!(pc.handle.projection_digest().unwrap(), phone.handle.projection_digest().unwrap());
}

#[test]
fn offline_expenses_added_on_each_side_end_up_on_both() {
    let (pc, phone) = pair();
    cmd(&pc.handle, "account.create", json!({"id": "acct-main-1", "name": "Main", "currency": "USD"}));
    pc.exchange(&phone);
    cmd(
        &pc.handle,
        "transaction.create",
        json!({"id": "tx-pc-00001", "account_id": "acct-main-1", "date": "2026-10-02", "amount_minor": -1250, "description": "PC lunch"}),
    );
    cmd(
        &phone.handle,
        "transaction.create",
        json!({"id": "tx-phone-001", "account_id": "acct-main-1", "date": "2026-10-02", "amount_minor": -4300, "description": "Phone taxi"}),
    );
    pc.exchange(&phone);
    assert_eq!(tx_count(&pc.handle), 2);
    assert_eq!(tx_count(&phone.handle), 2);
    assert_eq!(pc.handle.projection_digest().unwrap(), phone.handle.projection_digest().unwrap());
}

// ---------------------------------------------------------------- limits and hostile input

#[test]
fn oversized_or_absurd_batches_are_refused() {
    let (a, b) = pair();
    seed(&a.handle);
    let batch = a.handle.sync_export(b.id(), 500).unwrap();
    let event = events_of(&batch).remove(0);

    let too_many = with_events(&batch, vec![event.clone(); 501]);
    assert_eq!(code(&b.handle.sync_apply(a.id(), too_many).unwrap_err()), "validation");

    let mut huge_clock = event.clone();
    huge_clock["lamport"] = json!(i64::MAX);
    assert_eq!(code(&b.handle.sync_apply(a.id(), with_events(&batch, vec![huge_clock])).unwrap_err()), "validation");

    let backwards = SyncBatch { cursor_from: 9, cursor_to: 3, ..batch.clone() };
    assert_eq!(code(&b.handle.sync_apply(a.id(), backwards).unwrap_err()), "validation");

    let junk = SyncBatch { events_json: "not json".into(), ..batch.clone() };
    assert_eq!(code(&b.handle.sync_apply(a.id(), junk).unwrap_err()), "validation");

    let wrong_domain = {
        let mut e = event;
        e["domain"] = json!("memory");
        with_events(&batch, vec![e])
    };
    assert_eq!(code(&b.handle.sync_apply(a.id(), wrong_domain).unwrap_err()), "validation");
    assert_eq!(b.handle.event_count().unwrap(), 0);
}

#[test]
fn a_broken_signer_is_caught_before_anything_leaves_the_device() {
    let (a, b) = pair();
    let broken = Arc::new(TestSigner { key: SigningKey::from_slice(&[1; 32]).unwrap(), broken: true });
    a.handle.set_signer(broken);
    seed(&a.handle);
    let err = a.handle.sync_export(b.id(), 500).unwrap_err();
    assert!(matches!(code(&err), "internal" | "rejected"), "{err}");
}

#[test]
fn exporting_needs_a_device_key() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    let peer = TestSigner::new(2);
    h.register_peer("device-phone-1".into(), peer.public(), "Phone".into(), vec!["finance".into()]).unwrap();
    assert_eq!(code(&h.sync_export("device-phone-1".into(), 10).unwrap_err()), "rejected");
}
