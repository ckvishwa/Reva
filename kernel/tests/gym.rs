//! GYM-01: the default training program, a live workout session, and the finished session's
//! receipt. Every assertion reads what the Kernel actually committed to its encrypted file.

mod common;

use std::path::Path;
use std::sync::Arc;

use common::{code, MemKeys};
use reva_kernel::{open_domain, DomainHandle};
use serde_json::{json, Value};

fn open(dir: &Path, keys: &Arc<MemKeys>) -> Arc<DomainHandle> {
    open_domain("health".into(), keys.clone(), dir.to_string_lossy().into()).expect("health domain opens")
}

fn cmd(h: &DomainHandle, kind: &str, payload: Value) -> reva_kernel::CommitResult {
    h.command(kind.to_string(), payload.to_string()).unwrap_or_else(|e| panic!("{kind} failed: {e}"))
}

fn rows(h: &DomainHandle, name: &str, params: Value) -> Vec<Value> {
    let out = h.query(name.to_string(), params.to_string()).unwrap_or_else(|e| panic!("query {name} failed: {e}"));
    serde_json::from_str::<Value>(&out.rows_json).unwrap().as_array().cloned().unwrap_or_default()
}

fn one(h: &DomainHandle, name: &str, params: Value) -> Value {
    rows(h, name, params).into_iter().next().unwrap_or_else(|| panic!("query {name} returned no row"))
}

fn program(h: &DomainHandle) -> Value {
    one(h, "active_program", json!({}))
}

/// The active program read again, for tests that already bound `program` to a value.
fn reload(h: &DomainHandle) -> Value {
    program(h)
}

fn day(program: &Value, day_id: &str) -> Value {
    program["days"].as_array().unwrap().iter().find(|d| d["day_id"] == day_id).cloned().expect("plan day")
}

/// One completed working set, with the load in thousandths of the unit.
fn working_set(session: &str, exercise: &str, pounds: i64, reps: i64, at: &str) -> Value {
    json!({
        "session_id": session,
        "exercise_key": exercise,
        "set_type": "working",
        "weight_unit": "lb",
        "load_milli": pounds * 1_000,
        "reps": reps,
        "completed": true,
        "completed_at": at,
    })
}

// ---------------------------------------------------------------------------------------------
// GYM-01A Training Plan

#[test]
fn the_default_program_is_the_reviewed_seven_day_split() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    assert!(rows(&h, "active_program", json!({})).is_empty(), "no program exists before one is created");

    cmd(&h, "gym.program.create_default", json!({"anchor_date": "2026-10-22"}));
    let program = program(&h);
    let days = program["days"].as_array().unwrap();
    assert_eq!(days.len(), 7);
    assert_eq!(days.iter().filter(|d| d["day_type"] == "training").count(), 5);
    assert_eq!(days.iter().filter(|d| d["day_type"] == "rest").count(), 2);
    assert_eq!(program["plan_version"], 1);
    assert_eq!(program["anchor_date"], "2026-10-22");

    let planned: i64 = days
        .iter()
        .flat_map(|d| d["exercises"].as_array().cloned().unwrap_or_default())
        .filter_map(|e| e["planned_sets"].as_i64())
        .sum();
    assert_eq!(planned, 90, "90 prescribed working sets per rotation");

    for rest in ["day-4", "day-7"] {
        let rest_day = day(&program, rest);
        assert_eq!(rest_day["day_type"], "rest");
        assert_eq!(rest_day["exercises"].as_array().unwrap().len(), 0, "{rest} prescribes no sets");
    }

    // Day 2 exactly as prescribed: order, sets and rep ranges.
    let pull = day(&program, "day-2");
    assert_eq!(pull["label"], "Pull A: Lat Width + Biceps");
    let expected = [
        ("Lat Pulldown", 3, 6, 10),
        ("Chest-Supported Row", 3, 8, 12),
        ("Single-Arm Lat Pulldown", 2, 10, 15),
        ("Reverse Pec Deck", 3, 12, 20),
        ("Preacher Curl", 3, 8, 12),
        ("Hammer/Cable Curl", 2, 10, 15),
    ];
    let actual = pull["exercises"].as_array().unwrap();
    assert_eq!(actual.len(), expected.len());
    for (index, (name, sets, min, max)) in expected.iter().enumerate() {
        let e = &actual[index];
        assert_eq!(e["name"], *name, "exercise {} out of order", index + 1);
        assert_eq!(e["order"], index as i64 + 1);
        assert_eq!(
            (e["planned_sets"].as_i64(), e["min_reps"].as_i64(), e["max_reps"].as_i64()),
            (Some(*sets), Some(*min), Some(*max)),
            "{name} prescription"
        );
    }
}

