//! GYM-02: a completed workout survives the Health backup, a restore into a fresh encrypted
//! store, and a repeated import, with no loss and no duplication.

mod common;

use std::path::Path;
use std::sync::Arc;

use common::{code, MemKeys};
use reva_kernel::{open_domain, DomainHandle, ImportReport};
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

fn backup(h: &DomainHandle) -> Vec<u8> {
    h.export("json".into()).expect("health backup")
}

fn import(h: &DomainHandle, bytes: &[u8]) -> ImportReport {
    h.import_data("json".into(), bytes.to_vec(), "{}".into()).expect("import")
}

fn statuses(report: &ImportReport) -> Vec<String> {
    serde_json::from_str::<Value>(&report.rows_json)
        .unwrap()
        .as_array()
        .unwrap()
        .iter()
        .map(|r| r["status"].as_str().unwrap_or_default().to_string())
        .collect()
}

/// One completed working set, load in thousandths of the unit.
fn set(session: &str, exercise: &str, load_milli: i64, unit: &str, reps: i64, at: &str) -> Value {
    json!({
        "session_id": session,
        "exercise_key": exercise,
        "set_type": "working",
        "weight_unit": unit,
        "load_milli": load_milli,
        "reps": reps,
        "completed": true,
        "completed_at": at,
    })
}

/// The device whose data is being backed up: one edited program, one finished Pull A workout with
/// a warm-up and three working sets, one workout that was deleted, and one health record.
fn seed(h: &DomainHandle) -> String {
    cmd(h, "gym.program.create_default", json!({"anchor_date": "2026-10-22"}));
    cmd(h, "sleep.log", json!({"date": "2026-10-22", "duration_minutes": 430}));
    let program = one(h, "active_program", json!({}));
    let program_id = program["id"].as_str().unwrap().to_string();

    // A plan edit, so the restored device must carry plan version 2 as well as the session's
    // snapshot of version 1.
    let session = cmd(
        h,
        "gym.session.start",
        json!({"program_id": program_id, "day_id": "day-2", "started_at": "2026-10-22T17:00:00Z"}),
    )
    .aggregate_id;
    cmd(
        h,
        "gym.set.add",
        json!({"session_id": session, "exercise_key": "lat_pulldown", "set_type": "warmup",
               "weight_unit": "lb", "load_milli": 30_000, "reps": 12, "completed": true,
               "completed_at": "2026-10-22T17:02:00Z"}),
    );
    for (reps, at) in [(10, "17:05:00"), (9, "17:09:30"), (8, "17:14:00")] {
        cmd(h, "gym.set.add", set(&session, "lat_pulldown", 55_000, "lb", reps, &format!("2026-10-22T{at}Z")));
    }
    // A 52.5 lb step and a kg set, so a restore has to keep both the fraction and the unit.
    cmd(h, "gym.set.add", set(&session, "preacher_curl", 52_500, "lb", 11, "2026-10-22T17:20:00Z"));
    cmd(h, "gym.set.add", set(&session, "hammer_cable_curl", 18_000, "kg", 12, "2026-10-22T17:26:00Z"));
    cmd(
        h,
        "gym.set.add",
        json!({"session_id": session, "exercise_key": "reverse_pec_deck", "set_type": "working",
               "weight_unit": "lb", "load_semantics": "bodyweight", "reps": 15, "completed": true,
               "completed_at": "2026-10-22T17:30:00Z", "notes": "Slow negatives"}),
    );
    cmd(h, "gym.session.pause", json!({"session_id": session, "at": "2026-10-22T17:16:00Z"}));
    cmd(h, "gym.session.resume", json!({"session_id": session, "at": "2026-10-22T17:19:00Z"}));
    cmd(
        h,
        "gym.session.note",
        json!({"session_id": session, "notes": "Right elbow tight", "effort_note": "Felt strong"}),
    );
    cmd(h, "gym.session.complete", json!({"session_id": session, "ended_at": "2026-10-22T17:45:00Z"}));

    // A workout started, logged and then deleted: it must stay deleted everywhere.
    let discarded = cmd(
        h,
        "gym.session.start",
        json!({"program_id": program_id, "day_id": "day-3", "started_at": "2026-10-21T06:00:00Z"}),
    )
    .aggregate_id;
    cmd(h, "gym.set.add", set(&discarded, "smith_squat", 135_000, "lb", 8, "2026-10-21T06:10:00Z"));
    cmd(h, "gym.session.complete", json!({"session_id": discarded, "ended_at": "2026-10-21T06:40:00Z"}));
    cmd(h, "gym.session.delete", json!({"session_id": discarded}));

    let mut days = program["days"].as_array().unwrap().clone();
    days.iter_mut().find(|d| d["day_id"] == "day-2").unwrap()["label"] = json!("Pull A: Lats and Arms");
    cmd(h, "gym.program.update", json!({"program_id": program_id, "days": days}));

    session
}

