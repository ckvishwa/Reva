//! Backend support for the Finance page: transaction source, conflict resolution, schema v3.

mod common;

use common::{cmd, code, open, rows, MemKeys};
use reva_kernel::{DomainHandle, EventBatch};
use serde_json::{json, Value};

fn setup() -> (tempfile::TempDir, std::sync::Arc<DomainHandle>) {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    cmd(&h, "account.create", json!({"id": "acct-main-1", "name": "Main", "currency": "USD"}));
    (dir, h)
}

fn tx(h: &DomainHandle, id: &str) -> Value {
    rows(h, "get", json!({"aggregate_type": "transaction", "id": id})).remove(0)
}

fn pull(from: &DomainHandle) -> EventBatch {
    from.pending_events(1000).unwrap()
}

#[test]
fn manual_is_the_default_source_and_voice_is_allowed() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-manual-01", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -100, "description": "a"}),
    );
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-voice-001", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -200, "description": "b", "source": "voice"}),
    );
    assert_eq!(tx(&h, "tx-manual-01")["source_kind"], "manual");
    assert_eq!(tx(&h, "tx-voice-001")["source_kind"], "voice");
    assert_eq!(tx(&h, "tx-voice-001")["source"], "voice");
    for bad in ["phone", "csv", "import", "robot", ""] {
        let r = h.command(
            "transaction.create".into(),
            json!({"account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -1, "description": "x", "source": bad}).to_string(),
        );
        if bad.is_empty() {
            assert!(r.is_ok(), "empty source falls back to manual");
        } else {
            assert_eq!(code(&r.unwrap_err()), "validation", "{bad}");
        }
    }
}

#[test]
fn imports_record_their_format_as_the_source() {
    let (_d, h) = setup();
    let csv = b"Date,Memo,Amount\n2026-10-02,From csv,-1.00\n";
    h.import_data(
        "csv".into(),
        csv.to_vec(),
        json!({"account_id": "acct-main-1", "mapping": {"date": "Date", "description": "Memo", "amount": "Amount"}})
            .to_string(),
    )
    .unwrap();
    let ofx = "<OFX><CURDEF>USD<BANKTRANLIST><STMTTRN><DTPOSTED>20261003<TRNAMT>-2.00<FITID>S1<NAME>From ofx\n</BANKTRANLIST></OFX>";
    h.import_data("ofx".into(), ofx.as_bytes().to_vec(), json!({"account_id": "acct-main-1"}).to_string()).unwrap();
    let kinds: Vec<(String, String)> = rows(&h, "list_transactions", json!({}))
        .iter()
        .map(|t| (t["description"].as_str().unwrap().to_string(), t["source_kind"].as_str().unwrap().to_string()))
        .collect();
    assert!(kinds.contains(&("From csv".into(), "csv".into())), "{kinds:?}");
    assert!(kinds.contains(&("From ofx".into(), "ofx".into())), "{kinds:?}");
}

#[test]
fn a_transaction_first_recorded_on_another_device_is_a_phone_transaction() {
    let (_da, a) = setup();
    let db = tempfile::tempdir().unwrap();
    let b = open(db.path(), &MemKeys::new()).unwrap();
    cmd(
        &a,
        "transaction.create",
        json!({"id": "tx-from-pc-01", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -5, "description": "pc"}),
    );
    b.apply_events(pull(&a)).unwrap();
    cmd(
        &b,
        "transaction.create",
        json!({"id": "tx-from-ph-01", "account_id": "acct-main-1", "date": "2026-10-02", "amount_minor": -6, "description": "phone"}),
    );
    a.apply_events(pull(&b)).unwrap();
    assert_eq!(tx(&a, "tx-from-pc-01")["source_kind"], "manual");
    assert_eq!(tx(&a, "tx-from-ph-01")["source_kind"], "phone");
    assert_eq!(tx(&b, "tx-from-pc-01")["source_kind"], "phone", "from B's point of view the PC is the other device");
    assert_eq!(tx(&b, "tx-from-ph-01")["source_kind"], "manual");
}

#[test]
fn json_restore_keeps_the_recorded_source() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-voice-001", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -200, "description": "b", "source": "voice"}),
    );
    let dump = h.export("json".into()).unwrap();
    let dir = tempfile::tempdir().unwrap();
    let fresh = open(dir.path(), &MemKeys::new()).unwrap();
    let r = fresh.import_data("json".into(), dump, "{}".into()).unwrap();
    assert!(r.rejected.is_empty(), "{:?}", r.rejected);
    assert_eq!(tx(&fresh, "tx-voice-001")["source"], "voice");
}