#[test]
fn a_second_default_program_is_refused_and_a_restart_does_not_duplicate_it() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let h = open(dir.path(), &keys);
    cmd(&h, "gym.program.create_default", json!({}));
    let first = program(&h)["id"].as_str().unwrap().to_string();

    let err = h.command("gym.program.create_default".into(), "{}".into()).unwrap_err();
    assert_eq!(code(&err), "conflict");

    // Restart: the host drops the handle and opens the same encrypted file again.
    drop(h);
    let h = open(dir.path(), &keys);
    assert_eq!(rows(&h, "active_program", json!({})).len(), 1, "exactly one program after a restart");
    assert_eq!(program(&h)["id"].as_str().unwrap(), first, "the same program, not a fresh default");
    assert!(h.command("gym.program.create_default".into(), "{}".into()).is_err());
}

#[test]
fn editing_the_plan_makes_a_new_version_and_finished_sessions_keep_their_own_snapshot() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let program_before = program(&h);
    let program_id = program_before["id"].as_str().unwrap().to_string();

    // Finish a Day 2 workout against plan version 1.
    let session = cmd(
        &h,
        "gym.session.start",
        json!({"program_id": program_id, "day_id": "day-2",
        "started_at": "2026-10-22T17:00:00Z"}),
    )
    .aggregate_id;
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 10, "2026-10-22T17:05:00Z"));
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T17:40:00Z"}));

    // Now edit Day 2: drop the last exercise and widen the Lat Pulldown prescription.
    let mut days = program_before["days"].as_array().unwrap().clone();
    let edited = days.iter_mut().find(|d| d["day_id"] == "day-2").unwrap();
    let exercises = edited["exercises"].as_array_mut().unwrap();
    exercises.pop();
    exercises[0]["planned_sets"] = json!(4);
    exercises[0]["max_reps"] = json!(12);
    edited["label"] = json!("Pull A: Lats and Arms");
    cmd(&h, "gym.program.update", json!({"program_id": program_id, "days": days}));

    let after = program(&h);
    assert_eq!(after["plan_version"], 2, "an edit is a new plan version");
    let pull = day(&after, "day-2");
    assert_eq!(pull["label"], "Pull A: Lats and Arms");
    assert_eq!(pull["exercises"].as_array().unwrap().len(), 5);
    assert_eq!(pull["exercises"][0]["planned_sets"], 4);

    // The finished session still reports what was prescribed when it ran.
    let detail = one(&h, "session_details", json!({"session_id": session}));
    assert_eq!(detail["session"]["plan_version"], 1);
    assert_eq!(detail["session"]["label"], "Pull A: Lat Width + Biceps");
    assert_eq!(detail["session"]["plan_snapshot"]["exercises"].as_array().unwrap().len(), 6);
    assert_eq!(detail["session"]["plan_snapshot"]["exercises"][0]["planned_sets"], 3);
    assert_eq!(detail["metrics"]["planned_working_sets"], 16, "Day 2 as it was prescribed that day");
}

#[test]
fn a_rest_day_has_no_workout_to_start_and_a_broken_plan_edit_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let program = program(&h);
    let id = program["id"].as_str().unwrap().to_string();

    let err =
        h.command("gym.session.start".into(), json!({"program_id": id, "day_id": "day-4"}).to_string()).unwrap_err();
    assert_eq!(code(&err), "validation");

    let valid_days = program["days"].as_array().unwrap().clone();
    // Six days, a rest day with prescribed sets, and a training day with none: each refused whole.
    let six: Vec<Value> = valid_days.iter().take(6).cloned().collect();
    let mut rest_with_sets = valid_days.clone();
    rest_with_sets[3]["exercises"] = valid_days[0]["exercises"].clone();
    let mut training_without_sets = valid_days.clone();
    training_without_sets[0]["exercises"] = json!([]);
    for days in [json!(six), json!(rest_with_sets), json!(training_without_sets)] {
        let err =
            h.command("gym.program.update".into(), json!({"program_id": id, "days": days}).to_string()).unwrap_err();
        assert_eq!(code(&err), "validation");
    }
    let unchanged = reload(&h);
    assert_eq!(unchanged["plan_version"], 1, "a refused edit changes nothing");
    assert_eq!(day(&unchanged, "day-1")["exercises"].as_array().unwrap().len(), 7);
}

// ---------------------------------------------------------------------------------------------
// GYM-01B Live Workout

