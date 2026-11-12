//! Health backup roundtrip, Health Connect daily import, provenance, deletion and safety rules.

mod common;

use std::sync::Arc;

use common::{code, MemKeys};
use reva_kernel::{open_domain, DomainHandle, ImportReport};
use serde_json::{json, Value};

fn health(dir: &std::path::Path) -> Arc<DomainHandle> {
    open_domain("health".into(), MemKeys::new(), dir.to_string_lossy().into()).unwrap()
}

fn cmd(h: &DomainHandle, kind: &str, payload: Value) -> String {
    h.command(kind.into(), payload.to_string()).unwrap_or_else(|e| panic!("{kind}: {e}")).aggregate_id
}

fn summary(h: &DomainHandle, name: &str, day: &str) -> Value {
    let out = h.query(name.into(), json!({"date": day}).to_string()).unwrap();
    serde_json::from_str::<Value>(&out.rows_json).unwrap()[0].clone()
}

fn import(h: &DomainHandle, format: &str, data: &Value, options: &str) -> ImportReport {
    h.import_data(format.into(), data.to_string().into_bytes(), options.into()).unwrap()
}

fn connect_days(days: Value) -> Value {
    json!({"format": "reva-health-connect-v1", "days": days})
}

fn statuses(report: &ImportReport) -> Vec<String> {
    let rows: Value = serde_json::from_str(&report.rows_json).unwrap();
    rows.as_array().unwrap().iter().map(|r| r["status"].as_str().unwrap().to_string()).collect()
}

fn seed(h: &DomainHandle) -> String {
    cmd(h, "workout.log", json!({"date":"2026-10-16","activity":"Walk","duration_minutes":35}));
    cmd(h, "sleep.log", json!({"date":"2026-10-16","duration_minutes":440}));
    cmd(h, "meal.log", json!({"date":"2026-10-16","description":"Lunch"}));
    cmd(h, "weight.log", json!({"date":"2026-10-16","weight_grams":72500}));
    cmd(h, "steps.log", json!({"date":"2026-10-16","steps":8000}));
    cmd(h, "heart_rate.log", json!({"date":"2026-10-16","bpm":64}));
    let schedule = cmd(h, "medication.schedule", json!({"name":"Vitamin D","start_date":"2026-10-15"}));
    cmd(h, "medication.mark_taken", json!({"schedule_id":schedule,"date":"2026-10-16"}));
    schedule
}

#[test]
fn backup_restores_into_a_fresh_install_with_identical_state_and_reimport_is_all_duplicates() {
    let (a_dir, b_dir) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let a = health(a_dir.path());
    seed(&a);
    let backup = a.export("json".into()).unwrap();
    let parsed: Value = serde_json::from_slice(&backup).unwrap();
    // GYM-02 deliberately moved the written format to v2, which adds the gym section. A v1 file
    // still restores; a_backup_written_before_gym_training_still_restores in gym_backup.rs covers it.
    assert_eq!(parsed["format"], "reva-health-v2");

    let b = health(b_dir.path());
    let dry = b.import_data("json".into(), backup.clone(), r#"{"dry_run":true}"#.into()).unwrap();
    assert!(dry.dry_run);
    assert_eq!(dry.accepted, 8);
    assert_eq!(b.event_count().unwrap(), 0, "a dry run commits nothing");

    let real = b.import_data("json".into(), backup.clone(), "{}".into()).unwrap();
    assert_eq!((real.accepted, real.duplicates, real.rejected.len()), (8, 0, 0));
    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());
    for name in ["daily_summary", "weekly_summary"] {
        assert_eq!(summary(&a, name, "2026-10-16"), summary(&b, name, "2026-10-16"), "{name}");
    }

    let again = b.import_data("json".into(), backup, "{}".into()).unwrap();
    assert_eq!((again.accepted, again.duplicates, again.rejected.len()), (0, 8, 0));
    b.rebuild_projections().unwrap();
    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());
}