/// Everything a restored device must be able to answer about gym training, read through the
/// Kernel's own queries rather than its tables.
fn gym_state(h: &DomainHandle, session: &str) -> Value {
    json!({
        "program": one(h, "active_program", json!({})),
        "day": one(h, "program_day", json!({"day_id": "day-2"})),
        "details": one(h, "session_details", json!({"session_id": session})),
        "sessions": rows(h, "list_sessions", json!({})),
        "previous_pulldown": rows(h, "previous_performance", json!({"exercise_key": "lat_pulldown"})),
        "previous_curl": rows(h, "previous_performance", json!({"exercise_key": "preacher_curl"})),
        "active": rows(h, "active_session", json!({})),
    })
}

#[test]
fn a_completed_workout_survives_export_restore_and_a_repeated_import() {
    let (a_dir, b_dir) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let keys = MemKeys::new();
    let a = open(a_dir.path(), &keys);
    let session = seed(&a);

    let file = backup(&a);
    let parsed: Value = serde_json::from_slice(&file).unwrap();
    assert_eq!(parsed["format"], "reva-health-v2");
    assert_eq!(parsed["records"].as_array().unwrap().len(), 1, "the sleep record");
    let gym = &parsed["gym"];
    assert_eq!(gym["programs"].as_array().unwrap().len(), 1);
    assert_eq!(gym["sessions"].as_array().unwrap().len(), 1, "the deleted workout is not in the file");
    assert_eq!(gym["sets"].as_array().unwrap().len(), 7);
    assert_eq!(gym["deleted"].as_array().unwrap().len(), 2, "the deleted session and its set");

    // A fresh encrypted store: a new install, its own key and its own data file.
    let b = open(b_dir.path(), &keys);
    assert!(rows(&b, "active_program", json!({})).is_empty());

    let dry = b.import_data("json".into(), file.clone(), r#"{"dry_run":true}"#.into()).unwrap();
    assert!(dry.dry_run);
    // 1 sleep record + 1 program + 1 session + 7 sets + the 2 deletions the file records.
    assert_eq!(dry.accepted, 12);
    assert_eq!(b.event_count().unwrap(), 0, "a dry run commits nothing");

    let report = import(&b, &file);
    assert_eq!((report.accepted, report.duplicates, report.rejected.len()), (12, 0, 0));
    assert_eq!(statuses(&report).len(), 12, "every row of the file is accounted for once");

    // Deep comparison: every gym answer, the projection digest and the health summary.
    assert_eq!(gym_state(&a, &session), gym_state(&b, &session), "restored gym state differs");
    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());
    assert_eq!(
        a.query("daily_summary".into(), json!({"date": "2026-10-22"}).to_string()).unwrap().rows_json,
        b.query("daily_summary".into(), json!({"date": "2026-10-22"}).to_string()).unwrap().rows_json,
    );

    // Importing the same file again changes nothing at all.
    let digest_before = b.projection_digest().unwrap();
    let events_before = b.event_count().unwrap();
    let again = import(&b, &file);
    assert_eq!((again.accepted, again.duplicates, again.rejected.len()), (0, 12, 0));
    assert_eq!(b.projection_digest().unwrap(), digest_before);
    assert_eq!(b.event_count().unwrap(), events_before, "a repeated import writes no event");
    assert_eq!(rows(&b, "list_sessions", json!({})).len(), 1, "one session, not two");
    assert_eq!(rows(&b, "active_program", json!({})).len(), 1, "one program, not two");
    assert_eq!(gym_state(&a, &session), gym_state(&b, &session));

    // And a third import, after a projection rebuild, still holds.
    b.rebuild_projections().unwrap();
    let third = import(&b, &file);
    assert_eq!((third.accepted, third.duplicates), (0, 12));
    assert_eq!(b.projection_digest().unwrap(), digest_before);
    assert_eq!(b.integrity_check().unwrap(), "ok");
}