fn conflicted_pair(
) -> (tempfile::TempDir, tempfile::TempDir, std::sync::Arc<DomainHandle>, std::sync::Arc<DomainHandle>) {
    let (da, db) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let a = open(da.path(), &MemKeys::new()).unwrap();
    let b = open(db.path(), &MemKeys::new()).unwrap();
    cmd(&a, "account.create", json!({"id": "acct-main-1", "name": "Main", "currency": "USD"}));
    cmd(
        &a,
        "transaction.create",
        json!({"id": "tx-shared-01", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -5000, "description": "Corner Cafe"}),
    );
    let base = pull(&a);
    a.ack(base.cursor).unwrap();
    b.apply_events(base).unwrap();
    cmd(&a, "transaction.update", json!({"id": "tx-shared-01", "amount_minor": -1111}));
    cmd(&b, "transaction.update", json!({"id": "tx-shared-01", "amount_minor": -2222}));
    let (from_a, from_b) = (pull(&a), pull(&b));
    b.apply_events(from_a).unwrap();
    a.apply_events(from_b).unwrap();
    (da, db, a, b)
}

#[test]
fn conflicts_list_shows_what_the_banner_needs_and_hides_resolved_ones() {
    let (_da, _db, a, _b) = conflicted_pair();
    let list = rows(&a, "conflicts", json!({}));
    assert_eq!(list.len(), 1);
    let c = &list[0];
    assert_eq!(c["label"], "Corner Cafe");
    assert_eq!(c["currency"], "USD");
    assert_eq!(c["aggregate_type"], "transaction");
    let values = [c["local_value"].as_str().unwrap(), c["remote_value"].as_str().unwrap()];
    assert!(values.contains(&"-1111") && values.contains(&"-2222"));
}

#[test]
fn resolving_a_conflict_writes_the_chosen_amount_and_both_devices_converge() {
    for keep in ["local", "remote"] {
        let (_da, _db, a, b) = conflicted_pair();
        let c = rows(&a, "conflicts", json!({})).remove(0);
        let chosen =
            c[if keep == "local" { "local_value" } else { "remote_value" }].as_str().unwrap().parse::<i64>().unwrap();
        a.ack(a.pending_events(1000).unwrap().cursor).unwrap();
        cmd(&a, "conflict.resolve", json!({"conflict_id": c["id"], "keep": keep}));
        assert_eq!(tx(&a, "tx-shared-01")["amount_minor"], chosen, "keep {keep}");
        assert!(rows(&a, "conflicts", json!({})).is_empty(), "resolved conflicts disappear from the banner");
        assert_eq!(rows(&a, "conflicts", json!({"include_resolved": true})).len(), 1);

        // The resolution replicates: B ends with the same amount and no open conflict.
        let report = b.apply_events(pull(&a)).unwrap();
        assert!(report.applied >= 1);
        assert_eq!(tx(&b, "tx-shared-01")["amount_minor"], chosen);
        assert!(rows(&b, "conflicts", json!({})).is_empty());
        assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());
        a.rebuild_projections().unwrap();
        assert_eq!(a.integrity_check().unwrap(), "ok");
    }
}

#[test]
fn conflict_resolution_rejects_bad_requests() {
    let (_da, _db, a, _b) = conflicted_pair();
    let id = rows(&a, "conflicts", json!({})).remove(0)["id"].clone();
    let fail = |payload: Value| a.command("conflict.resolve".into(), payload.to_string()).unwrap_err();
    assert_eq!(code(&fail(json!({"conflict_id": id, "keep": "both"}))), "validation");
    assert_eq!(code(&fail(json!({"conflict_id": id}))), "validation");
    assert_eq!(code(&fail(json!({"conflict_id": 9999, "keep": "local"}))), "not_found");
    assert_eq!(code(&fail(json!({"conflict_id": id, "keep": "local", "extra": 1}))), "validation");
    cmd(&a, "conflict.resolve", json!({"conflict_id": id, "keep": "local"}));
    assert_eq!(code(&fail(json!({"conflict_id": id, "keep": "remote"}))), "conflict", "already resolved");
}
