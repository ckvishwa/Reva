mod common;

use common::MemKeys;
use reva_kernel::open_domain;
use serde_json::{json, Value};

#[test]
fn manual_health_records_make_exact_daily_summary_and_replay() {
    let dir = tempfile::tempdir().unwrap();
    let h = open_domain("health".into(), MemKeys::new(), dir.path().to_string_lossy().into()).unwrap();
    h.command("workout.log".into(), json!({"date":"2026-10-16","activity":"Walk","duration_minutes":35}).to_string())
        .unwrap();
    h.command("workout.log".into(), json!({"date":"2026-10-15","activity":"Walk","duration_minutes":60}).to_string())
        .unwrap();
    h.command("sleep.log".into(), json!({"date":"2026-10-16","duration_minutes":440}).to_string()).unwrap();
    h.command("meal.log".into(), json!({"date":"2026-10-16","description":"Lunch"}).to_string()).unwrap();
    h.command("weight.log".into(), json!({"date":"2026-10-16","weight_grams":72500}).to_string()).unwrap();
    let scheduled = h
        .command("medication.schedule".into(), json!({"name":"Vitamin D","start_date":"2026-10-15"}).to_string())
        .unwrap();
    h.command(
        "medication.mark_taken".into(),
        json!({"schedule_id":scheduled.aggregate_id,"date":"2026-10-16"}).to_string(),
    )
    .unwrap();
    let before = h.query("daily_summary".into(), json!({"date":"2026-10-16"}).to_string()).unwrap();
    let rows: Value = serde_json::from_str(&before.rows_json).unwrap();
    assert_eq!(rows[0]["workout_minutes"], 35);
    assert_eq!(rows[0]["sleep_minutes"], 440);
    assert_eq!(rows[0]["sleep_count"], 1);
    assert_eq!(rows[0]["meal_count"], 1);
    assert_eq!(rows[0]["weight_grams"], 72500);
    assert_eq!(rows[0]["medications_scheduled"], 1);
    assert_eq!(rows[0]["medications_taken"], 1);
    assert_eq!(before.source_ids.len(), 6);
    h.rebuild_projections().unwrap();
    let after = h.query("daily_summary".into(), json!({"date":"2026-10-16"}).to_string()).unwrap();
    assert_eq!(before.rows_json, after.rows_json);
}

#[test]
fn health_rejects_invalid_or_unreviewed_fields_without_event() {
    let dir = tempfile::tempdir().unwrap();
    let h = open_domain("health".into(), MemKeys::new(), dir.path().to_string_lossy().into()).unwrap();
    for payload in [
        json!({"date":"2026-02-30","activity":"Walk","duration_minutes":35}),
        json!({"date":"2026-10-16","activity":"Walk","duration_minutes":0}),
        json!({"date":"2026-10-16","activity":"Walk","duration_minutes":35,"dose":"10mg"}),
    ] {
        assert!(h.command("workout.log".into(), payload.to_string()).is_err());
    }
    assert_eq!(h.event_count().unwrap(), 0);
}

#[test]
fn medication_taken_is_unique_per_day_and_deleting_schedule_removes_its_history() {
    let dir = tempfile::tempdir().unwrap();
    let h = open_domain("health".into(), MemKeys::new(), dir.path().to_string_lossy().into()).unwrap();
    let schedule = h
        .command("medication.schedule".into(), json!({"name":"Vitamin D","start_date":"2026-10-15"}).to_string())
        .unwrap();
    let payload = json!({"schedule_id":schedule.aggregate_id,"date":"2026-10-16"}).to_string();
    h.command("medication.mark_taken".into(), payload.clone()).unwrap();
    assert!(h.command("medication.mark_taken".into(), payload).is_err());
    h.command("record.delete".into(), json!({"id":schedule.aggregate_id}).to_string()).unwrap();
    let summary = h.query("daily_summary".into(), json!({"date":"2026-10-16"}).to_string()).unwrap();
    let rows: Value = serde_json::from_str(&summary.rows_json).unwrap();
    assert_eq!(rows[0]["medications_scheduled"], 0);
    assert_eq!(rows[0]["medications_taken"], 0);
    h.rebuild_projections().unwrap();
    assert_eq!(
        summary.rows_json,
        h.query("daily_summary".into(), json!({"date":"2026-10-16"}).to_string()).unwrap().rows_json
    );
}

#[test]
fn weekly_summary_uses_only_the_seven_days_ending_on_requested_day() {
    let dir = tempfile::tempdir().unwrap();
    let h = open_domain("health".into(), MemKeys::new(), dir.path().to_string_lossy().into()).unwrap();
    for (day, minutes) in [("2026-10-12", 420), ("2026-10-18", 480), ("2026-10-11", 600)] {
        h.command("sleep.log".into(), json!({"date":day,"duration_minutes":minutes}).to_string()).unwrap();
    }
    h.command("workout.log".into(), json!({"date":"2026-10-18","activity":"Walk","duration_minutes":30}).to_string())
        .unwrap();
    let result = h.query("weekly_summary".into(), json!({"date":"2026-10-18"}).to_string()).unwrap();
    let rows: Value = serde_json::from_str(&result.rows_json).unwrap();
    assert_eq!(rows[0]["start_date"], "2026-10-12");
    assert_eq!(rows[0]["end_date"], "2026-10-18");
    assert_eq!(rows[0]["sleep_minutes"], 900);
    assert_eq!(rows[0]["sleep_count"], 2);
    assert_eq!(rows[0]["workout_minutes"], 30);
    assert_eq!(result.source_ids.len(), 3);
}

#[test]
fn manual_steps_and_heart_rate_are_factual_and_bounded() {
    let dir = tempfile::tempdir().unwrap();
    let h = open_domain("health".into(), MemKeys::new(), dir.path().to_string_lossy().into()).unwrap();
    h.command("steps.log".into(), json!({"date":"2026-10-18","steps":0}).to_string()).unwrap();
    h.command("heart_rate.log".into(), json!({"date":"2026-10-18","bpm":62}).to_string()).unwrap();
    h.command("heart_rate.log".into(), json!({"date":"2026-10-18","bpm":88}).to_string()).unwrap();
    assert!(h.command("steps.log".into(), json!({"date":"2026-10-18","steps":100}).to_string()).is_err());
    assert!(h.command("heart_rate.log".into(), json!({"date":"2026-10-18","bpm":0}).to_string()).is_err());
    let daily = h.query("daily_summary".into(), json!({"date":"2026-10-18"}).to_string()).unwrap();
    let rows: Value = serde_json::from_str(&daily.rows_json).unwrap();
    assert_eq!(rows[0]["steps"], 0);
    assert_eq!(rows[0]["steps_count"], 1);
    assert_eq!(rows[0]["heart_rate_count"], 2);
    assert_eq!(rows[0]["heart_rate_min_bpm"], 62);
    assert_eq!(rows[0]["heart_rate_max_bpm"], 88);
    let weekly = h.query("weekly_summary".into(), json!({"date":"2026-10-18"}).to_string()).unwrap();
    let week_rows: Value = serde_json::from_str(&weekly.rows_json).unwrap();
    assert_eq!(week_rows[0]["steps_total"], 0);
    assert_eq!(week_rows[0]["steps_days"], 1);
    assert_eq!(week_rows[0]["heart_rate_count"], 2);
}