#[test]
fn the_pull_a_session_keeps_its_exact_loads_reps_and_1485_lb_through_a_restore() {
    let (a_dir, b_dir) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let keys = MemKeys::new();
    let a = open(a_dir.path(), &keys);
    let session = seed(&a);

    let b = open(b_dir.path(), &keys);
    import(&b, &backup(&a));

    let detail = one(&b, "session_details", json!({"session_id": session}));
    assert_eq!(detail["session"]["state"], "completed");
    assert_eq!(detail["session"]["label"], "Pull A: Lat Width + Biceps", "the session keeps its own snapshot");
    assert_eq!(detail["session"]["plan_version"], 1, "even though the program is now version 2");
    assert_eq!(detail["session"]["date"], "2026-10-22");
    assert_eq!(detail["session"]["started_at"], "2026-10-22T17:00:00Z");
    assert_eq!(detail["session"]["ended_at"], "2026-10-22T17:45:00Z");
    assert_eq!(detail["session"]["notes"], "Right elbow tight");
    assert_eq!(detail["session"]["effort_note"], "Felt strong");

    let metrics = &detail["metrics"];
    assert_eq!(metrics["elapsed_seconds"], 2_700);
    assert_eq!(metrics["paused_seconds"], 180, "the pause interval survived");
    assert_eq!(metrics["active_seconds"], 2_520);
    assert_eq!(metrics["working_sets_completed"], 6);
    assert_eq!(metrics["warmup_sets_completed"], 1, "the warm-up is still a warm-up");
    assert_eq!(metrics["volume_excluded_sets"], 1, "the bodyweight set is still excluded");

    // 55 lb x (10 + 9 + 8) = 1485 lb, plus the 52.5 lb set; kg is totalled apart.
    let volume = metrics["volume_by_unit"].as_array().unwrap();
    let lb = volume.iter().find(|v| v["unit"] == "lb").unwrap();
    let kg = volume.iter().find(|v| v["unit"] == "kg").unwrap();
    assert_eq!(lb["volume_milli"], 1_485_000 + 52_500 * 11);
    assert_eq!(kg["volume_milli"], 18_000 * 12);

    let pulldown =
        detail["exercises"].as_array().unwrap().iter().find(|e| e["exercise_key"] == "lat_pulldown").cloned().unwrap();
    assert_eq!(pulldown["exercise_name"], "Lat Pulldown");
    assert_eq!(pulldown["equipment"], "Cable", "the equipment variant survived");
    assert_eq!(pulldown["working_sets_completed"], 3);
    let working: Vec<&Value> =
        pulldown["sets"].as_array().unwrap().iter().filter(|s| s["set_type"] == "working").collect();
    assert_eq!(working.len(), 3);
    for (index, (reps, at)) in [(10, "17:05:00"), (9, "17:09:30"), (8, "17:14:00")].iter().enumerate() {
        assert_eq!(working[index]["load_milli"], 55_000, "set {} load", index + 1);
        assert_eq!(working[index]["weight_unit"], "lb");
        assert_eq!(working[index]["reps"], *reps);
        assert_eq!(working[index]["completed_at"], format!("2026-10-22T{at}Z"));
        // The warm-up holds set_order 1 for this exercise, so the working sets are 2, 3 and 4.
        assert_eq!(working[index]["set_order"], index as i64 + 2);
    }
    // The 1485 lb headline on its own, as the Session Details screen reports it.
    let three: i64 = working.iter().map(|s| s["load_milli"].as_i64().unwrap() * s["reps"].as_i64().unwrap()).sum();
    assert_eq!(three, 1_485_000, "55 lb x 10, 9 and 8 is 1485 lb");

    // The fractional step and the kg set kept their exact values.
    let curl = detail["exercises"].as_array().unwrap().iter().find(|e| e["exercise_key"] == "preacher_curl").unwrap();
    assert_eq!(curl["sets"][0]["load_milli"], 52_500, "52.5 lb is not rounded");
    let hammer =
        detail["exercises"].as_array().unwrap().iter().find(|e| e["exercise_key"] == "hammer_cable_curl").unwrap();
    assert_eq!(hammer["sets"][0]["weight_unit"], "kg");
    let bodyweight =
        detail["exercises"].as_array().unwrap().iter().find(|e| e["exercise_key"] == "reverse_pec_deck").unwrap();
    assert_eq!(bodyweight["sets"][0]["load_semantics"], "bodyweight");
    assert_eq!(bodyweight["sets"][0]["notes"], "Slow negatives");
}