#[test]
fn only_one_workout_can_be_active_at_a_time() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let first = cmd(&h, "gym.session.start", json!({"day_id": "day-2"})).aggregate_id;

    let err = h.command("gym.session.start".into(), json!({"day_id": "day-3"}).to_string()).unwrap_err();
    assert_eq!(code(&err), "conflict");

    // Finishing the first one frees the slot.
    cmd(&h, "gym.session.complete", json!({"session_id": first}));
    let second = cmd(&h, "gym.session.start", json!({"day_id": "day-3"})).aggregate_id;
    assert_ne!(second, first);
    assert_eq!(one(&h, "active_session", json!({}))["session"]["id"], second);
}

#[test]
fn warm_up_sets_are_recorded_but_never_counted_as_working_sets() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    cmd(
        &h,
        "gym.set.add",
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "warmup",
               "weight_unit": "lb", "load_milli": 30_000, "reps": 12, "completed": true,
               "completed_at": "2026-10-22T17:02:00Z"}),
    );
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 10, "2026-10-22T17:05:00Z"));

    let metrics = one(&h, "session_details", json!({"session_id": session}))["metrics"].clone();
    assert_eq!(metrics["working_sets_completed"], 1);
    assert_eq!(metrics["warmup_sets_completed"], 1);
    // Volume counts the 55 lb x 10 only: 550 lb, in thousandths.
    assert_eq!(metrics["volume_by_unit"][0]["unit"], "lb");
    assert_eq!(metrics["volume_by_unit"][0]["volume_milli"], 550_000);
    assert_eq!(metrics["volume_by_unit"][0]["sets"], 1);
}

#[test]
fn invalid_sets_are_refused_and_leave_no_event_behind() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session = cmd(&h, "gym.session.start", json!({"day_id": "day-2"})).aggregate_id;
    let before = h.event_count().unwrap();

    let bad = [
        // A completed set without repetitions.
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "lb", "load_milli": 55_000, "completed": true}),
        // A negative load and an impossible one.
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "lb", "load_milli": -1, "reps": 10, "completed": true}),
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "lb", "load_milli": 9_000_000, "reps": 10, "completed": true}),
        // Reps out of range, RIR out of range, an unknown unit, an unknown set type.
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "lb", "load_milli": 55_000, "reps": -2, "completed": true}),
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "lb", "load_milli": 55_000, "reps": 10, "rir": 9, "completed": true}),
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "stone", "load_milli": 55_000, "reps": 10, "completed": true}),
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "drop",
               "weight_unit": "lb", "load_milli": 55_000, "reps": 10, "completed": true}),
        // A field nobody reviewed.
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "lb", "load_milli": 55_000, "reps": 10, "completed": true,
               "completed_at": "2026-10-22T17:05:00Z", "form_score": 9}),
        // A timestamp that is not UTC.
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "working",
               "weight_unit": "lb", "load_milli": 55_000, "reps": 10, "completed": true,
               "completed_at": "2026-10-22T17:05:00+02:00"}),
    ];
    for payload in bad {
        let err = h.command("gym.set.add".into(), payload.to_string()).unwrap_err();
        assert_eq!(code(&err), "validation", "{payload}");
    }
    assert_eq!(h.event_count().unwrap(), before, "a refused set writes nothing");
    assert_eq!(one(&h, "session_details", json!({"session_id": session}))["metrics"]["working_sets_completed"], 0);
}

#[test]
fn a_set_can_be_corrected_or_removed_and_rir_survives_the_round_trip() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    let mut first = working_set(&session, "lat_pulldown", 55, 10, "2026-10-22T17:05:00Z");
    first["rir"] = json!(2);
    first["notes"] = json!("Felt easy");
    let set_id = cmd(&h, "gym.set.add", first).aggregate_id;
    let second =
        cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 9, "2026-10-22T17:09:00Z")).aggregate_id;

    let detail = one(&h, "session_details", json!({"session_id": session}));
    let logged = &detail["exercises"][0]["sets"];
    assert_eq!(logged[0]["rir"], 2);
    assert_eq!(logged[0]["notes"], "Felt easy");
    assert_eq!((logged[0]["set_order"].as_i64(), logged[1]["set_order"].as_i64()), (Some(1), Some(2)));

    // Correct the first set: 50 lb x 11, RIR cleared.
    cmd(&h, "gym.set.update", json!({"set_id": set_id, "load_milli": 50_000, "reps": 11, "rir": Value::Null}));
    let detail = one(&h, "session_details", json!({"session_id": session}));
    assert_eq!(detail["exercises"][0]["sets"][0]["load_milli"], 50_000);
    assert_eq!(detail["exercises"][0]["sets"][0]["reps"], 11);
    assert!(detail["exercises"][0]["sets"][0]["rir"].is_null());

    // Remove the second one.
    cmd(&h, "gym.set.remove", json!({"set_id": second}));
    let detail = one(&h, "session_details", json!({"session_id": session}));
    assert_eq!(detail["exercises"][0]["sets"].as_array().unwrap().len(), 1);
    assert_eq!(detail["metrics"]["working_sets_completed"], 1);
    assert_eq!(detail["metrics"]["volume_by_unit"][0]["volume_milli"], 550_000, "50 lb x 11");

    // A removed set stays removed when the projections are rebuilt from the log.
    h.rebuild_projections().unwrap();
    let after = one(&h, "session_details", json!({"session_id": session}));
    assert_eq!(after["exercises"][0]["sets"].as_array().unwrap().len(), 1);
}

