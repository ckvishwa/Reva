//! Event log, outbox, tombstones, replication primitives (AR-DOM-004, AR-DOM-008).

mod common;

use common::{cmd, code, open, rows, MemKeys};
use reva_kernel::{DomainHandle, EventBatch};
use serde_json::{json, Value};

fn two_devices() -> (tempfile::TempDir, tempfile::TempDir, std::sync::Arc<DomainHandle>, std::sync::Arc<DomainHandle>) {
    let (da, db) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let a = open(da.path(), &MemKeys::new()).unwrap();
    let b = open(db.path(), &MemKeys::new()).unwrap();
    assert_ne!(a.device_id(), b.device_id());
    (da, db, a, b)
}

fn pull(from: &DomainHandle) -> EventBatch {
    from.pending_events(1000).unwrap()
}

fn seed_account_and_tx(h: &DomainHandle) {
    cmd(h, "account.create", json!({"id": "acct-main-1", "name": "Main", "currency": "USD"}));
    cmd(
        h,
        "transaction.create",
        json!({"id": "tx-shared-1", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -5000, "description": "Shared"}),
    );
}

#[test]
fn every_command_appends_an_event_and_an_outbox_entry() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    seed_account_and_tx(&h);
    assert_eq!(h.event_count().unwrap(), 2);
    let batch = pull(&h);
    assert_eq!(batch.count, 2);
    let events: Vec<Value> = serde_json::from_str(&batch.events_json).unwrap();
    for e in &events {
        assert_eq!(e["event_schema"], "1.0");
        assert_eq!(e["domain"], "finance");
        assert_eq!(e["origin_device_id"], h.device_id());
        assert!(e["signature"].as_str().unwrap().len() == 64);
        assert_eq!(e["tombstone"], false);
    }
    assert_eq!(events[0]["kind"], "account.created");
    assert_eq!(events[1]["kind"], "transaction.created");
    assert!(events[1]["lamport"].as_i64().unwrap() > events[0]["lamport"].as_i64().unwrap());
}

#[test]
fn ack_clears_the_outbox_up_to_the_cursor_only() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    seed_account_and_tx(&h);
    let first = h.pending_events(1).unwrap();
    assert_eq!(first.count, 1);
    h.ack(first.cursor).unwrap();
    let rest = h.pending_events(10).unwrap();
    assert_eq!(rest.count, 1);
    let ev: Vec<Value> = serde_json::from_str(&rest.events_json).unwrap();
    assert_eq!(ev[0]["kind"], "transaction.created");
    h.ack(rest.cursor).unwrap();
    assert_eq!(h.pending_events(10).unwrap().count, 0);
    assert_eq!(h.event_count().unwrap(), 2, "acking never removes events from the log");
}

#[test]
fn applying_events_reproduces_state_and_duplicates_are_no_ops() {
    let (_da, _db, a, b) = two_devices();
    seed_account_and_tx(&a);
    let batch = pull(&a);
    let report = b.apply_events(batch.clone()).unwrap();
    assert_eq!((report.applied, report.duplicates), (2, 0));
    assert!(report.conflicts.is_empty());
    assert_eq!(rows(&b, "list_transactions", json!({})).len(), 1);
    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());

    let again = b.apply_events(batch).unwrap();
    assert_eq!((again.applied, again.duplicates), (0, 2), "duplicate events are no-ops");
    assert_eq!(b.event_count().unwrap(), 2);
    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());
    assert_eq!(b.pending_events(10).unwrap().count, 0, "received events are not re-sent");
}

#[test]
fn order_of_delivery_does_not_change_the_result() {
    let (_da, _db, a, b) = two_devices();
    let dc = tempfile::tempdir().unwrap();
    let c = open(dc.path(), &MemKeys::new()).unwrap();
    seed_account_and_tx(&a);
    cmd(&a, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -7000}));
    cmd(&a, "transaction.update", json!({"id": "tx-shared-1", "description": "Edited"}));
    let batch = pull(&a);
    let mut events: Vec<Value> = serde_json::from_str(&batch.events_json).unwrap();
    b.apply_events(batch.clone()).unwrap();
    events.reverse();
    let reversed =
        EventBatch { events_json: serde_json::to_string(&events).unwrap(), cursor: batch.cursor, count: batch.count };
    c.apply_events(reversed).unwrap();
    assert_eq!(b.projection_digest().unwrap(), c.projection_digest().unwrap());
    let tx = &rows(&c, "list_transactions", json!({}))[0];
    assert_eq!(tx["amount_minor"], -7000);
    assert_eq!(tx["description"], "Edited");
    assert_eq!(tx["version"], 3);
}

#[test]
fn a_late_older_event_does_not_overwrite_a_newer_state() {
    let (_da, _db, a, b) = two_devices();
    seed_account_and_tx(&a);
    let first = pull(&a);
    a.ack(first.cursor).unwrap();
    cmd(&a, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -9000}));
    let second = pull(&a);
    // Newer event first, then the older creation arrives late.
    b.apply_events(second).unwrap_err_or_ok();
    b.apply_events(first).unwrap();
    assert_eq!(rows(&b, "list_transactions", json!({}))[0]["amount_minor"], -9000);
}

trait Tolerate {
    fn unwrap_err_or_ok(self);
}
impl<T> Tolerate for Result<T, reva_kernel::DomainError> {
    fn unwrap_err_or_ok(self) {
        // Delivering the update before its account/creation exists is allowed: events are state-based.
        let _ = self;
    }
}