#[test]
fn a_deleted_workout_is_not_brought_back_and_a_restore_never_deletes_one() {
    let (a_dir, b_dir, c_dir) =
        (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let keys = MemKeys::new();
    let a = open(a_dir.path(), &keys);
    let session = seed(&a);
    let early = backup(&a);

    // B restores, so it learns about the deletion as well as the kept workout.
    let b = open(b_dir.path(), &keys);
    let report = import(&b, &early);
    assert_eq!(report.rejected.len(), 0);
    assert_eq!(rows(&b, "list_sessions", json!({})).len(), 1);

    // A deletes the Pull A workout and backs up again.
    cmd(&a, "gym.session.delete", json!({"session_id": session}));
    assert!(rows(&a, "list_sessions", json!({})).is_empty());
    let later = backup(&a);
    let parsed: Value = serde_json::from_slice(&later).unwrap();
    assert_eq!(parsed["gym"]["sessions"].as_array().unwrap().len(), 0);
    assert_eq!(parsed["gym"]["deleted"].as_array().unwrap().len(), 10, "both workouts and every set");

    // Restoring the newer file onto B does NOT delete the workout B still holds: a restore is
    // never a way to destroy data. It is reported instead.
    let onto_b = import(&b, &later);
    assert_eq!(rows(&b, "list_sessions", json!({})).len(), 1, "B still has its workout");
    let refusals: Vec<String> = onto_b.rejected.iter().map(|r| r.reason.clone()).collect();
    assert!(refusals.iter().any(|r| r.contains("restoring a backup never deletes a workout")), "{refusals:?}");

    // A fresh device restoring the newer file simply never sees the deleted workouts.
    let c = open(c_dir.path(), &keys);
    let onto_c = import(&c, &later);
    assert_eq!(onto_c.rejected.len(), 0);
    assert!(rows(&c, "list_sessions", json!({})).is_empty());
    assert_eq!(
        code(&c.query("session_details".into(), json!({"session_id": session}).to_string()).unwrap_err()),
        "not_found"
    );

    // And the older file, which still holds that workout, cannot bring it back on C.
    let older = import(&c, &early);
    assert!(rows(&c, "list_sessions", json!({})).is_empty(), "a tombstoned workout stays deleted");
    let reasons: Vec<String> = older.rejected.iter().map(|r| r.reason.clone()).collect();
    assert!(reasons.iter().any(|r| r.contains("deleted on this device")), "{reasons:?}");
    c.rebuild_projections().unwrap();
    assert!(rows(&c, "list_sessions", json!({})).is_empty(), "and stays deleted after a rebuild");
}

#[test]
fn a_backup_written_before_gym_training_still_restores() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new());
    // Exactly what the previous format looked like: health records, no gym key.
    let v1 = json!({
        "format": "reva-health-v1",
        "records": [{
            "id": "11111111-2222-3333-4444-555555555555",
            "kind": "workout",
            "date": "2026-10-16",
            "created_at": "2026-10-16T18:00:00.000Z",
            "activity": "Walk",
            "duration_minutes": 35,
        }],
    });
    let report = import(&h, v1.to_string().as_bytes());
    assert_eq!((report.accepted, report.duplicates, report.rejected.len()), (1, 0, 0));
    assert_eq!(one(&h, "daily_summary", json!({"date": "2026-10-16"}))["workout_minutes"], 35);
    assert!(rows(&h, "active_program", json!({})).is_empty(), "a v1 file carries no gym training");

    // Re-importing it is all duplicates, as before.
    let again = import(&h, v1.to_string().as_bytes());
    assert_eq!((again.accepted, again.duplicates), (0, 1));

    // A v1 file that claims to carry gym training is refused rather than half-read.
    let mixed = json!({"format": "reva-health-v1", "records": [], "gym": {"programs": []}});
    let error = h.import_data("json".into(), mixed.to_string().into_bytes(), "{}".into()).unwrap_err();
    assert_eq!(code(&error), "validation");
}