#[test]
fn pause_and_resume_are_recorded_so_active_duration_excludes_the_break() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.session.pause", json!({"session_id": session, "at": "2026-10-22T17:10:00Z"}));
    assert_eq!(one(&h, "active_session", json!({}))["session"]["state"], "paused");
    // Pausing twice is a conflict, not a second interval.
    assert_eq!(
        code(&h.command("gym.session.pause".into(), json!({"session_id": session}).to_string()).unwrap_err()),
        "conflict"
    );
    cmd(&h, "gym.session.resume", json!({"session_id": session, "at": "2026-10-22T17:15:00Z"}));
    assert_eq!(
        code(&h.command("gym.session.resume".into(), json!({"session_id": session}).to_string()).unwrap_err()),
        "conflict"
    );
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T18:00:00Z"}));

    let metrics = one(&h, "session_details", json!({"session_id": session}))["metrics"].clone();
    assert_eq!(metrics["elapsed_seconds"], 3_600, "17:00 to 18:00");
    assert_eq!(metrics["paused_seconds"], 300, "a five-minute break");
    assert_eq!(metrics["active_seconds"], 3_300);
}

#[test]
fn a_workout_paused_at_the_finish_tap_does_not_count_the_open_break_twice() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-3", "started_at": "2026-10-22T06:00:00Z"})).aggregate_id;
    cmd(&h, "gym.session.pause", json!({"session_id": session, "at": "2026-10-22T06:20:00Z"}));
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T06:30:00Z"}));

    let detail = one(&h, "session_details", json!({"session_id": session}));
    assert_eq!(detail["session"]["state"], "completed");
    assert_eq!(detail["metrics"]["elapsed_seconds"], 1_800);
    assert_eq!(detail["metrics"]["paused_seconds"], 600);
    assert_eq!(detail["metrics"]["active_seconds"], 1_200);
}

#[test]
fn a_workout_is_finished_once_and_a_repeated_tap_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 10, "2026-10-22T17:05:00Z"));
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T17:40:00Z"}));

    for _ in 0..3 {
        let err = h.command("gym.session.complete".into(), json!({"session_id": session}).to_string()).unwrap_err();
        assert_eq!(code(&err), "conflict");
    }
    assert_eq!(rows(&h, "list_sessions", json!({})).len(), 1, "one session, however many taps");
    assert!(rows(&h, "active_session", json!({})).is_empty());
    // Logging into a finished workout is refused too.
    assert_eq!(
        code(
            &h.command(
                "gym.set.add".into(),
                working_set(&session, "lat_pulldown", 55, 8, "2026-10-22T17:45:00Z").to_string()
            )
            .unwrap_err()
        ),
        "conflict"
    );
}

#[test]
fn an_unfinished_workout_is_recovered_after_a_restart_with_every_set_it_had() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let h = open(dir.path(), &keys);
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 10, "2026-10-22T17:05:00Z"));
    cmd(&h, "gym.session.pause", json!({"session_id": session, "at": "2026-10-22T17:07:00Z"}));
    drop(h);

    // The app was killed mid-workout. Reopening finds the same session, still paused.
    let h = open(dir.path(), &keys);
    let recovered = one(&h, "active_session", json!({}));
    assert_eq!(recovered["session"]["id"], session);
    assert_eq!(recovered["session"]["state"], "paused");
    assert_eq!(recovered["session"]["started_at"], "2026-10-22T17:00:00Z");
    assert_eq!(recovered["exercises"][0]["sets"].as_array().unwrap().len(), 1);
    assert_eq!(recovered["exercises"][0]["sets"][0]["load_milli"], 55_000);

    // And it can be carried on and finished.
    cmd(&h, "gym.session.resume", json!({"session_id": session, "at": "2026-10-22T17:12:00Z"}));
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 9, "2026-10-22T17:16:00Z"));
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T17:40:00Z"}));
    let detail = one(&h, "session_details", json!({"session_id": session}));
    assert_eq!(detail["metrics"]["working_sets_completed"], 2);
    assert_eq!(detail["metrics"]["paused_seconds"], 300);
}