#[test]
fn a_deleted_record_is_never_brought_back_by_restoring_an_older_backup() {
    let dir = tempfile::tempdir().unwrap();
    let h = health(dir.path());
    let schedule = seed(&h);
    let backup = h.export("json".into()).unwrap();
    cmd(&h, "record.delete", json!({"id": schedule}));
    let digest = h.projection_digest().unwrap();
    let report = h.import_data("json".into(), backup, "{}".into()).unwrap();
    assert_eq!(report.accepted, 0);
    assert_eq!(report.rejected.len(), 2, "the schedule and its taken entry were deleted together");
    assert!(report.rejected.iter().all(|r| r.reason.contains("deleted on this device")), "{:?}", report.rejected);
    assert_eq!(h.projection_digest().unwrap(), digest);
    let exported: Value = serde_json::from_slice(&h.export("json".into()).unwrap()).unwrap();
    assert!(!exported.to_string().contains(&schedule), "a deleted record is not in later exports");
}

#[test]
fn restore_rejects_records_that_break_the_rules_with_a_reason_per_row() {
    let dir = tempfile::tempdir().unwrap();
    let h = health(dir.path());
    let ok = |id: &str, kind: &str, extra: Value| {
        let mut r = json!({"id": id, "kind": kind, "date": "2026-10-16", "created_at": "2026-10-16T08:00:00.000Z"});
        r.as_object_mut().unwrap().extend(extra.as_object().unwrap().clone());
        r
    };
    let file = json!({"format": "reva-health-v1", "records": [
        // A taken entry listed before its schedule is still checked against it.
        ok("taken-0001", "medication_taken", json!({"schedule_id": "sched-0001"})),
        ok("sched-0001", "medication_schedule", json!({"name": "Vitamin D"})),
        ok("dose-00001", "medication_schedule", json!({"name": "X", "dose": "10mg"})),
        ok("orphan-001", "medication_taken", json!({"schedule_id": "missing-01"})),
        ok("hr-day-001", "heart_rate_day", json!({"min_bpm": 50, "max_bpm": 90, "samples": 4})),
        ok("hc-steps-2026-10-15", "steps_day", json!({"steps": 10, "source": "health_connect"})),
        ok("weird-src1", "steps_day", json!({"steps": 10, "source": "cloud"})),
        ok("bad/id", "meal", json!({"description": "Lunch"})),
        ok("steps-0001", "steps_day", json!({"steps": 100})),
        ok("steps-0002", "steps_day", json!({"steps": 200})),
        json!("not an object"),
    ]});
    let report = import(&h, "json", &file, "{}");
    assert_eq!(
        statuses(&report),
        [
            "accepted", "accepted", "rejected", "rejected", "rejected", "rejected", "rejected", "rejected", "accepted",
            "rejected", "rejected"
        ]
    );
    assert_eq!(report.accepted + report.duplicates + report.rejected.len() as u64, 11, "every row accounted for");
    assert!(report.rejected.iter().all(|r| !r.reason.is_empty()));
    assert_eq!(summary(&h, "daily_summary", "2026-10-16")["steps"], 100);

    for bad in
        [json!({"format": "other", "records": []}), json!({"format": "reva-health-v1", "records": [], "extra": 1})]
    {
        let e = h.import_data("json".into(), bad.to_string().into_bytes(), "{}".into()).unwrap_err();
        assert_eq!(code(&e), "validation");
    }
    let e = h.import_data("json".into(), b"{not json".to_vec(), "{}".into()).unwrap_err();
    assert_eq!(code(&e), "validation");
    let e = h.import_data("csv".into(), b"a,b".to_vec(), "{}".into()).unwrap_err();
    assert_eq!(code(&e), "validation");
    let e = h.import_data("json".into(), file.to_string().into_bytes(), r#"{"account_id":"x"}"#.into()).unwrap_err();
    assert_eq!(code(&e), "validation");
}

#[test]
fn repeated_health_connect_imports_are_idempotent_and_never_double_count_steps() {
    let dir = tempfile::tempdir().unwrap();
    let h = health(dir.path());
    let days = connect_days(json!([
        {"date":"2026-10-17","type":"steps","steps":4000,"origins":["com.example.watch","com.example.phone"]},
        {"date":"2026-10-18","type":"steps","steps":6000,"origins":["com.example.watch"]},
        {"date":"2026-10-18","type":"heart_rate","min_bpm":55,"max_bpm":120,"samples":300,"origins":["com.example.watch"]},
    ]));
    let first = import(&h, "health_connect", &days, "{}");
    assert_eq!((first.accepted, first.duplicates), (3, 0));
    let events = h.event_count().unwrap();
    let second = import(&h, "health_connect", &days, "{}");
    assert_eq!((second.accepted, second.duplicates), (0, 3));
    assert_eq!(h.event_count().unwrap(), events, "an unchanged repeat writes nothing");

    // Later in the day Health Connect reports a higher total: the same record is updated, not added to.
    let later =
        connect_days(json!([{"date":"2026-10-18","type":"steps","steps":9000,"origins":["com.example.watch"]}]));
    let third = import(&h, "health_connect", &later, "{}");
    assert_eq!(statuses(&third), ["updated"]);
    let day = summary(&h, "daily_summary", "2026-10-18");
    assert_eq!(day["steps"], 9000);
    assert_eq!(day["steps_count"], 1);
    assert_eq!(day["steps_source"], "health_connect");
    assert_eq!(day["heart_rate_count"], 300);
    assert_eq!(day["heart_rate_min_bpm"], 55);
    let week = summary(&h, "weekly_summary", "2026-10-18");
    assert_eq!(week["steps_total"], 13000);
    assert_eq!(week["steps_days"], 2);

    let exported: Value = serde_json::from_slice(&h.export("json".into()).unwrap()).unwrap();
    let steps = exported["records"].as_array().unwrap().iter().find(|r| r["id"] == "hc-steps-2026-10-17").unwrap();
    assert_eq!(steps["source"], "health_connect");
    assert_eq!(steps["origins"], json!(["com.example.phone", "com.example.watch"]), "provenance is kept, sorted");

    h.rebuild_projections().unwrap();
    assert_eq!(summary(&h, "daily_summary", "2026-10-18"), day);
}

#[test]
fn same_day_manual_and_health_connect_steps_are_shown_as_a_conflict_not_summed() {
    let dir = tempfile::tempdir().unwrap();
    let h = health(dir.path());
    import(&h, "health_connect", &connect_days(json!([{"date":"2026-10-18","type":"steps","steps":7000}])), "{}");
    // A Health Connect day does not block the user's own entry for that day.
    cmd(&h, "steps.log", json!({"date":"2026-10-18","steps":5000}));
    let day = summary(&h, "daily_summary", "2026-10-18");
    assert_eq!(day["steps"], 5000, "the user's own entry is what totals use");
    assert_eq!(day["steps_source"], "manual");
    assert_eq!(day["steps_conflict"], true);
    assert_eq!(day["steps_manual"], 5000);
    assert_eq!(day["steps_health_connect"], 7000);
    let week = summary(&h, "weekly_summary", "2026-10-18");
    assert_eq!(week["steps_total"], 5000);
    assert_eq!(week["steps_days"], 1);
    assert_eq!(week["steps_conflict_dates"], json!(["2026-10-18"]));

    // Equal values are not a conflict.
    import(&h, "health_connect", &connect_days(json!([{"date":"2026-10-18","type":"steps","steps":5000}])), "{}");
    assert_eq!(summary(&h, "daily_summary", "2026-10-18")["steps_conflict"], false);
    // A second manual entry for the day is still refused.
    assert_eq!(
        code(&h.command("steps.log".into(), json!({"date":"2026-10-18","steps":1}).to_string()).unwrap_err()),
        "conflict"
    );
}

#[test]
fn deleted_health_connect_days_stay_deleted_and_source_delete_forgets_only_imported_data() {
    let dir = tempfile::tempdir().unwrap();
    let h = health(dir.path());
    let days = connect_days(json!([
        {"date":"2026-10-17","type":"steps","steps":4000},
        {"date":"2026-10-18","type":"steps","steps":6000},
        {"date":"2026-10-18","type":"heart_rate","min_bpm":60,"max_bpm":100,"samples":10},
    ]));
    import(&h, "health_connect", &days, "{}");
    cmd(&h, "record.delete", json!({"id":"hc-steps-2026-10-17"}));
    let again = import(&h, "health_connect", &days, "{}");
    assert_eq!(statuses(&again), ["rejected", "duplicate", "duplicate"]);
    assert!(again.rejected[0].reason.contains("deleted on this device"));

    let manual = cmd(&h, "meal.log", json!({"date":"2026-10-18","description":"Dinner"}));
    cmd(&h, "source.delete", json!({"source":"health_connect"}));
    let day = summary(&h, "daily_summary", "2026-10-18");
    assert_eq!(day["steps"], Value::Null);
    assert_eq!(day["heart_rate_count"], 0);
    assert_eq!(day["meal_count"], 1, "manual entries are untouched");
    let exported = String::from_utf8(h.export("json".into()).unwrap()).unwrap();
    assert!(!exported.contains("health_connect") && exported.contains(&manual));
    assert_eq!(
        code(&h.command("source.delete".into(), json!({"source":"health_connect"}).to_string()).unwrap_err()),
        "not_found"
    );
    assert_eq!(
        code(&h.command("source.delete".into(), json!({"source":"manual"}).to_string()).unwrap_err()),
        "validation"
    );
}

#[test]
fn health_connect_import_validates_every_day_with_a_reason() {
    let dir = tempfile::tempdir().unwrap();
    let h = health(dir.path());
    let report = import(
        &h,
        "health_connect",
        &connect_days(json!([
            {"date":"2026-10-18","type":"steps","steps":100},
            {"date":"2026-10-18","type":"steps","steps":200},
            {"date":"2026-10-18","type":"weight","grams":1},
            {"date":"2026-02-30","type":"steps","steps":1},
            {"date":"2026-10-17","type":"steps","steps":-1},
            {"date":"2026-10-17","type":"steps","steps":1,"origins":["not a package!"]},
            {"date":"2026-10-17","type":"heart_rate","min_bpm":120,"max_bpm":60,"samples":2},
            {"date":"2026-10-17","type":"steps","steps":1,"note":"extra"},
        ])),
        "{}",
    );
    assert_eq!(
        statuses(&report),
        ["accepted", "rejected", "rejected", "rejected", "rejected", "rejected", "rejected", "rejected"]
    );
    assert!(report.rejected[0].reason.contains("more than once"));
    let e = h.import_data(
        "health_connect".into(),
        json!({"format":"reva-health-v1","days":[]}).to_string().into_bytes(),
        "{}".into(),
    );
    assert_eq!(code(&e.unwrap_err()), "validation");
    let too_many: Vec<Value> = (0..401).map(|i| json!({"date":"2026-10-18","type":"steps","steps":i})).collect();
    let e = h.import_data("health_connect".into(), connect_days(json!(too_many)).to_string().into_bytes(), "{}".into());
    assert_eq!(code(&e.unwrap_err()), "validation");
}

/// Health is a record keeper: no command or query may diagnose, rate, or advise on medication.
#[test]
fn health_commands_and_summaries_carry_no_diagnosis_or_dosing_vocabulary() {
    const FORBIDDEN: &[&str] = &[
        "diagnose",
        "diagnosis",
        "dose",
        "dosage",
        "dosing",
        "prescribe",
        "treatment",
        "risk",
        "normal",
        "abnormal",
        "advice",
        "recommend",
        "score",
    ];
    let dir = tempfile::tempdir().unwrap();
    let h = health(dir.path());
    seed(&h);
    import(
        &h,
        "health_connect",
        &connect_days(json!([{"date":"2026-10-16","type":"heart_rate","min_bpm":40,"max_bpm":190,"samples":5}])),
        "{}",
    );
    let mut words: Vec<String> = h.command_names();
    for name in ["daily_summary", "weekly_summary"] {
        words.extend(summary(&h, name, "2026-10-16").as_object().unwrap().keys().cloned());
    }
    for word in &words {
        for token in word.split(['.', '_']) {
            assert!(!FORBIDDEN.contains(&token), "{word} contains {token:?}");
        }
    }
    // Extreme readings are stored as facts; nothing in the summary judges them.
    let day = summary(&h, "daily_summary", "2026-10-16");
    assert_eq!((day["heart_rate_min_bpm"].as_i64(), day["heart_rate_max_bpm"].as_i64()), (Some(40), Some(190)));
    for dose in [
        json!({"name":"Ibuprofen","start_date":"2026-10-16","dose_mg":400}),
        json!({"name":"Ibuprofen","start_date":"2026-10-16","frequency":"2x"}),
    ] {
        assert_eq!(code(&h.command("medication.schedule".into(), dose.to_string()).unwrap_err()), "validation");
    }
}