#[test]
fn concurrent_amount_edits_are_reported_as_conflicts_and_both_devices_converge() {
    let (_da, _db, a, b) = two_devices();
    seed_account_and_tx(&a);
    let base = pull(&a);
    a.ack(base.cursor).unwrap();
    b.apply_events(base).unwrap();

    cmd(&a, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -1111}));
    cmd(&b, "transaction.update", json!({"id": "tx-shared-1", "amount_minor": -2222}));

    let from_a = pull(&a);
    let from_b = pull(&b);
    let report_b = b.apply_events(from_a).unwrap();
    let report_a = a.apply_events(from_b).unwrap();
    assert_eq!(report_a.conflicts.len(), 1, "device A must be told about the disagreement");
    assert_eq!(report_b.conflicts.len(), 1, "device B must be told about the disagreement");
    let c = &report_a.conflicts[0];
    assert_eq!((c.aggregate_type.as_str(), c.field.as_str()), ("transaction", "amount_minor"));
    let values = [c.local_value.clone(), c.remote_value.clone()];
    assert!(values.contains(&"-1111".to_string()) && values.contains(&"-2222".to_string()), "{values:?}");

    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap(), "devices converge");
    assert_eq!(rows(&a, "conflicts", json!({})).len(), 1, "the conflict stays visible to the user");
    assert_eq!(
        rows(&a, "list_transactions", json!({}))[0]["amount_minor"],
        rows(&b, "list_transactions", json!({}))[0]["amount_minor"]
    );
}

#[test]
fn deletions_replicate_as_tombstones() {
    let (_da, _db, a, b) = two_devices();
    seed_account_and_tx(&a);
    let base = pull(&a);
    a.ack(base.cursor).unwrap();
    b.apply_events(base).unwrap();
    cmd(&a, "transaction.delete", json!({"id": "tx-shared-1"}));
    let del = pull(&a);
    let events: Vec<Value> = serde_json::from_str(&del.events_json).unwrap();
    assert_eq!(events[0]["kind"], "transaction.deleted");
    assert_eq!(events[0]["tombstone"], true);
    b.apply_events(del).unwrap();
    assert!(rows(&b, "list_transactions", json!({})).is_empty());
    let err = b
        .command("transaction.update".into(), json!({"id": "tx-shared-1", "amount_minor": -1}).to_string())
        .unwrap_err();
    assert_eq!(code(&err), "deleted");
    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());
}

#[test]
fn malformed_remote_events_are_rejected_without_changing_anything() {
    let (_da, _db, a, b) = two_devices();
    seed_account_and_tx(&a);
    let good: Vec<Value> = serde_json::from_str(&pull(&a).events_json).unwrap();
    let before = (b.event_count().unwrap(), b.projection_digest().unwrap());
    type Mutation = Box<dyn Fn(&mut Value)>;
    let cases: Vec<(&str, Mutation)> = vec![
        ("other domain", Box::new(|e| e["domain"] = json!("health"))),
        ("bad kind", Box::new(|e| e["kind"] = json!("transaction.exploded"))),
        ("tombstone mismatch", Box::new(|e| e["tombstone"] = json!(true))),
        ("short id", Box::new(|e| e["event_id"] = json!("abc"))),
        ("future schema", Box::new(|e| e["event_schema"] = json!("2.0"))),
        ("payload not object", Box::new(|e| e["payload"] = json!([]))),
        ("no signature", Box::new(|e| e["signature"] = json!(""))),
        ("bad type", Box::new(|e| e["aggregate_type"] = json!("Bad Type!"))),
        ("version 0", Box::new(|e| e["version"] = json!(0))),
    ];
    for (name, mutate) in cases {
        let mut events = good.clone();
        mutate(&mut events[0]);
        let batch =
            EventBatch { events_json: serde_json::to_string(&events).unwrap(), cursor: 0, count: events.len() as u64 };
        let err = b.apply_events(batch).unwrap_err();
        assert_eq!(code(&err), "validation", "{name}");
    }
    assert_eq!((b.event_count().unwrap(), b.projection_digest().unwrap()), before);
    let garbage = EventBatch { events_json: "not json".into(), cursor: 0, count: 0 };
    assert_eq!(code(&b.apply_events(garbage).unwrap_err()), "validation");
}

#[test]
fn rebuilt_projections_equal_live_state_after_a_mixed_history() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    cmd(
        &h,
        "account.create",
        json!({"id": "acct-main-1", "name": "Main", "currency": "USD", "opening_balance_minor": 10000}),
    );
    cmd(&h, "category.create", json!({"id": "cat-food-01", "name": "Food", "aliases": ["groceries"]}));
    for i in 0..30 {
        cmd(
            &h,
            "transaction.create",
            json!({"id": format!("tx-mixed-{i:03}"), "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -(i + 1) * 10, "description": format!("t{i}"), "category": "groceries"}),
        );
    }
    for i in (0..30).step_by(3) {
        cmd(&h, "transaction.update", json!({"id": format!("tx-mixed-{i:03}"), "amount_minor": -5}));
    }
    for i in (0..30).step_by(5) {
        cmd(&h, "transaction.delete", json!({"id": format!("tx-mixed-{i:03}")}));
    }
    cmd(&h, "category.update", json!({"id": "cat-food-01", "aliases": ["groceries", "market"]}));
    cmd(
        &h,
        "bill.create",
        json!({"id": "bill-test-01", "name": "B", "amount_minor": 100, "currency": "USD", "due_date": "2026-11-01", "recurrence": "monthly"}),
    );
    cmd(
        &h,
        "bill.mark_paid",
        json!({"id": "bill-test-01", "paid_date": "2026-11-01", "record_transaction": true, "account_id": "acct-main-1"}),
    );
    let live = h.projection_digest().unwrap();
    let replayed = h.rebuild_projections().unwrap();
    assert_eq!(replayed as i64, h.event_count().unwrap());
    assert_eq!(h.projection_digest().unwrap(), live, "rebuild == live");
    assert_eq!(h.integrity_check().unwrap(), "ok");
}