// ---------------------------------------------------------------------------------------------
// GYM-01C Session Details

#[test]
fn session_details_report_only_what_was_recorded() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 10, "2026-10-22T17:05:00Z"));
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 9, "2026-10-22T17:09:00Z"));
    // One prescribed exercise was skipped entirely, and one set was logged but not completed.
    cmd(
        &h,
        "gym.set.add",
        json!({"session_id": session, "exercise_key": "preacher_curl", "set_type": "working",
               "weight_unit": "lb", "load_milli": 40_000, "reps": 8, "completed": false}),
    );
    cmd(
        &h,
        "gym.session.note",
        json!({"session_id": session, "notes": "Right elbow tight",
        "effort_note": "Felt strong"}),
    );
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T17:52:30Z"}));

    let detail = one(&h, "session_details", json!({"session_id": session}));
    let session_row = &detail["session"];
    assert_eq!(session_row["state"], "completed");
    assert_eq!(session_row["date"], "2026-10-22");
    assert_eq!(session_row["started_at"], "2026-10-22T17:00:00Z");
    assert_eq!(session_row["ended_at"], "2026-10-22T17:52:30Z");
    assert_eq!(session_row["notes"], "Right elbow tight");
    assert_eq!(session_row["effort_note"], "Felt strong");

    let metrics = &detail["metrics"];
    assert_eq!(metrics["elapsed_seconds"], 3_150);
    assert_eq!(metrics["active_seconds"], 3_150, "no pauses were recorded");
    assert_eq!(metrics["exercises_performed"], 2, "only what was actually performed");
    assert_eq!(metrics["working_sets_completed"], 2);
    assert_eq!(metrics["working_sets_pending"], 1);
    assert_eq!(metrics["planned_working_sets"], 16);
    // (55 x 10) + (55 x 9) = 1045 lb, in thousandths. The pending set contributes nothing.
    assert_eq!(metrics["volume_by_unit"][0]["volume_milli"], 1_045_000);
    assert_eq!(metrics["volume_by_unit"][0]["sets"], 2);

    // Planned against actual, per exercise.
    let pulldown =
        detail["exercises"].as_array().unwrap().iter().find(|e| e["exercise_key"] == "lat_pulldown").cloned().unwrap();
    assert_eq!(pulldown["exercise_name"], "Lat Pulldown");
    assert_eq!(pulldown["planned"]["planned_sets"], 3);
    assert_eq!(pulldown["planned"]["min_reps"], 6);
    assert_eq!(pulldown["working_sets_completed"], 2);
    assert_eq!(pulldown["sets"][0]["completed_at"], "2026-10-22T17:05:00Z");
}

#[test]
fn bodyweight_and_assisted_loads_are_kept_out_of_volume_and_units_are_never_mixed() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-5", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    // An assisted pull-up: the recorded load is assistance, not work done on a bar.
    cmd(
        &h,
        "gym.set.add",
        json!({"session_id": session, "exercise_key": "assisted_pull_up", "set_type": "working",
               "weight_unit": "lb", "load_milli": 60_000, "load_semantics": "assistance", "reps": 8,
               "completed": true, "completed_at": "2026-10-22T17:04:00Z"}),
    );
    // A bodyweight set carries no external load at all.
    cmd(
        &h,
        "gym.set.add",
        json!({"session_id": session, "exercise_key": "hanging_leg_raise", "exercise_name": "Hanging Leg Raise",
               "set_type": "working", "weight_unit": "lb", "load_semantics": "bodyweight", "reps": 15,
               "completed": true, "completed_at": "2026-10-22T17:08:00Z"}),
    );
    // Two external sets in different units stay in different totals.
    cmd(&h, "gym.set.add", working_set(&session, "cable_lateral_raise", 20, 15, "2026-10-22T17:12:00Z"));
    cmd(
        &h,
        "gym.set.add",
        json!({"session_id": session, "exercise_key": "incline_chest_press", "set_type": "working",
               "weight_unit": "kg", "load_milli": 40_000, "reps": 10, "completed": true,
               "completed_at": "2026-10-22T17:18:00Z"}),
    );

    let metrics = one(&h, "session_details", json!({"session_id": session}))["metrics"].clone();
    assert_eq!(metrics["working_sets_completed"], 4);
    assert_eq!(metrics["volume_excluded_sets"], 2, "the assisted and bodyweight sets");
    let volume = metrics["volume_by_unit"].as_array().unwrap();
    assert_eq!(volume.len(), 2, "one total per unit, never one sum");
    let kg = volume.iter().find(|v| v["unit"] == "kg").unwrap();
    let lb = volume.iter().find(|v| v["unit"] == "lb").unwrap();
    assert_eq!(kg["volume_milli"], 400_000);
    assert_eq!(lb["volume_milli"], 300_000);
}