#[test]
fn a_hand_edited_gym_backup_is_refused_record_by_record() {
    let (a_dir, b_dir) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let keys = MemKeys::new();
    let a = open(a_dir.path(), &keys);
    let session = seed(&a);
    let file: Value = serde_json::from_slice(&backup(&a)).unwrap();

    let b = open(b_dir.path(), &keys);
    let mut broken = file.clone();
    let sets = broken["gym"]["sets"].as_array_mut().unwrap();
    // A load nobody can lift, a rep count that is not a number, a set type nobody reviewed, and a
    // completed set with no repetitions.
    sets[0]["load_milli"] = json!(9_000_000);
    sets[1]["reps"] = json!("ten");
    sets[2]["set_type"] = json!("drop");
    sets[3].as_object_mut().unwrap().remove("reps");
    // A session whose end is before its start.
    broken["gym"]["sessions"][0]["ended_at"] = json!("2026-10-22T16:00:00Z");
    // A field nobody reviewed on the program.
    broken["gym"]["programs"][0]["coach_score"] = json!(9);

    let report = import(&b, broken.to_string().as_bytes());
    assert_eq!(report.accepted, 6, "the sleep record, the three sound sets and the two deletions");
    assert_eq!(report.rejected.len(), 6);
    assert!(report.rejected.iter().all(|r| !r.reason.is_empty()));
    assert!(rows(&b, "active_program", json!({})).is_empty(), "the broken program was not written");
    assert_eq!(
        code(&b.query("session_details".into(), json!({"session_id": session}).to_string()).unwrap_err()),
        "not_found",
        "the broken session was not written",
    );

    // The file is refused as a whole only when its shape is wrong, not its contents.
    for bad in [
        json!({"format": "reva-health-v2", "records": [], "gym": {"programs": [], "extra": []}}),
        json!({"format": "reva-health-v2", "records": [], "gym": {"sets": 7}}),
        json!({"format": "reva-health-v2", "records": [], "gym": []}),
    ] {
        let error = b.import_data("json".into(), bad.to_string().into_bytes(), "{}".into()).unwrap_err();
        assert_eq!(code(&error), "validation", "{bad}");
    }

    // A sound file still restores into the same store afterwards.
    let good = import(&b, &backup(&a));
    assert_eq!(good.rejected.len(), 0);
    assert_eq!(one(&b, "session_details", json!({"session_id": session}))["metrics"]["working_sets_completed"], 6);
}

#[test]
fn a_restored_device_can_carry_on_training_from_the_backup() {
    let (a_dir, b_dir) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let keys = MemKeys::new();
    let a = open(a_dir.path(), &keys);
    seed(&a);

    let b = open(b_dir.path(), &keys);
    import(&b, &backup(&a));

    // The restored workout is the previous record the next session reads.
    let previous = one(&b, "previous_performance", json!({"exercise_key": "lat_pulldown"}));
    assert_eq!(previous["sets"].as_array().unwrap().len(), 3);
    assert_eq!(previous["sets"][2]["reps"], 8);

    // A second default program is still refused, and the restored one is still editable.
    assert_eq!(code(&b.command("gym.program.create_default".into(), "{}".into()).unwrap_err()), "conflict");
    let program = one(&b, "active_program", json!({}));
    assert_eq!(program["plan_version"], 2, "the edit that was made before the backup");
    assert_eq!(one(&b, "program_day", json!({"day_id": "day-2"}))["day"]["label"], "Pull A: Lats and Arms");

    // And a new workout runs normally on the restored device.
    let next =
        cmd(&b, "gym.session.start", json!({"day_id": "day-2", "started_at": "2026-10-29T17:00:00Z"})).aggregate_id;
    cmd(&b, "gym.set.add", set(&next, "lat_pulldown", 57_500, "lb", 10, "2026-10-29T17:05:00Z"));
    cmd(&b, "gym.session.complete", json!({"session_id": next, "ended_at": "2026-10-29T17:40:00Z"}));
    assert_eq!(rows(&b, "list_sessions", json!({})).len(), 2);
    let newest = one(&b, "previous_performance", json!({"exercise_key": "lat_pulldown"}));
    assert_eq!(newest["session_id"], next);
    assert_eq!(newest["sets"][0]["load_milli"], 57_500);
}