#[test]
fn previous_performance_comes_from_a_finished_session_or_says_there_is_none() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));

    // Nothing logged yet: the Kernel invents no prior weight.
    assert!(rows(&h, "previous_performance", json!({"exercise_key": "lat_pulldown"})).is_empty());

    let first =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-15T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.set.add", working_set(&first, "lat_pulldown", 50, 10, "2026-10-15T17:05:00Z"));
    // An open session is never a previous record.
    assert!(rows(&h, "previous_performance", json!({"exercise_key": "lat_pulldown"})).is_empty());
    cmd(&h, "gym.session.complete", json!({"session_id": first, "ended_at": "2026-10-15T17:50:00Z"}));

    let previous = one(&h, "previous_performance", json!({"exercise_key": "lat_pulldown"}));
    assert_eq!(previous["session_id"], first);
    assert_eq!(previous["date"], "2026-10-15");
    assert_eq!(previous["sets"].as_array().unwrap().len(), 1);
    assert_eq!(previous["sets"][0]["load_milli"], 50_000);

    // During the next workout, that first session is still the previous record.
    let second =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    let during = one(
        &h,
        "previous_performance",
        json!({"exercise_key": "lat_pulldown",
        "before_session_id": second}),
    );
    assert_eq!(during["session_id"], first);
    // An exercise never trained has no record, and never borrows another exercise's.
    assert!(rows(&h, "previous_performance", json!({"exercise_key": "smith_squat"})).is_empty());
}

#[test]
fn a_discarded_workout_keeps_its_record_and_a_deleted_one_stays_deleted() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let h = open(dir.path(), &keys);
    cmd(&h, "gym.program.create_default", json!({}));

    let discarded =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-20T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.set.add", working_set(&discarded, "lat_pulldown", 55, 10, "2026-10-20T17:05:00Z"));
    cmd(&h, "gym.session.discard", json!({"session_id": discarded, "ended_at": "2026-10-20T17:06:00Z"}));
    let detail = one(&h, "session_details", json!({"session_id": discarded}));
    assert_eq!(detail["session"]["state"], "discarded");
    assert_eq!(detail["exercises"][0]["sets"].as_array().unwrap().len(), 1, "the sets are still there");
    assert!(rows(&h, "active_session", json!({})).is_empty(), "a discarded workout is not active");
    // It is not a previous record either.
    assert!(rows(&h, "previous_performance", json!({"exercise_key": "lat_pulldown"})).is_empty());
    // And nothing more can be logged into it.
    assert_eq!(
        code(
            &h.command(
                "gym.set.add".into(),
                working_set(&discarded, "lat_pulldown", 55, 9, "2026-10-20T17:10:00Z").to_string()
            )
            .unwrap_err()
        ),
        "conflict"
    );

    let deleted =
        cmd(&h, "gym.session.start", json!({"day_id": "day-3", "started_at": "2026-10-21T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.set.add", working_set(&deleted, "smith_squat", 135, 8, "2026-10-21T17:05:00Z"));
    cmd(&h, "gym.session.complete", json!({"session_id": deleted, "ended_at": "2026-10-21T17:50:00Z"}));
    cmd(&h, "gym.session.delete", json!({"session_id": deleted}));
    assert_eq!(
        code(&h.query("session_details".into(), json!({"session_id": deleted}).to_string()).unwrap_err()),
        "not_found"
    );

    // A rebuild and a restart must not bring a deleted workout back.
    h.rebuild_projections().unwrap();
    assert!(h.query("session_details".into(), json!({"session_id": deleted}).to_string()).is_err());
    drop(h);
    let h = open(dir.path(), &keys);
    assert!(h.query("session_details".into(), json!({"session_id": deleted}).to_string()).is_err());
    let listed = rows(&h, "list_sessions", json!({}));
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0]["id"], discarded);
}

#[test]
fn unknown_sessions_sets_and_queries_are_refused_without_inventing_a_record() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    let session = cmd(&h, "gym.session.start", json!({"day_id": "day-2"})).aggregate_id;

    for (kind, payload) in [
        ("gym.session.complete", json!({"session_id": "11111111-2222-3333-4444-555555555555"})),
        ("gym.set.update", json!({"set_id": "11111111-2222-3333-4444-555555555555", "reps": 5})),
        ("gym.set.remove", json!({"set_id": "11111111-2222-3333-4444-555555555555"})),
        (
            "gym.set.add",
            json!({"session_id": "11111111-2222-3333-4444-555555555555",
            "exercise_key": "lat_pulldown", "exercise_name": "Lat Pulldown", "set_type": "working",
            "weight_unit": "lb", "load_milli": 55_000, "reps": 10, "completed": false}),
        ),
    ] {
        let err = h.command(kind.into(), payload.to_string()).unwrap_err();
        assert_eq!(code(&err), "not_found", "{kind}");
    }
    // An exercise outside the plan snapshot must name itself; it cannot borrow a name.
    let err = h
        .command(
            "gym.set.add".into(),
            json!({"session_id": session, "exercise_key": "barbell_curl", "set_type": "working",
                   "weight_unit": "lb", "load_milli": 40_000, "reps": 10, "completed": false})
            .to_string(),
        )
        .unwrap_err();
    assert_eq!(code(&err), "validation");
    assert_eq!(code(&h.query("gym_progress".into(), "{}".into()).unwrap_err()), "validation");
}

#[test]
fn the_gym_projections_rebuild_to_the_same_state_and_the_digest_covers_them() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    cmd(&h, "gym.program.create_default", json!({}));
    // A health record and a gym session share the domain file and the same event log.
    cmd(&h, "sleep.log", json!({"date": "2026-10-22", "duration_minutes": 440}));
    let session =
        cmd(&h, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"})).aggregate_id;
    cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, 10, "2026-10-22T17:05:00Z"));
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T17:40:00Z"}));

    let before_details = one(&h, "session_details", json!({"session_id": session}));
    let before_digest = h.projection_digest().unwrap();
    let before_health = h.query("daily_summary".into(), json!({"date": "2026-10-22"}).to_string()).unwrap().rows_json;

    let replayed = h.rebuild_projections().unwrap();
    assert!(replayed >= 5, "every event replays: {replayed}");
    assert_eq!(h.projection_digest().unwrap(), before_digest, "the digest covers gym rows");
    assert_eq!(one(&h, "session_details", json!({"session_id": session})), before_details);
    assert_eq!(
        h.query("daily_summary".into(), json!({"date": "2026-10-22"}).to_string()).unwrap().rows_json,
        before_health,
        "the health records are untouched"
    );
    assert_eq!(h.integrity_check().unwrap(), "ok");
    assert_eq!(h.schema_version().unwrap(), 3, "the gym tables are migration v3 of the health domain");
}

#[test]
fn the_gym_commands_are_registered_and_carry_no_forbidden_capability() {
    const FORBIDDEN: &[&str] = &[
        "diagnose",
        "diagnosis",
        "dose",
        "dosing",
        "prescribe",
        "treatment",
        "payment",
        "transfer",
        "purchase",
        "buy",
        "login",
        "credential",
        "password",
        "shell",
        "recommend",
        "score",
    ];
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    let names = h.command_names();
    for expected in [
        "gym.program.create_default",
        "gym.program.update",
        "gym.session.start",
        "gym.session.pause",
        "gym.session.resume",
        "gym.session.complete",
        "gym.set.add",
        "gym.set.update",
        "gym.set.remove",
    ] {
        assert!(names.iter().any(|n| n == expected), "{expected} is not registered");
    }
    // The health record commands are still there.
    assert!(names.iter().any(|n| n == "workout.log"));
    for name in &names {
        for token in name.split(['.', '_']) {
            assert!(!FORBIDDEN.contains(&token), "{name} contains {token:?}");
        }
    }
}

// ---------------------------------------------------------------------------------------------
// The required end-to-end proof, on fictional data: Day 2 Pull A, Lat Pulldown 55 lb for
// 10, 9 and 8, paused and resumed, finished once, read back, and read again after a restart.