/// How many programs a device holds, read from its own backup file (no query lists them all).
fn program_count(h: &DomainHandle) -> usize {
    let file: Value = serde_json::from_slice(&backup(h)).unwrap();
    file["gym"]["programs"].as_array().unwrap().len()
}

#[test]
fn restoring_onto_a_device_with_its_own_plan_never_leaves_two_active_plans() {
    let (a_dir, b_dir) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let keys = MemKeys::new();
    let a = open(a_dir.path(), &keys);
    seed(&a);
    let file = backup(&a);

    // B has been used: it created its own default plan before the restore.
    let b = open(b_dir.path(), &keys);
    cmd(&b, "gym.program.create_default", json!({"anchor_date": "2026-11-01"}));
    let own_plan = one(&b, "active_program", json!({}))["id"].as_str().unwrap().to_string();
    let digest = b.projection_digest().unwrap();
    let events = b.event_count().unwrap();

    for options in ["{}", r#"{"dry_run":true}"#] {
        let error = b.import_data("json".into(), file.clone(), options.into()).unwrap_err();
        assert_eq!(code(&error), "conflict");
        assert!(error.to_string().contains("already has a training plan"), "{error}");
        assert_eq!(b.projection_digest().unwrap(), digest, "a refused backup changes no records");
        assert_eq!(b.event_count().unwrap(), events, "a refused backup writes no events");
    }
    assert_eq!(program_count(&b), 1, "a restore must not add a second active plan");
    assert_eq!(one(&b, "active_program", json!({}))["id"], own_plan, "the device keeps its own plan");
    assert!(rows(&b, "list_sessions", json!({})).is_empty(), "no workout from the refused backup is imported");
    let on_device: Value = serde_json::from_slice(&backup(&b)).unwrap();
    assert!(on_device["records"].as_array().unwrap().is_empty(), "no Health row is imported");
}

/// Import report rows counted by what they describe.
fn kinds(report: &ImportReport) -> std::collections::BTreeMap<String, usize> {
    let mut counts = std::collections::BTreeMap::new();
    for row in serde_json::from_str::<Value>(&report.rows_json).unwrap().as_array().unwrap() {
        *counts.entry(row["description"].as_str().unwrap_or("?").to_string()).or_insert(0) += 1;
    }
    counts
}

/// GYM-02 listed 11 gym entries in the file and reported 12 imports. Both were right: the 11 were
/// only the gym section, and the 12th was the sleep record. Two of the 12 were deletions, which
/// were reported under the same name as the records they delete. This pins the whole breakdown.
#[test]
fn the_twelve_imported_rows_are_ten_records_and_two_deletions_and_say_so() {
    let (a_dir, b_dir) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let keys = MemKeys::new();
    let a = open(a_dir.path(), &keys);
    seed(&a);
    let file = backup(&a);

    let parsed: Value = serde_json::from_slice(&file).unwrap();
    let listed_gym = ["programs", "sessions", "sets", "deleted"]
        .iter()
        .map(|k| parsed["gym"][*k].as_array().unwrap().len())
        .sum::<usize>();
    let listed_health = parsed["records"].as_array().unwrap().len();
    assert_eq!((listed_gym, listed_health), (11, 1), "11 gym entries plus the 1 health record");

    let b = open(b_dir.path(), &keys);
    let report = import(&b, &file);
    assert_eq!(report.accepted, 12, "11 + 1");
    let counts = kinds(&report);
    let expected: std::collections::BTreeMap<String, usize> = [
        ("sleep", 1),
        ("gym_program", 1),
        ("gym_session", 1),
        ("gym_set", 7),
        ("gym_session.deleted", 1),
        ("gym_set.deleted", 1),
    ]
    .iter()
    .map(|(k, v)| (k.to_string(), *v))
    .collect();
    assert_eq!(counts, expected);
    let deletions: usize = counts.iter().filter(|(k, _)| k.ends_with(".deleted")).map(|(_, v)| v).sum();
    assert_eq!(counts.values().sum::<usize>() - deletions, 10, "ten restored records");
    assert_eq!(deletions, 2, "and two deletions");

    // Repeated, the same twelve rows are all duplicates and are still named by kind.
    let again = import(&b, &file);
    assert_eq!((again.accepted, again.duplicates), (0, 12));
    assert_eq!(kinds(&again), expected);
}