#[test]
fn end_to_end_day_two_lat_pulldown_survives_a_restart_without_loss_or_duplication() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let h = open(dir.path(), &keys);

    // 1-2. Open the Training Plan: it is created once, on first use.
    cmd(&h, "gym.program.create_default", json!({"anchor_date": "2026-10-22"}));
    let program = program(&h);

    // 3. Select Day 2 - Pull A.
    let pull = day(&program, "day-2");
    assert_eq!(pull["label"], "Pull A: Lat Width + Biceps");
    assert_eq!(pull["exercises"][0]["name"], "Lat Pulldown");

    // 4. Start the workout.
    let session = cmd(
        &h,
        "gym.session.start",
        json!({"program_id": program["id"], "day_id": "day-2",
        "started_at": "2026-10-22T17:00:00Z"}),
    )
    .aggregate_id;

    // 5-8. Log three completed working sets of 55 lb for 10, 9 and 8.
    let logged: Vec<String> = [(10, "17:05:00"), (9, "17:09:30"), (8, "17:14:00")]
        .iter()
        .map(|(reps, at)| {
            cmd(&h, "gym.set.add", working_set(&session, "lat_pulldown", 55, *reps, &format!("2026-10-22T{at}Z")))
                .aggregate_id
        })
        .collect();
    assert_eq!(logged.len(), 3);

    // 9. The commits are in the Kernel's own file, before anything is shown as saved.
    let live = one(&h, "active_session", json!({}));
    let sets = live["exercises"][0]["sets"].as_array().unwrap().clone();
    assert_eq!(sets.len(), 3);
    for (index, reps) in [10, 9, 8].iter().enumerate() {
        assert_eq!(sets[index]["load_milli"], 55_000, "set {} load", index + 1);
        assert_eq!(sets[index]["reps"], *reps);
        assert_eq!(sets[index]["set_type"], "working");
        assert_eq!(sets[index]["weight_unit"], "lb");
        assert_eq!(sets[index]["completed"], true);
        assert_eq!(sets[index]["set_order"], index as i64 + 1);
    }

    // 10. Pause and resume.
    cmd(&h, "gym.session.pause", json!({"session_id": session, "at": "2026-10-22T17:16:00Z"}));
    cmd(&h, "gym.session.resume", json!({"session_id": session, "at": "2026-10-22T17:19:00Z"}));

    // 11. Finish the workout.
    cmd(&h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T17:45:00Z"}));

    // 12-13. Session Details holds exactly those three sets.
    let expect_details = |detail: &Value, label: &str| {
        assert_eq!(detail["session"]["state"], "completed", "{label}");
        assert_eq!(detail["session"]["date"], "2026-10-22", "{label}");
        assert_eq!(detail["session"]["started_at"], "2026-10-22T17:00:00Z", "{label}");
        assert_eq!(detail["session"]["ended_at"], "2026-10-22T17:45:00Z", "{label}");
        assert_eq!(detail["metrics"]["working_sets_completed"], 3, "{label}");
        assert_eq!(detail["metrics"]["warmup_sets_completed"], 0, "{label}");
        assert_eq!(detail["metrics"]["elapsed_seconds"], 2_700, "{label}");
        assert_eq!(detail["metrics"]["paused_seconds"], 180, "{label}");
        assert_eq!(detail["metrics"]["active_seconds"], 2_520, "{label}");
        // 55 x (10 + 9 + 8) = 1485 lb.
        assert_eq!(detail["metrics"]["volume_by_unit"][0]["unit"], "lb", "{label}");
        assert_eq!(detail["metrics"]["volume_by_unit"][0]["volume_milli"], 1_485_000, "{label}");
        let sets = detail["exercises"][0]["sets"].as_array().unwrap();
        assert_eq!(sets.len(), 3, "{label}: three sets, no duplicates");
        assert_eq!(detail["exercises"].as_array().unwrap().len(), 1, "{label}: one exercise performed");
        for (index, (reps, at)) in [(10, "17:05:00"), (9, "17:09:30"), (8, "17:14:00")].iter().enumerate() {
            assert_eq!(sets[index]["reps"], *reps, "{label}: set {} reps", index + 1);
            assert_eq!(sets[index]["load_milli"], 55_000, "{label}: set {} load", index + 1);
            assert_eq!(sets[index]["completed_at"], format!("2026-10-22T{at}Z"), "{label}");
        }
    };
    let before = one(&h, "session_details", json!({"session_id": session}));
    expect_details(&before, "before the restart");

    // 14-16. Restart: close the domain file and open it again from disk.
    drop(h);
    let h = open(dir.path(), &keys);
    let after = one(&h, "session_details", json!({"session_id": session}));
    expect_details(&after, "after the restart");
    assert_eq!(before, after, "the receipt is byte-for-byte the same after a restart");
    assert_eq!(rows(&h, "list_sessions", json!({})).len(), 1, "one session, not two");
    assert_eq!(rows(&h, "active_program", json!({})).len(), 1, "one program, not two");
    assert!(rows(&h, "active_session", json!({})).is_empty(), "nothing is still open");

    // The next workout sees this one as its previous record.
    let previous = one(&h, "previous_performance", json!({"exercise_key": "lat_pulldown"}));
    assert_eq!(previous["sets"].as_array().unwrap().len(), 3);
    assert_eq!(previous["sets"][2]["reps"], 8);
    assert_eq!(h.integrity_check().unwrap(), "ok");
}
