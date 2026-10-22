//! Gym training inside the Health domain: a seven-day training program and the workout
//! sessions logged against it. Same encrypted domain file, same event log, same projections
//! rebuild as every other Health record (ADR-028, AR-DOM-015).
//!
//! What the Kernel owns here, so that Windows and Android never compute it twice:
//! * every validation rule (load, reps, RIR, set type, session state transitions),
//! * the default program and its versioning,
//! * active and total session duration from recorded timestamps and pause intervals,
//! * working-set counts and working-set volume, with warm-ups excluded.
//!
//! Deliberate limits: a warm-up set never counts toward prescribed or performed working sets;
//! bodyweight and assisted loads are recorded but kept out of volume totals; lb and kg are
//! never summed together; a completed session is finalized once, so a repeated tap is a
//! conflict rather than a second session.

use std::collections::{BTreeMap, BTreeSet};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};

use crate::civil::{self, Date};
use crate::error::{DomainError, DomainResult};
use crate::events::{self, Event, EventCtx, EventDraft};
use crate::import::RowResult;
use crate::store::Migration;

use super::{fields, object, ranged, text};

/// Commands this module adds to the Health domain.
pub const COMMANDS: &[&str] = &[
    "gym.program.create_default",
    "gym.program.update",
    "gym.session.start",
    "gym.session.pause",
    "gym.session.resume",
    "gym.session.note",
    "gym.session.complete",
    "gym.session.discard",
    "gym.session.delete",
    "gym.set.add",
    "gym.set.update",
    "gym.set.remove",
];

/// Queries this module adds to the Health domain.
pub const QUERIES: &[&str] =
    &["active_program", "program_day", "active_session", "session_details", "list_sessions", "previous_performance"];

/// Aggregate types whose events this module projects.
pub const AGGREGATES: &[&str] = &["gym_program", "gym_session", "gym_set"];

pub const MIGRATION: Migration = Migration {
    version: 3,
    name: "gym_training",
    sql: "CREATE TABLE gym_programs (\
            id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, anchor_date TEXT NOT NULL, \
            plan_version INTEGER NOT NULL, updated_at TEXT NOT NULL, data_json TEXT NOT NULL, \
            version INTEGER NOT NULL); \
          CREATE TABLE gym_sessions (\
            id TEXT PRIMARY KEY, program_id TEXT NOT NULL, plan_version INTEGER NOT NULL, \
            day_id TEXT NOT NULL, state TEXT NOT NULL, date TEXT NOT NULL, started_at TEXT NOT NULL, \
            ended_at TEXT, data_json TEXT NOT NULL, version INTEGER NOT NULL); \
          CREATE INDEX gym_sessions_state ON gym_sessions (state, started_at); \
          CREATE INDEX gym_sessions_date ON gym_sessions (date, started_at); \
          CREATE TABLE gym_sets (\
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, exercise_key TEXT NOT NULL, \
            exercise_order INTEGER NOT NULL, set_order INTEGER NOT NULL, set_type TEXT NOT NULL, \
            completed INTEGER NOT NULL, data_json TEXT NOT NULL, version INTEGER NOT NULL); \
          CREATE INDEX gym_sets_session ON gym_sets (session_id, exercise_order, set_order); \
          CREATE INDEX gym_sets_exercise ON gym_sets (exercise_key, completed);",
};

/// Session states. `paused` and `in_progress` are the two active states.
const STATE_IN_PROGRESS: &str = "in_progress";
const STATE_PAUSED: &str = "paused";
const STATE_COMPLETED: &str = "completed";
const STATE_DISCARDED: &str = "discarded";
const STATES: &[&str] = &[STATE_IN_PROGRESS, STATE_PAUSED, STATE_COMPLETED, STATE_DISCARDED];

const SET_TYPES: &[&str] = &["warmup", "working"];
const UNITS: &[&str] = &["lb", "kg"];
/// How a recorded load acts on the body. Only `external` load produces volume.
const SEMANTICS: &[&str] = &["external", "bodyweight", "assistance"];
const DAY_TYPES: &[&str] = &["training", "rest"];

/// Load is stored in thousandths of the unit, so 2.5 lb increments and 55 lb are exact and a
/// user-entered value is never rounded to a machine increment.
const LOAD_SCALE: i64 = 1_000;
const MAX_LOAD_MILLI: i64 = 2_000_000; // 2000 lb or kg
const MAX_REPS: i64 = 1_000;
const MAX_RIR: i64 = 5;
const MAX_SETS_PER_EXERCISE: i64 = 60;
const MAX_PLANNED_SETS: i64 = 20;
const MAX_NOTE: usize = 500;
const PLAN_DAYS: usize = 7;
const DEFAULT_PROGRAM_NAME: &str = "REVA Base Program";

// ---------------------------------------------------------------------------------------------
// The default program. Five training days and two rest days; 90 prescribed working sets per
// rotation. Exercise keys are the stable progress identity: two materially different machine
// variations keep different keys, and the same movement repeated across days shares one key.

/// `(exercise_key, display name, equipment or variation, planned working sets, min reps, max reps)`
type Prescription = (&'static str, &'static str, &'static str, i64, i64, i64);

const DAY_1: &[Prescription] = &[
    ("incline_smith_machine_press", "Incline Smith/Machine Press", "Smith machine or chest-press machine", 3, 6, 10),
    ("chest_press", "Chest Press", "Machine", 2, 8, 12),
    ("pec_deck", "Pec Deck", "Machine", 2, 10, 15),
    ("lateral_raise", "Lateral Raise", "Dumbbell", 4, 12, 20),
    ("shoulder_press", "Shoulder Press", "Machine", 2, 6, 10),
    ("overhead_cable_triceps_extension", "Overhead Cable Triceps Extension", "Cable", 2, 10, 15),
    ("rope_pushdown", "Rope Pushdown", "Cable", 2, 10, 15),
];

const DAY_2: &[Prescription] = &[
    ("lat_pulldown", "Lat Pulldown", "Cable", 3, 6, 10),
    ("chest_supported_row", "Chest-Supported Row", "Machine", 3, 8, 12),
    ("single_arm_lat_pulldown", "Single-Arm Lat Pulldown", "Cable", 2, 10, 15),
    ("reverse_pec_deck", "Reverse Pec Deck", "Machine", 3, 12, 20),
    ("preacher_curl", "Preacher Curl", "Machine or bench", 3, 8, 12),
    ("hammer_cable_curl", "Hammer/Cable Curl", "Dumbbell or cable", 2, 10, 15),
];

const DAY_3: &[Prescription] = &[
    ("smith_squat", "Smith Squat", "Smith machine", 3, 6, 10),
    ("smith_rdl", "Smith RDL", "Smith machine", 3, 6, 10),
    ("leg_press", "Leg Press", "Machine", 2, 10, 15),
    ("seated_leg_curl", "Seated Leg Curl", "Machine", 3, 10, 15),
    ("leg_extension", "Leg Extension", "Machine", 3, 10, 15),
    ("calf_raise", "Calf Raise", "Machine", 4, 8, 15),
    ("cable_crunch", "Cable Crunch", "Cable", 3, 10, 20),
];

const DAY_5: &[Prescription] = &[
    ("assisted_pull_up", "Assisted Pull-Up", "Assisted pull-up machine", 3, 6, 10),
    ("chest_supported_upper_back_row", "Chest-Supported/Upper-Back Row", "Machine", 3, 8, 12),
    ("incline_chest_press", "Incline Chest Press", "Machine", 2, 8, 12),
    ("cable_lateral_raise", "Cable Lateral Raise", "Cable", 4, 12, 20),
    ("reverse_pec_deck", "Reverse Pec Deck", "Machine", 3, 12, 20),
];

const DAY_6: &[Prescription] = &[
    ("leg_press", "Leg Press", "Machine", 2, 8, 12),
    ("leg_extension", "Leg Extension", "Machine", 2, 12, 15),
    ("seated_lying_leg_curl", "Seated/Lying Leg Curl", "Machine", 3, 10, 15),
    ("calf_raise", "Calf Raise", "Machine", 3, 10, 15),
    ("preacher_curl", "Preacher Curl", "Machine or bench", 2, 8, 12),
    ("hammer_cable_curl", "Hammer/Cable Curl", "Dumbbell or cable", 2, 10, 15),
    ("rope_pushdown", "Rope Pushdown", "Cable", 2, 10, 15),
    ("overhead_triceps_extension", "Overhead Triceps Extension", "Dumbbell or cable", 2, 10, 15),
    ("hanging_leg_raise", "Hanging Leg Raise", "Bodyweight", 3, 10, 20),
];

/// `(day_id, label, day_type, prescriptions)`
const DEFAULT_DAYS: &[(&str, &str, &str, &[Prescription])] = &[
    ("day-1", "Upper A: Upper Chest + Delts", "training", DAY_1),
    ("day-2", "Pull A: Lat Width + Biceps", "training", DAY_2),
    ("day-3", "Legs A", "training", DAY_3),
    ("day-4", "REST", "rest", &[]),
    ("day-5", "Upper B: Back + Shoulders", "training", DAY_5),
    ("day-6", "Legs B + Arms", "training", DAY_6),
    ("day-7", "REST", "rest", &[]),
];

fn default_days() -> Value {
    let days: Vec<Value> = DEFAULT_DAYS
        .iter()
        .enumerate()
        .map(|(index, (day_id, label, day_type, plan))| {
            let exercises: Vec<Value> = plan
                .iter()
                .enumerate()
                .map(|(order, (key, name, equipment, sets, min_reps, max_reps))| {
                    json!({
                        "exercise_key": key,
                        "name": name,
                        "equipment": equipment,
                        "order": order as i64 + 1,
                        "planned_sets": sets,
                        "min_reps": min_reps,
                        "max_reps": max_reps,
                        "rest_seconds": Value::Null,
                    })
                })
                .collect();
            json!({
                "day_id": day_id,
                "day_index": index as i64 + 1,
                "label": label,
                "day_type": day_type,
                "exercises": exercises,
            })
        })
        .collect();
    Value::Array(days)
}

// ---------------------------------------------------------------------------------------------
// Small validators. The parent module owns the shared ones (`text`, `fields`, `ranged`).

fn one_of(map: &Map<String, Value>, field: &str, allowed: &[&str]) -> DomainResult<String> {
    let value = text(map, field, 32)?;
    if !allowed.contains(&value.as_str()) {
        return Err(DomainError::validation(field, format!("must be one of {}", allowed.join(", "))));
    }
    Ok(value)
}

fn identifier(map: &Map<String, Value>, field: &str) -> DomainResult<String> {
    let value = text(map, field, 64)?;
    let ok = value.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_');
    if !ok {
        return Err(DomainError::validation(field, "must be letters, digits, '-' or '_'"));
    }
    Ok(value)
}

fn optional_note(map: &Map<String, Value>, field: &str) -> DomainResult<Value> {
    match map.get(field) {
        None | Some(Value::Null) => Ok(Value::Null),
        Some(Value::String(raw)) => {
            let note = raw.trim();
            if note.is_empty() {
                return Ok(Value::Null);
            }
            if note.chars().count() > MAX_NOTE || note.chars().any(|c| c.is_control() && c != '\n') {
                return Err(DomainError::validation(field, "invalid note"));
            }
            Ok(json!(note))
        }
        Some(_) => Err(DomainError::validation(field, "must be text or null")),
    }
}

fn optional_ranged(map: &Map<String, Value>, field: &str, min: i64, max: i64) -> DomainResult<Value> {
    match map.get(field) {
        None | Some(Value::Null) => Ok(Value::Null),
        Some(_) => Ok(json!(ranged(map, field, min, max)?)),
    }
}

/// An ISO-8601 instant in UTC: `2026-10-22T18:30:00Z` or with milliseconds.
fn timestamp_value(raw: &str, field: &str) -> DomainResult<String> {
    let invalid = || DomainError::validation(field, "must be an ISO-8601 UTC instant, like 2026-10-22T18:30:00Z");
    if !(raw.len() == 20 || raw.len() == 24) || !raw.ends_with('Z') || !raw.is_ascii() {
        return Err(invalid());
    }
    let bytes = raw.as_bytes();
    if bytes[10] != b'T' || bytes[13] != b':' || bytes[16] != b':' {
        return Err(invalid());
    }
    Date::parse(&raw[..10]).ok_or_else(invalid)?;
    let part = |from: usize, to: usize| raw[from..to].parse::<i64>().map_err(|_| invalid());
    let (hour, minute, second) = (part(11, 13)?, part(14, 16)?, part(17, 19)?);
    if hour > 23 || minute > 59 || second > 59 {
        return Err(invalid());
    }
    if raw.len() == 24 {
        if bytes[19] != b'.' {
            return Err(invalid());
        }
        part(20, 23)?;
    }
    Ok(raw.to_string())
}

fn timestamp(map: &Map<String, Value>, field: &str) -> DomainResult<String> {
    let raw = map.get(field).and_then(Value::as_str).ok_or_else(|| DomainError::validation(field, "required"))?;
    timestamp_value(raw, field)
}

/// `field` when present, otherwise the Kernel's own clock. Hosts may pass the instant the user
/// actually tapped; they can never pass a malformed one.
fn timestamp_or_now(map: &Map<String, Value>, field: &str) -> DomainResult<String> {
    match map.get(field) {
        None | Some(Value::Null) => Ok(civil::now_iso()),
        Some(_) => timestamp(map, field),
    }
}

fn epoch_ms(raw: &str) -> DomainResult<i64> {
    let ts = timestamp_value(raw, "timestamp")?;
    let date = Date::parse(&ts[..10]).ok_or_else(|| DomainError::validation("timestamp", "invalid date"))?;
    let part = |from: usize, to: usize| ts[from..to].parse::<i64>().unwrap_or(0);
    let secs = date.to_days() * 86_400 + part(11, 13) * 3600 + part(14, 16) * 60 + part(17, 19);
    let millis = if ts.len() == 24 { part(20, 23) } else { 0 };
    Ok(secs * 1_000 + millis)
}

// ---------------------------------------------------------------------------------------------
// Payload validation. `command` builds a payload and validates it with the same function
// `apply` uses, so a projection rebuilt from the log is identical to the one written live.

struct ProgramRow {
    name: String,
    status: String,
    anchor_date: String,
    plan_version: i64,
    updated_at: String,
}

fn validate_day(value: &Value, seen_ids: &mut BTreeSet<String>, index: usize) -> DomainResult<()> {
    let day = object(value)?;
    fields(day, &["day_id", "day_index", "label", "day_type", "exercises"])?;
    let day_id = identifier(day, "day_id")?;
    if !seen_ids.insert(day_id) {
        return Err(DomainError::validation("day_id", "duplicate plan day"));
    }
    let day_index = ranged(day, "day_index", 1, PLAN_DAYS as i64)?;
    if day_index != index as i64 + 1 {
        return Err(DomainError::validation("day_index", "plan days must be numbered 1..7 in order"));
    }
    text(day, "label", 120)?;
    let day_type = one_of(day, "day_type", DAY_TYPES)?;
    let exercises = day
        .get("exercises")
        .and_then(Value::as_array)
        .ok_or_else(|| DomainError::validation("exercises", "required list"))?;
    if day_type == "rest" && !exercises.is_empty() {
        return Err(DomainError::validation("exercises", "a rest day has no prescribed sets"));
    }
    if day_type == "training" && exercises.is_empty() {
        return Err(DomainError::validation("exercises", "a training day needs at least one exercise"));
    }
    if exercises.len() > 30 {
        return Err(DomainError::validation("exercises", "too many exercises in one day"));
    }
    let mut orders = BTreeSet::new();
    for (position, item) in exercises.iter().enumerate() {
        let exercise = object(item)?;
        fields(
            exercise,
            &["exercise_key", "name", "equipment", "order", "planned_sets", "min_reps", "max_reps", "rest_seconds"],
        )?;
        identifier(exercise, "exercise_key")?;
        text(exercise, "name", 120)?;
        optional_note(exercise, "equipment")?;
        let order = ranged(exercise, "order", 1, 30)?;
        if order != position as i64 + 1 || !orders.insert(order) {
            return Err(DomainError::validation("order", "exercises must be ordered 1..n without gaps"));
        }
        let planned = ranged(exercise, "planned_sets", 1, MAX_PLANNED_SETS)?;
        let (min_reps, max_reps) =
            (ranged(exercise, "min_reps", 1, MAX_REPS)?, ranged(exercise, "max_reps", 1, MAX_REPS)?);
        if min_reps > max_reps {
            return Err(DomainError::validation("min_reps", "greater than max_reps"));
        }
        let _ = planned;
        optional_ranged(exercise, "rest_seconds", 0, 3_600)?;
    }
    Ok(())
}

fn validate_program(id: &str, payload: &Map<String, Value>) -> DomainResult<ProgramRow> {
    fields(
        payload,
        &["id", "kind", "name", "status", "anchor_date", "plan_version", "created_at", "updated_at", "days"],
    )?;
    if payload.get("id").and_then(Value::as_str) != Some(id) {
        return Err(DomainError::validation("id", "payload id does not match the aggregate"));
    }
    if payload.get("kind").and_then(Value::as_str) != Some("gym_program") {
        return Err(DomainError::validation("kind", "not a gym program"));
    }
    let row = ProgramRow {
        name: text(payload, "name", 120)?,
        status: one_of(payload, "status", &["active", "archived"])?,
        anchor_date: super::date(payload, "anchor_date")?,
        plan_version: ranged(payload, "plan_version", 1, 100_000)?,
        updated_at: timestamp(payload, "updated_at")?,
    };
    timestamp(payload, "created_at")?;
    let days = payload
        .get("days")
        .and_then(Value::as_array)
        .ok_or_else(|| DomainError::validation("days", "required list"))?;
    if days.len() != PLAN_DAYS {
        return Err(DomainError::validation("days", "a program has exactly seven plan days"));
    }
    let mut seen = BTreeSet::new();
    for (index, day) in days.iter().enumerate() {
        validate_day(day, &mut seen, index)?;
    }
    Ok(row)
}

struct SessionRow {
    program_id: String,
    plan_version: i64,
    day_id: String,
    state: String,
    date: String,
    started_at: String,
    ended_at: Option<String>,
}

fn validate_session(id: &str, payload: &Map<String, Value>) -> DomainResult<SessionRow> {
    fields(
        payload,
        &[
            "id",
            "kind",
            "program_id",
            "plan_version",
            "day_id",
            "label",
            "plan_snapshot",
            "state",
            "date",
            "started_at",
            "ended_at",
            "pauses",
            "notes",
            "effort_note",
        ],
    )?;
    if payload.get("id").and_then(Value::as_str) != Some(id) {
        return Err(DomainError::validation("id", "payload id does not match the aggregate"));
    }
    if payload.get("kind").and_then(Value::as_str) != Some("gym_session") {
        return Err(DomainError::validation("kind", "not a gym session"));
    }
    let state = one_of(payload, "state", STATES)?;
    let started_at = timestamp(payload, "started_at")?;
    let ended_at = match payload.get("ended_at") {
        None | Some(Value::Null) => None,
        Some(_) => Some(timestamp(payload, "ended_at")?),
    };
    if let Some(end) = &ended_at {
        if epoch_ms(end)? < epoch_ms(&started_at)? {
            return Err(DomainError::validation("ended_at", "before the session started"));
        }
    }
    if (state == STATE_COMPLETED) != ended_at.is_some() {
        return Err(DomainError::validation(
            "ended_at",
            "a completed session has an end instant, an open one has none",
        ));
    }
    let row = SessionRow {
        program_id: identifier(payload, "program_id")?,
        plan_version: ranged(payload, "plan_version", 1, 100_000)?,
        day_id: identifier(payload, "day_id")?,
        state,
        date: super::date(payload, "date")?,
        started_at,
        ended_at,
    };
    text(payload, "label", 120)?;
    optional_note(payload, "notes")?;
    optional_note(payload, "effort_note")?;
    let snapshot = payload.get("plan_snapshot").ok_or_else(|| DomainError::validation("plan_snapshot", "required"))?;
    let mut seen = BTreeSet::new();
    validate_snapshot(snapshot, &mut seen)?;
    validate_pauses(payload, &row)?;
    Ok(row)
}

/// A session keeps the plan day exactly as it was prescribed when the workout started, so a later
/// plan edit never rewrites a finished session.
fn validate_snapshot(value: &Value, seen: &mut BTreeSet<String>) -> DomainResult<()> {
    let day = object(value)?;
    let index = day
        .get("day_index")
        .and_then(Value::as_i64)
        .ok_or_else(|| DomainError::validation("plan_snapshot", "missing day_index"))?;
    if !(1..=PLAN_DAYS as i64).contains(&index) {
        return Err(DomainError::validation("plan_snapshot", "invalid day_index"));
    }
    validate_day(value, seen, index as usize - 1)
}

fn validate_pauses(payload: &Map<String, Value>, row: &SessionRow) -> DomainResult<()> {
    let pauses = payload
        .get("pauses")
        .and_then(Value::as_array)
        .ok_or_else(|| DomainError::validation("pauses", "required list"))?;
    if pauses.len() > 200 {
        return Err(DomainError::validation("pauses", "too many pause intervals"));
    }
    let start = epoch_ms(&row.started_at)?;
    let mut previous_end = start;
    for (index, item) in pauses.iter().enumerate() {
        let interval = object(item)?;
        fields(interval, &["from", "to"])?;
        let from = epoch_ms(&timestamp(interval, "from")?)?;
        if from < previous_end {
            return Err(DomainError::validation("pauses", "pause intervals must not overlap or precede the start"));
        }
        match interval.get("to") {
            None | Some(Value::Null) => {
                if index + 1 != pauses.len() || row.state != STATE_PAUSED {
                    return Err(DomainError::validation(
                        "pauses",
                        "only a paused session has an open pause, and only its last",
                    ));
                }
                previous_end = from;
            }
            Some(_) => {
                let to = epoch_ms(&timestamp(interval, "to")?)?;
                if to < from {
                    return Err(DomainError::validation("pauses", "a pause cannot end before it starts"));
                }
                previous_end = to;
            }
        }
    }
    if row.state == STATE_PAUSED && !pauses.last().map(|p| p.get("to").is_none_or(Value::is_null)).unwrap_or(false) {
        return Err(DomainError::validation("pauses", "a paused session has an open pause interval"));
    }
    if let Some(end) = &row.ended_at {
        if previous_end > epoch_ms(end)? {
            return Err(DomainError::validation("pauses", "a pause extends past the end of the session"));
        }
    }
    Ok(())
}

struct SetRow {
    session_id: String,
    exercise_key: String,
    exercise_order: i64,
    set_order: i64,
    set_type: String,
    completed: bool,
}

fn validate_set(id: &str, payload: &Map<String, Value>) -> DomainResult<SetRow> {
    fields(
        payload,
        &[
            "id",
            "kind",
            "session_id",
            "exercise_key",
            "exercise_name",
            "equipment",
            "exercise_order",
            "set_order",
            "set_type",
            "load_milli",
            "weight_unit",
            "load_semantics",
            "reps",
            "rir",
            "completed",
            "completed_at",
            "notes",
            "prescription_order",
        ],
    )?;
    if payload.get("id").and_then(Value::as_str) != Some(id) {
        return Err(DomainError::validation("id", "payload id does not match the aggregate"));
    }
    if payload.get("kind").and_then(Value::as_str) != Some("gym_set") {
        return Err(DomainError::validation("kind", "not a gym set"));
    }
    let completed = match payload.get("completed") {
        Some(Value::Bool(flag)) => *flag,
        _ => return Err(DomainError::validation("completed", "required true or false")),
    };
    let semantics = one_of(payload, "load_semantics", SEMANTICS)?;
    let load = optional_ranged(payload, "load_milli", 0, MAX_LOAD_MILLI)?;
    if semantics == "external" && load.is_null() && completed {
        return Err(DomainError::validation("load_milli", "a completed external-load set records its load"));
    }
    let reps = optional_ranged(payload, "reps", 0, MAX_REPS)?;
    if completed && reps.is_null() {
        return Err(DomainError::validation("reps", "a completed set records its repetitions"));
    }
    let completed_at = match payload.get("completed_at") {
        None | Some(Value::Null) => None,
        Some(_) => Some(timestamp(payload, "completed_at")?),
    };
    if completed != completed_at.is_some() {
        return Err(DomainError::validation("completed_at", "a completed set carries the instant it was completed"));
    }
    let row = SetRow {
        session_id: identifier(payload, "session_id")?,
        exercise_key: identifier(payload, "exercise_key")?,
        exercise_order: ranged(payload, "exercise_order", 1, 30)?,
        set_order: ranged(payload, "set_order", 1, MAX_SETS_PER_EXERCISE)?,
        set_type: one_of(payload, "set_type", SET_TYPES)?,
        completed,
    };
    text(payload, "exercise_name", 120)?;
    optional_note(payload, "equipment")?;
    one_of(payload, "weight_unit", UNITS)?;
    optional_ranged(payload, "rir", 0, MAX_RIR)?;
    optional_ranged(payload, "prescription_order", 1, 30)?;
    optional_note(payload, "notes")?;
    Ok(row)
}

// ---------------------------------------------------------------------------------------------
// Reads used by commands and queries.

fn program_row(conn: &Connection, id: &str) -> DomainResult<Option<Value>> {
    load_json(conn, "SELECT data_json FROM gym_programs WHERE id=?1", id)
}

fn active_program_row(conn: &Connection) -> DomainResult<Option<Value>> {
    let data: Option<String> = conn
        .query_row("SELECT data_json FROM gym_programs WHERE status='active' ORDER BY id LIMIT 1", [], |r| r.get(0))
        .optional()?;
    Ok(match data {
        Some(text) => Some(serde_json::from_str(&text)?),
        None => None,
    })
}

fn session_row(conn: &Connection, id: &str) -> DomainResult<Option<Value>> {
    load_json(conn, "SELECT data_json FROM gym_sessions WHERE id=?1", id)
}

fn set_row(conn: &Connection, id: &str) -> DomainResult<Option<Value>> {
    load_json(conn, "SELECT data_json FROM gym_sets WHERE id=?1", id)
}

fn load_json(conn: &Connection, sql: &str, id: &str) -> DomainResult<Option<Value>> {
    let data: Option<String> = conn.query_row(sql, [id], |r| r.get(0)).optional()?;
    Ok(match data {
        Some(text) => Some(serde_json::from_str(&text)?),
        None => None,
    })
}

fn open_session(conn: &Connection) -> DomainResult<Option<Value>> {
    let data: Option<String> = conn
        .query_row(
            "SELECT data_json FROM gym_sessions WHERE state IN ('in_progress','paused') ORDER BY started_at, id LIMIT 1",
            [],
            |r| r.get(0),
        )
        .optional()?;
    Ok(match data {
        Some(text) => Some(serde_json::from_str(&text)?),
        None => None,
    })
}

fn session_sets(conn: &Connection, session_id: &str) -> DomainResult<Vec<Value>> {
    let mut stmt = conn.prepare(
        "SELECT data_json FROM gym_sets WHERE session_id=?1 ORDER BY exercise_order, exercise_key, set_order, id",
    )?;
    let raw: Vec<String> = stmt.query_map([session_id], |r| r.get(0))?.collect::<Result<_, _>>()?;
    raw.iter().map(|text| Ok(serde_json::from_str(text)?)).collect()
}

fn next_set_order(conn: &Connection, session_id: &str, exercise_key: &str) -> DomainResult<i64> {
    let highest: i64 = conn.query_row(
        "SELECT COALESCE(MAX(set_order), 0) FROM gym_sets WHERE session_id=?1 AND exercise_key=?2",
        params![session_id, exercise_key],
        |r| r.get(0),
    )?;
    if highest >= MAX_SETS_PER_EXERCISE {
        return Err(DomainError::validation("set_order", "too many sets for one exercise"));
    }
    Ok(highest + 1)
}

fn day_of(program: &Value, day_id: &str) -> DomainResult<Value> {
    program["days"]
        .as_array()
        .and_then(|days| days.iter().find(|d| d["day_id"].as_str() == Some(day_id)))
        .cloned()
        .ok_or_else(|| DomainError::not_found("plan day"))
}

fn draft(aggregate_type: &str, id: &str, verb: &str, payload: Value) -> EventDraft {
    EventDraft {
        aggregate_type: aggregate_type.to_string(),
        aggregate_id: id.to_string(),
        kind: format!("{aggregate_type}.{verb}"),
        tombstone: false,
        payload,
    }
}

fn tombstone(aggregate_type: &str, id: String) -> EventDraft {
    EventDraft {
        aggregate_type: aggregate_type.to_string(),
        aggregate_id: id,
        kind: format!("{aggregate_type}.deleted"),
        tombstone: true,
        payload: json!({}),
    }
}

fn new_id() -> String {
    uuid::Uuid::new_v4().to_string()
}

/// A session only accepts logging while it is in progress or paused.
fn require_open(session: &Value) -> DomainResult<&str> {
    match session["state"].as_str() {
        Some(STATE_IN_PROGRESS) => Ok(STATE_IN_PROGRESS),
        Some(STATE_PAUSED) => Ok(STATE_PAUSED),
        Some(STATE_COMPLETED) => Err(DomainError::conflict("this workout is already finished")),
        Some(STATE_DISCARDED) => Err(DomainError::conflict("this workout was discarded")),
        _ => Err(DomainError::internal("session state")),
    }
}

// ---------------------------------------------------------------------------------------------
// Commands

pub fn command(conn: &Connection, kind: &str, payload: &Value) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    match kind {
        "gym.program.create_default" => create_default(conn, map),
        "gym.program.update" => update_program(conn, map),
        "gym.session.start" => start_session(conn, map),
        "gym.session.pause" => pause_session(conn, map),
        "gym.session.resume" => resume_session(conn, map),
        "gym.session.note" => note_session(conn, map),
        "gym.session.complete" => complete_session(conn, map),
        "gym.session.discard" => discard_session(conn, map),
        "gym.session.delete" => delete_session(conn, map),
        "gym.set.add" => add_set(conn, map),
        "gym.set.update" => update_set(conn, map),
        "gym.set.remove" => remove_set(conn, map),
        _ => Err(DomainError::validation("kind", "unknown gym command")),
    }
}

fn create_default(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["name", "anchor_date"])?;
    if active_program_row(conn)?.is_some() {
        return Err(DomainError::conflict("a gym program already exists; edit it instead of creating another"));
    }
    let name = match map.get("name") {
        None | Some(Value::Null) => DEFAULT_PROGRAM_NAME.to_string(),
        Some(_) => text(map, "name", 120)?,
    };
    let anchor = match map.get("anchor_date") {
        None | Some(Value::Null) => civil::today().to_iso(),
        Some(_) => super::date(map, "anchor_date")?,
    };
    let now = civil::now_iso();
    let id = new_id();
    let payload = json!({
        "id": id,
        "kind": "gym_program",
        "name": name,
        "status": "active",
        "anchor_date": anchor,
        "plan_version": 1,
        "created_at": now,
        "updated_at": now,
        "days": default_days(),
    });
    validate_program(&id, object(&payload)?)?;
    Ok(vec![draft("gym_program", &id, "created", payload)])
}

fn update_program(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["program_id", "name", "anchor_date", "days"])?;
    let id = identifier(map, "program_id")?;
    let existing = program_row(conn, &id)?.ok_or_else(|| DomainError::not_found("gym program"))?;
    let mut payload = existing.as_object().cloned().ok_or_else(|| DomainError::internal("program row"))?;
    if map.contains_key("name") {
        payload.insert("name".into(), json!(text(map, "name", 120)?));
    }
    if map.contains_key("anchor_date") {
        payload.insert("anchor_date".into(), json!(super::date(map, "anchor_date")?));
    }
    if let Some(days) = map.get("days") {
        if !days.is_array() {
            return Err(DomainError::validation("days", "must be a list of seven plan days"));
        }
        payload.insert("days".into(), days.clone());
    }
    let next = existing["plan_version"].as_i64().unwrap_or(1) + 1;
    payload.insert("plan_version".into(), json!(next));
    payload.insert("updated_at".into(), json!(civil::now_iso()));
    validate_program(&id, &payload)?;
    Ok(vec![draft("gym_program", &id, "updated", Value::Object(payload))])
}

fn start_session(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["program_id", "day_id", "started_at"])?;
    let program = match map.get("program_id") {
        None | Some(Value::Null) => active_program_row(conn)?,
        Some(_) => program_row(conn, &identifier(map, "program_id")?)?,
    }
    .ok_or_else(|| DomainError::not_found("gym program"))?;
    let day_id = identifier(map, "day_id")?;
    let day = day_of(&program, &day_id)?;
    if day["day_type"].as_str() != Some("training") {
        return Err(DomainError::validation("day_id", "a rest day has no workout to start"));
    }
    if open_session(conn)?.is_some() {
        return Err(DomainError::conflict("a workout is already in progress; finish or discard it first"));
    }
    let started_at = timestamp_or_now(map, "started_at")?;
    let id = new_id();
    let payload = json!({
        "id": id,
        "kind": "gym_session",
        "program_id": program["id"],
        "plan_version": program["plan_version"],
        "day_id": day_id,
        "label": day["label"],
        "plan_snapshot": day,
        "state": STATE_IN_PROGRESS,
        "date": started_at[..10],
        "started_at": started_at,
        "ended_at": Value::Null,
        "pauses": [],
        "notes": Value::Null,
        "effort_note": Value::Null,
    });
    validate_session(&id, object(&payload)?)?;
    Ok(vec![draft("gym_session", &id, "created", payload)])
}

/// Load a session for editing, with its state checked by `allow`.
fn session_for_update(
    conn: &Connection,
    map: &Map<String, Value>,
    allow: &[&str],
) -> DomainResult<(String, Map<String, Value>)> {
    let id = identifier(map, "session_id")?;
    let session = session_row(conn, &id)?.ok_or_else(|| DomainError::not_found("workout session"))?;
    let state = session["state"].as_str().unwrap_or_default();
    if !allow.contains(&state) {
        return Err(DomainError::conflict(match state {
            STATE_COMPLETED => "this workout is already finished",
            STATE_DISCARDED => "this workout was discarded",
            STATE_PAUSED => "this workout is paused",
            _ => "this workout is in progress",
        }));
    }
    let payload = session.as_object().cloned().ok_or_else(|| DomainError::internal("session row"))?;
    Ok((id, payload))
}

fn pause_session(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["session_id", "at"])?;
    let (id, mut payload) = session_for_update(conn, map, &[STATE_IN_PROGRESS])?;
    let at = timestamp_or_now(map, "at")?;
    let mut pauses = payload["pauses"].as_array().cloned().unwrap_or_default();
    pauses.push(json!({"from": at, "to": Value::Null}));
    payload.insert("pauses".into(), Value::Array(pauses));
    payload.insert("state".into(), json!(STATE_PAUSED));
    validate_session(&id, &payload)?;
    Ok(vec![draft("gym_session", &id, "updated", Value::Object(payload))])
}

fn resume_session(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["session_id", "at"])?;
    let (id, mut payload) = session_for_update(conn, map, &[STATE_PAUSED])?;
    let at = timestamp_or_now(map, "at")?;
    let mut pauses = payload["pauses"].as_array().cloned().unwrap_or_default();
    let open = pauses.last_mut().ok_or_else(|| DomainError::internal("paused session without a pause"))?;
    open.as_object_mut().ok_or_else(|| DomainError::internal("pause interval"))?.insert("to".into(), json!(at));
    payload.insert("pauses".into(), Value::Array(pauses));
    payload.insert("state".into(), json!(STATE_IN_PROGRESS));
    validate_session(&id, &payload)?;
    Ok(vec![draft("gym_session", &id, "updated", Value::Object(payload))])
}

fn note_session(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["session_id", "notes", "effort_note"])?;
    let (id, mut payload) = session_for_update(conn, map, &[STATE_IN_PROGRESS, STATE_PAUSED, STATE_COMPLETED])?;
    if map.contains_key("notes") {
        payload.insert("notes".into(), optional_note(map, "notes")?);
    }
    if map.contains_key("effort_note") {
        payload.insert("effort_note".into(), optional_note(map, "effort_note")?);
    }
    validate_session(&id, &payload)?;
    Ok(vec![draft("gym_session", &id, "updated", Value::Object(payload))])
}

fn complete_session(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["session_id", "ended_at", "notes"])?;
    let (id, mut payload) = session_for_update(conn, map, &[STATE_IN_PROGRESS, STATE_PAUSED])?;
    let ended_at = timestamp_or_now(map, "ended_at")?;
    // A session paused at the moment the user taps Finish has its open interval closed here, so
    // active duration never counts the pause twice.
    if payload["state"].as_str() == Some(STATE_PAUSED) {
        let mut pauses = payload["pauses"].as_array().cloned().unwrap_or_default();
        if let Some(open) = pauses.last_mut() {
            if let Some(interval) = open.as_object_mut() {
                interval.insert("to".into(), json!(ended_at));
            }
        }
        payload.insert("pauses".into(), Value::Array(pauses));
    }
    if map.contains_key("notes") {
        payload.insert("notes".into(), optional_note(map, "notes")?);
    }
    payload.insert("state".into(), json!(STATE_COMPLETED));
    payload.insert("ended_at".into(), json!(ended_at));
    validate_session(&id, &payload)?;
    Ok(vec![draft("gym_session", &id, "completed", Value::Object(payload))])
}

fn discard_session(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["session_id", "ended_at"])?;
    let (id, mut payload) = session_for_update(conn, map, &[STATE_IN_PROGRESS, STATE_PAUSED])?;
    let ended_at = timestamp_or_now(map, "ended_at")?;
    if payload["state"].as_str() == Some(STATE_PAUSED) {
        let mut pauses = payload["pauses"].as_array().cloned().unwrap_or_default();
        if let Some(open) = pauses.last_mut() {
            if let Some(interval) = open.as_object_mut() {
                interval.insert("to".into(), json!(ended_at));
            }
        }
        payload.insert("pauses".into(), Value::Array(pauses));
    }
    payload.insert("state".into(), json!(STATE_DISCARDED));
    validate_session(&id, &payload)?;
    Ok(vec![draft("gym_session", &id, "discarded", Value::Object(payload))])
}

/// Delete a session and every set in it. Tombstoned, so a deleted workout never comes back
/// through sync or a projection rebuild.
fn delete_session(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["session_id"])?;
    let id = identifier(map, "session_id")?;
    if session_row(conn, &id)?.is_none() {
        return Err(DomainError::not_found("workout session"));
    }
    let mut stmt = conn.prepare("SELECT id FROM gym_sets WHERE session_id=?1 ORDER BY id")?;
    let set_ids: Vec<String> = stmt.query_map([&id], |r| r.get(0))?.collect::<Result<_, _>>()?;
    let mut drafts: Vec<EventDraft> = vec![tombstone("gym_session", id)];
    drafts.extend(set_ids.into_iter().map(|set_id| tombstone("gym_set", set_id)));
    Ok(drafts)
}

fn add_set(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(
        map,
        &[
            "session_id",
            "exercise_key",
            "exercise_name",
            "equipment",
            "exercise_order",
            "set_type",
            "load_milli",
            "weight_unit",
            "load_semantics",
            "reps",
            "rir",
            "completed",
            "completed_at",
            "notes",
        ],
    )?;
    let session_id = identifier(map, "session_id")?;
    let session = session_row(conn, &session_id)?.ok_or_else(|| DomainError::not_found("workout session"))?;
    require_open(&session)?;
    let exercise_key = identifier(map, "exercise_key")?;
    // The plan snapshot supplies name, equipment and order for a prescribed exercise; an extra
    // exercise the user adds on the day must name itself.
    let prescribed = session["plan_snapshot"]["exercises"]
        .as_array()
        .and_then(|list| list.iter().find(|e| e["exercise_key"].as_str() == Some(&exercise_key)))
        .cloned();
    let exercise_name = match map.get("exercise_name") {
        Some(Value::String(_)) => text(map, "exercise_name", 120)?,
        _ => prescribed
            .as_ref()
            .and_then(|e| e["name"].as_str().map(str::to_string))
            .ok_or_else(|| DomainError::validation("exercise_name", "required for an exercise outside the plan"))?,
    };
    let equipment = match map.get("equipment") {
        Some(_) => optional_note(map, "equipment")?,
        None => prescribed.as_ref().map(|e| e["equipment"].clone()).unwrap_or(Value::Null),
    };
    let exercise_order = match map.get("exercise_order") {
        Some(_) => ranged(map, "exercise_order", 1, 30)?,
        None => prescribed
            .as_ref()
            .and_then(|e| e["order"].as_i64())
            .unwrap_or_else(|| session["plan_snapshot"]["exercises"].as_array().map_or(1, |l| l.len() as i64 + 1)),
    };
    let completed = match map.get("completed") {
        Some(Value::Bool(flag)) => *flag,
        None => true,
        Some(_) => return Err(DomainError::validation("completed", "must be true or false")),
    };
    let completed_at = if completed { json!(timestamp_or_now(map, "completed_at")?) } else { Value::Null };
    let id = new_id();
    let payload = json!({
        "id": id,
        "kind": "gym_set",
        "session_id": session_id,
        "exercise_key": exercise_key,
        "exercise_name": exercise_name,
        "equipment": equipment,
        "exercise_order": exercise_order,
        "prescription_order": prescribed.as_ref().and_then(|e| e["order"].as_i64()).map_or(Value::Null, |n| json!(n)),
        "set_order": next_set_order(conn, &session_id, &exercise_key)?,
        "set_type": one_of(map, "set_type", SET_TYPES)?,
        "load_milli": optional_ranged(map, "load_milli", 0, MAX_LOAD_MILLI)?,
        "weight_unit": one_of(map, "weight_unit", UNITS)?,
        "load_semantics": match map.get("load_semantics") {
            Some(_) => json!(one_of(map, "load_semantics", SEMANTICS)?),
            None => json!("external"),
        },
        "reps": optional_ranged(map, "reps", 0, MAX_REPS)?,
        "rir": optional_ranged(map, "rir", 0, MAX_RIR)?,
        "completed": completed,
        "completed_at": completed_at,
        "notes": optional_note(map, "notes")?,
    });
    validate_set(&id, object(&payload)?)?;
    Ok(vec![draft("gym_set", &id, "created", payload)])
}

fn update_set(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(
        map,
        &[
            "set_id",
            "set_type",
            "load_milli",
            "weight_unit",
            "load_semantics",
            "reps",
            "rir",
            "completed",
            "completed_at",
            "notes",
        ],
    )?;
    let id = identifier(map, "set_id")?;
    let existing = set_row(conn, &id)?.ok_or_else(|| DomainError::not_found("workout set"))?;
    let session_id = existing["session_id"].as_str().unwrap_or_default().to_string();
    let session = session_row(conn, &session_id)?.ok_or_else(|| DomainError::not_found("workout session"))?;
    // A completed session may still be corrected from Session Details; a discarded one may not.
    if session["state"].as_str() == Some(STATE_DISCARDED) {
        return Err(DomainError::conflict("this workout was discarded"));
    }
    let mut payload = existing.as_object().cloned().ok_or_else(|| DomainError::internal("set row"))?;
    for field in ["load_milli", "reps", "rir"] {
        if map.contains_key(field) {
            let max = match field {
                "load_milli" => MAX_LOAD_MILLI,
                "reps" => MAX_REPS,
                _ => MAX_RIR,
            };
            payload.insert(field.into(), optional_ranged(map, field, 0, max)?);
        }
    }
    if map.contains_key("set_type") {
        payload.insert("set_type".into(), json!(one_of(map, "set_type", SET_TYPES)?));
    }
    if map.contains_key("weight_unit") {
        payload.insert("weight_unit".into(), json!(one_of(map, "weight_unit", UNITS)?));
    }
    if map.contains_key("load_semantics") {
        payload.insert("load_semantics".into(), json!(one_of(map, "load_semantics", SEMANTICS)?));
    }
    if map.contains_key("notes") {
        payload.insert("notes".into(), optional_note(map, "notes")?);
    }
    if let Some(flag) = map.get("completed") {
        let completed = flag.as_bool().ok_or_else(|| DomainError::validation("completed", "must be true or false"))?;
        payload.insert("completed".into(), json!(completed));
        let at = if completed {
            let fallback = payload["completed_at"].as_str().map(str::to_string);
            match (map.get("completed_at"), fallback) {
                (Some(Value::Null) | None, Some(previous)) => json!(previous),
                _ => json!(timestamp_or_now(map, "completed_at")?),
            }
        } else {
            Value::Null
        };
        payload.insert("completed_at".into(), at);
    } else if map.contains_key("completed_at") && payload["completed"].as_bool() == Some(true) {
        payload.insert("completed_at".into(), json!(timestamp(map, "completed_at")?));
    }
    validate_set(&id, &payload)?;
    Ok(vec![draft("gym_set", &id, "updated", Value::Object(payload))])
}

fn remove_set(conn: &Connection, map: &Map<String, Value>) -> DomainResult<Vec<EventDraft>> {
    fields(map, &["set_id"])?;
    let id = identifier(map, "set_id")?;
    let existing = set_row(conn, &id)?.ok_or_else(|| DomainError::not_found("workout set"))?;
    let session_id = existing["session_id"].as_str().unwrap_or_default().to_string();
    if let Some(session) = session_row(conn, &session_id)? {
        if session["state"].as_str() == Some(STATE_DISCARDED) {
            return Err(DomainError::conflict("this workout was discarded"));
        }
    }
    Ok(vec![tombstone("gym_set", id)])
}

// ---------------------------------------------------------------------------------------------
// Projections

pub fn owns(aggregate_type: &str) -> bool {
    AGGREGATES.contains(&aggregate_type)
}

pub fn apply(conn: &Connection, event: &Event) -> DomainResult<()> {
    let table = match event.aggregate_type.as_str() {
        "gym_program" => "gym_programs",
        "gym_session" => "gym_sessions",
        "gym_set" => "gym_sets",
        other => return Err(DomainError::validation("aggregate_type", format!("not a gym aggregate: {other}"))),
    };
    if event.tombstone {
        conn.execute(&format!("DELETE FROM {table} WHERE id=?1"), [&event.aggregate_id])?;
        return Ok(());
    }
    if events::is_tombstoned(conn, &event.aggregate_type, &event.aggregate_id)? {
        return Ok(());
    }
    let payload = object(&event.payload)?;
    let data = event.payload.to_string();
    match event.aggregate_type.as_str() {
        "gym_program" => {
            let row = validate_program(&event.aggregate_id, payload)?;
            conn.execute(
                "INSERT INTO gym_programs (id,name,status,anchor_date,plan_version,updated_at,data_json,version) \
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8) ON CONFLICT(id) DO UPDATE SET name=excluded.name,\
                 status=excluded.status,anchor_date=excluded.anchor_date,plan_version=excluded.plan_version,\
                 updated_at=excluded.updated_at,data_json=excluded.data_json,version=excluded.version",
                params![
                    event.aggregate_id,
                    row.name,
                    row.status,
                    row.anchor_date,
                    row.plan_version,
                    row.updated_at,
                    data,
                    event.version
                ],
            )?;
        }
        "gym_session" => {
            let row = validate_session(&event.aggregate_id, payload)?;
            conn.execute(
                "INSERT INTO gym_sessions (id,program_id,plan_version,day_id,state,date,started_at,ended_at,data_json,version) \
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10) ON CONFLICT(id) DO UPDATE SET program_id=excluded.program_id,\
                 plan_version=excluded.plan_version,day_id=excluded.day_id,state=excluded.state,date=excluded.date,\
                 started_at=excluded.started_at,ended_at=excluded.ended_at,data_json=excluded.data_json,version=excluded.version",
                params![
                    event.aggregate_id,
                    row.program_id,
                    row.plan_version,
                    row.day_id,
                    row.state,
                    row.date,
                    row.started_at,
                    row.ended_at,
                    data,
                    event.version
                ],
            )?;
        }
        _ => {
            let row = validate_set(&event.aggregate_id, payload)?;
            conn.execute(
                "INSERT INTO gym_sets (id,session_id,exercise_key,exercise_order,set_order,set_type,completed,data_json,version) \
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9) ON CONFLICT(id) DO UPDATE SET session_id=excluded.session_id,\
                 exercise_key=excluded.exercise_key,exercise_order=excluded.exercise_order,set_order=excluded.set_order,\
                 set_type=excluded.set_type,completed=excluded.completed,data_json=excluded.data_json,version=excluded.version",
                params![
                    event.aggregate_id,
                    row.session_id,
                    row.exercise_key,
                    row.exercise_order,
                    row.set_order,
                    row.set_type,
                    row.completed as i64,
                    data,
                    event.version
                ],
            )?;
        }
    }
    Ok(())
}

/// Called by the Health domain's rebuild before the event log is replayed.
pub fn clear(conn: &Connection) -> DomainResult<()> {
    for table in ["gym_sets", "gym_sessions", "gym_programs"] {
        conn.execute(&format!("DELETE FROM {table}"), [])?;
    }
    Ok(())
}

/// Rows for the projection digest, prefixed so a gym id never collides with a health record id.
pub fn digest_rows(conn: &Connection) -> DomainResult<Vec<(String, String)>> {
    let mut out = Vec::new();
    for (table, prefix) in [("gym_programs", "gym_program"), ("gym_sessions", "gym_session"), ("gym_sets", "gym_set")] {
        let mut stmt = conn.prepare(&format!("SELECT id,data_json FROM {table} ORDER BY id"))?;
        let rows: Vec<(String, String)> =
            stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<Result<_, _>>()?;
        out.extend(rows.into_iter().map(|(id, data)| (format!("{prefix}:{id}"), data)));
    }
    Ok(out)
}

// ---------------------------------------------------------------------------------------------
// Metrics. Computed here so Windows, Android and the Core never disagree about a number the
// user sees next to their own recorded sets.

/// Volume is the sum of load x reps over completed working sets that carry an external load,
/// kept apart per weight unit. Bodyweight and assisted sets are counted, never added in.
fn metrics(session: &Value, sets: &[Value]) -> DomainResult<Value> {
    let started = epoch_ms(session["started_at"].as_str().unwrap_or_default())?;
    let end_instant = match session["ended_at"].as_str() {
        Some(end) => epoch_ms(end)?,
        None => epoch_ms(&civil::now_iso())?,
    };
    let mut paused_ms = 0_i64;
    for interval in session["pauses"].as_array().cloned().unwrap_or_default() {
        let from = epoch_ms(interval["from"].as_str().unwrap_or_default())?;
        let to = match interval["to"].as_str() {
            Some(to) => epoch_ms(to)?,
            None => end_instant,
        };
        paused_ms += (to - from).max(0);
    }
    let elapsed_ms = (end_instant - started).max(0);
    let active_ms = (elapsed_ms - paused_ms).max(0);

    let mut volume: BTreeMap<String, (i64, i64)> = BTreeMap::new();
    let mut working_completed = 0_i64;
    let mut working_pending = 0_i64;
    let mut warmup_completed = 0_i64;
    let mut excluded = 0_i64;
    let mut exercises: BTreeSet<&str> = BTreeSet::new();
    for set in sets {
        let completed = set["completed"].as_bool().unwrap_or(false);
        let working = set["set_type"].as_str() == Some("working");
        if let Some(key) = set["exercise_key"].as_str() {
            exercises.insert(key);
        }
        match (working, completed) {
            (true, true) => working_completed += 1,
            (true, false) => working_pending += 1,
            (false, true) => warmup_completed += 1,
            (false, false) => {}
        }
        if !(working && completed) {
            continue;
        }
        let external = set["load_semantics"].as_str() == Some("external");
        let (load, reps) = (set["load_milli"].as_i64(), set["reps"].as_i64());
        match (external, load, reps) {
            (true, Some(load), Some(reps)) => {
                let unit = set["weight_unit"].as_str().unwrap_or("lb").to_string();
                let entry = volume.entry(unit).or_insert((0, 0));
                entry.0 += load * reps;
                entry.1 += 1;
            }
            _ => excluded += 1,
        }
    }
    let volume_rows: Vec<Value> = volume
        .into_iter()
        .map(|(unit, (milli, count))| {
            json!({"unit": unit, "volume_milli": milli, "volume": milli as f64 / LOAD_SCALE as f64, "sets": count})
        })
        .collect();
    let planned: i64 = session["plan_snapshot"]["exercises"]
        .as_array()
        .map(|list| list.iter().filter_map(|e| e["planned_sets"].as_i64()).sum())
        .unwrap_or(0);
    Ok(json!({
        "started_at": session["started_at"],
        "ended_at": session["ended_at"],
        "elapsed_seconds": elapsed_ms / 1_000,
        "active_seconds": active_ms / 1_000,
        "paused_seconds": paused_ms / 1_000,
        "exercises_performed": exercises.len(),
        "planned_working_sets": planned,
        "working_sets_completed": working_completed,
        "working_sets_pending": working_pending,
        "warmup_sets_completed": warmup_completed,
        "volume_by_unit": volume_rows,
        "volume_excluded_sets": excluded,
    }))
}

/// Performed exercises with their sets, in the order the plan prescribes and extras after it.
fn breakdown(session: &Value, sets: &[Value]) -> Value {
    let mut groups: BTreeMap<(i64, String), Vec<Value>> = BTreeMap::new();
    for set in sets {
        let key = (set["exercise_order"].as_i64().unwrap_or(0), set["exercise_key"].as_str().unwrap_or("").to_string());
        groups.entry(key).or_default().push(set.clone());
    }
    let prescriptions = session["plan_snapshot"]["exercises"].as_array().cloned().unwrap_or_default();
    let rows: Vec<Value> = groups
        .into_iter()
        .map(|((order, key), items)| {
            let planned = prescriptions.iter().find(|e| e["exercise_key"].as_str() == Some(&key)).cloned();
            let working: Vec<&Value> = items.iter().filter(|s| s["set_type"].as_str() == Some("working")).collect();
            let completed_working = working.iter().filter(|s| s["completed"].as_bool() == Some(true)).count();
            json!({
                "exercise_key": key,
                "exercise_name": items.first().map(|s| s["exercise_name"].clone()).unwrap_or(Value::Null),
                "equipment": items.first().map(|s| s["equipment"].clone()).unwrap_or(Value::Null),
                "exercise_order": order,
                "planned": planned.as_ref().map(|p| json!({
                    "planned_sets": p["planned_sets"],
                    "min_reps": p["min_reps"],
                    "max_reps": p["max_reps"],
                })).unwrap_or(Value::Null),
                "working_sets_logged": working.len(),
                "working_sets_completed": completed_working,
                "sets": items,
            })
        })
        .collect();
    Value::Array(rows)
}

// ---------------------------------------------------------------------------------------------
// Queries

pub fn query(conn: &Connection, name: &str, params: &Value) -> DomainResult<(Value, Vec<String>)> {
    let map = object(params)?;
    match name {
        "active_program" => {
            fields(map, &[])?;
            Ok(match active_program_row(conn)? {
                Some(program) => {
                    let id = program["id"].as_str().unwrap_or_default().to_string();
                    (json!([program]), vec![id])
                }
                None => (json!([]), vec![]),
            })
        }
        "program_day" => {
            fields(map, &["program_id", "day_id"])?;
            let program = match map.get("program_id") {
                None | Some(Value::Null) => active_program_row(conn)?,
                Some(_) => program_row(conn, &identifier(map, "program_id")?)?,
            }
            .ok_or_else(|| DomainError::not_found("gym program"))?;
            let day = day_of(&program, &identifier(map, "day_id")?)?;
            let id = program["id"].as_str().unwrap_or_default().to_string();
            Ok((
                json!([{
                    "program_id": program["id"],
                    "program_name": program["name"],
                    "plan_version": program["plan_version"],
                    "anchor_date": program["anchor_date"],
                    "day": day,
                }]),
                vec![id],
            ))
        }
        "active_session" => {
            fields(map, &[])?;
            match open_session(conn)? {
                None => Ok((json!([]), vec![])),
                Some(session) => {
                    let id = session["id"].as_str().unwrap_or_default().to_string();
                    let sets = session_sets(conn, &id)?;
                    let ids = source_ids(&id, &sets);
                    Ok((json!([detail(&session, &sets)?]), ids))
                }
            }
        }
        "session_details" => {
            fields(map, &["session_id"])?;
            let id = identifier(map, "session_id")?;
            let session = session_row(conn, &id)?.ok_or_else(|| DomainError::not_found("workout session"))?;
            let sets = session_sets(conn, &id)?;
            let ids = source_ids(&id, &sets);
            Ok((json!([detail(&session, &sets)?]), ids))
        }
        "list_sessions" => {
            fields(map, &["limit", "state"])?;
            let limit = match map.get("limit") {
                None | Some(Value::Null) => 30,
                Some(_) => ranged(map, "limit", 1, 365)?,
            };
            let state = match map.get("state") {
                None | Some(Value::Null) => None,
                Some(_) => Some(one_of(map, "state", STATES)?),
            };
            let (sql, args): (&str, Vec<String>) = match &state {
                Some(state) => (
                    "SELECT data_json FROM gym_sessions WHERE state=?1 ORDER BY started_at DESC, id DESC LIMIT ?2",
                    vec![state.clone(), limit.to_string()],
                ),
                None => (
                    "SELECT data_json FROM gym_sessions ORDER BY started_at DESC, id DESC LIMIT ?1",
                    vec![limit.to_string()],
                ),
            };
            let mut stmt = conn.prepare(sql)?;
            let bound: Vec<&dyn rusqlite::ToSql> = args.iter().map(|a| a as &dyn rusqlite::ToSql).collect();
            let raw: Vec<String> = stmt.query_map(bound.as_slice(), |r| r.get(0))?.collect::<Result<_, _>>()?;
            let mut rows = Vec::with_capacity(raw.len());
            let mut ids = Vec::with_capacity(raw.len());
            for text in raw {
                let session: Value = serde_json::from_str(&text)?;
                let id = session["id"].as_str().unwrap_or_default().to_string();
                let sets = session_sets(conn, &id)?;
                rows.push(json!({
                    "id": session["id"],
                    "label": session["label"],
                    "day_id": session["day_id"],
                    "date": session["date"],
                    "state": session["state"],
                    "metrics": metrics(&session, &sets)?,
                }));
                ids.push(id);
            }
            Ok((Value::Array(rows), ids))
        }
        "previous_performance" => {
            fields(map, &["exercise_key", "before_session_id"])?;
            let exercise_key = identifier(map, "exercise_key")?;
            let exclude = match map.get("before_session_id") {
                None | Some(Value::Null) => String::new(),
                Some(_) => identifier(map, "before_session_id")?,
            };
            // The most recent completed session that holds a completed working set for this exercise.
            let found: Option<(String, String)> = conn
                .query_row(
                    "SELECT s.id, s.data_json FROM gym_sessions s \
                     JOIN gym_sets t ON t.session_id = s.id \
                     WHERE s.state='completed' AND s.id <> ?1 AND t.exercise_key=?2 \
                       AND t.set_type='working' AND t.completed=1 \
                     GROUP BY s.id ORDER BY s.started_at DESC, s.id DESC LIMIT 1",
                    params![exclude, exercise_key],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?;
            let Some((id, data)) = found else {
                return Ok((json!([]), vec![]));
            };
            let session: Value = serde_json::from_str(&data)?;
            let sets: Vec<Value> = session_sets(conn, &id)?
                .into_iter()
                .filter(|s| {
                    s["exercise_key"].as_str() == Some(&exercise_key)
                        && s["set_type"].as_str() == Some("working")
                        && s["completed"].as_bool() == Some(true)
                })
                .collect();
            Ok((
                json!([{
                    "exercise_key": exercise_key,
                    "session_id": session["id"],
                    "date": session["date"],
                    "label": session["label"],
                    "sets": sets,
                }]),
                vec![id],
            ))
        }
        _ => Err(DomainError::validation("name", "unknown gym query")),
    }
}

fn source_ids(session_id: &str, sets: &[Value]) -> Vec<String> {
    let mut ids = vec![session_id.to_string()];
    ids.extend(sets.iter().filter_map(|s| s["id"].as_str().map(str::to_string)));
    ids
}

fn detail(session: &Value, sets: &[Value]) -> DomainResult<Value> {
    Ok(json!({
        "session": session,
        "metrics": metrics(session, sets)?,
        "exercises": breakdown(session, sets),
    }))
}

// ---------------------------------------------------------------------------------------------
// Backup and restore (GYM-02). Gym training travels inside the Health backup, in its own `gym`
// section, so one file is still the whole domain. Every record is the Kernel's own stored payload,
// so a restore revalidates it with the same rules that let it be written in the first place:
// loads stay exact integers, units and equipment variants stay as recorded, and a session keeps
// its own plan snapshot, timestamps and pause intervals.

/// Which projection table holds an aggregate type.
fn table_of(aggregate_type: &str) -> DomainResult<&'static str> {
    match aggregate_type {
        "gym_program" => Ok("gym_programs"),
        "gym_session" => Ok("gym_sessions"),
        "gym_set" => Ok("gym_sets"),
        other => Err(DomainError::validation("aggregate_type", format!("not a gym aggregate: {other}"))),
    }
}

fn payloads(conn: &Connection, table: &str) -> DomainResult<Vec<Value>> {
    let mut stmt = conn.prepare(&format!("SELECT data_json FROM {table} ORDER BY id"))?;
    let raw: Vec<String> = stmt.query_map([], |r| r.get(0))?.collect::<Result<_, _>>()?;
    raw.iter().map(|text| Ok(serde_json::from_str(text)?)).collect()
}

/// What this device has deleted. Carried so a restore can keep a deleted workout deleted instead
/// of letting an older copy of the file bring it back.
fn deletions(conn: &Connection) -> DomainResult<Vec<Value>> {
    let mut stmt = conn.prepare(
        "SELECT aggregate_type, aggregate_id, deleted_at FROM tombstones \
         WHERE aggregate_type IN ('gym_program','gym_session','gym_set') \
         ORDER BY aggregate_type, aggregate_id",
    )?;
    let rows: Vec<(String, String, String)> =
        stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?.collect::<Result<_, _>>()?;
    Ok(rows
        .into_iter()
        .map(|(aggregate_type, id, deleted_at)| {
            json!({"aggregate_type": aggregate_type, "id": id, "deleted_at": deleted_at})
        })
        .collect())
}

/// The `gym` section of the Health backup.
pub fn export_section(conn: &Connection) -> DomainResult<Value> {
    Ok(json!({
        "programs": payloads(conn, "gym_programs")?,
        "sessions": payloads(conn, "gym_sessions")?,
        "sets": payloads(conn, "gym_sets")?,
        "deleted": deletions(conn)?,
    }))
}

fn list<'a>(map: &'a Map<String, Value>, key: &str) -> DomainResult<&'a [Value]> {
    match map.get(key) {
        None | Some(Value::Null) => Ok(&[]),
        Some(Value::Array(items)) => Ok(items.as_slice()),
        Some(_) => Err(DomainError::validation(key, "must be a list")),
    }
}

/// How many records a `gym` section holds, counted before anything is written.
pub fn section_len(section: &Value) -> DomainResult<usize> {
    let map = object(section)?;
    fields(map, &["programs", "sessions", "sets", "deleted"])?;
    let mut total = 0;
    for key in ["programs", "sessions", "sets", "deleted"] {
        total += list(map, key)?.len();
    }
    Ok(total)
}

fn current_payload(conn: &Connection, aggregate_type: &str, id: &str) -> DomainResult<Option<Value>> {
    load_json(conn, &format!("SELECT data_json FROM {} WHERE id=?1", table_of(aggregate_type)?), id)
}

/// Restore the `gym` section. Row numbers continue after the health records, so one import report
/// still accounts for every line of the file exactly once.
pub fn restore(conn: &Connection, ctx: &EventCtx, section: &Value, offset: u64) -> DomainResult<Vec<RowResult>> {
    let map = object(section)?;
    fields(map, &["programs", "sessions", "sets", "deleted"])?;
    let mut out = Vec::new();
    let mut n = offset;
    // Programs, then sessions, then sets: a set is read after the workout it belongs to.
    for (key, aggregate_type) in [("programs", "gym_program"), ("sessions", "gym_session"), ("sets", "gym_set")] {
        for raw in list(map, key)? {
            n += 1;
            out.push(restore_record(conn, ctx, aggregate_type, raw, n)?);
        }
    }
    for raw in list(map, "deleted")? {
        n += 1;
        out.push(restore_deletion(conn, ctx, raw, n)?);
    }
    Ok(out)
}

fn gym_row(
    n: u64,
    status: &str,
    reason: Option<&str>,
    aggregate_type: &str,
    id: &str,
    date: Option<String>,
    raw: &Value,
) -> RowResult {
    RowResult {
        row: n,
        status: status.to_string(),
        reason: reason.map(str::to_string),
        date,
        amount_minor: None,
        description: Some(aggregate_type.to_string()),
        record_id: if id.is_empty() { None } else { Some(id.to_string()) },
        warning: None,
        raw: raw.to_string().chars().take(300).collect(),
    }
}

fn restore_record(
    conn: &Connection,
    ctx: &EventCtx,
    aggregate_type: &str,
    raw: &Value,
    n: u64,
) -> DomainResult<RowResult> {
    let id = raw.get("id").and_then(Value::as_str).unwrap_or_default().to_string();
    let date = raw.get("date").and_then(Value::as_str).map(str::to_string);
    // The same validation that guards a live write, so a hand-edited backup cannot widen a rule.
    let checked = object(raw).and_then(|map| {
        super::record_id(&id)?;
        match aggregate_type {
            "gym_program" => validate_program(&id, map).map(|_| ()),
            "gym_session" => validate_session(&id, map).map(|_| ()),
            _ => validate_set(&id, map).map(|_| ()),
        }
    });
    if let Err(error) = checked {
        return Ok(gym_row(n, "rejected", Some(&error.to_string()), aggregate_type, &id, date, raw));
    }
    if events::is_tombstoned(conn, aggregate_type, &id)? {
        return Ok(gym_row(
            n,
            "rejected",
            Some("deleted on this device; not restored"),
            aggregate_type,
            &id,
            date,
            raw,
        ));
    }
    if let Some(current) = current_payload(conn, aggregate_type, &id)? {
        return Ok(if events::canonical(&current) == events::canonical(raw) {
            gym_row(n, "duplicate", None, aggregate_type, &id, date, raw)
        } else {
            gym_row(
                n,
                "rejected",
                Some("a different record with this id already exists"),
                aggregate_type,
                &id,
                date,
                raw,
            )
        });
    }
    let event = events::append_local(conn, ctx, draft(aggregate_type, &id, "imported", raw.clone()))?;
    apply(conn, &event)?;
    Ok(gym_row(n, "accepted", None, aggregate_type, &id, date, raw))
}

/// A deletion recorded in the file. It is never allowed to remove a workout this device still
/// holds: restoring a backup must not be a way to destroy data. It only keeps a record that is
/// already absent from coming back later.
fn restore_deletion(conn: &Connection, ctx: &EventCtx, raw: &Value, n: u64) -> DomainResult<RowResult> {
    let map = match object(raw) {
        Ok(map) => map,
        Err(error) => return Ok(gym_row(n, "rejected", Some(&error.to_string()), "gym_deleted", "", None, raw)),
    };
    let checked = (|| -> DomainResult<(String, String)> {
        fields(map, &["aggregate_type", "id", "deleted_at"])?;
        let aggregate_type = one_of(map, "aggregate_type", AGGREGATES)?;
        let id = super::record_id(&text(map, "id", 64)?)?;
        timestamp(map, "deleted_at")?;
        Ok((aggregate_type, id))
    })();
    let (aggregate_type, id) = match checked {
        Ok(pair) => pair,
        Err(error) => return Ok(gym_row(n, "rejected", Some(&error.to_string()), "gym_deleted", "", None, raw)),
    };
    if events::is_tombstoned(conn, &aggregate_type, &id)? {
        return Ok(gym_row(n, "duplicate", None, &aggregate_type, &id, None, raw));
    }
    if current_payload(conn, &aggregate_type, &id)?.is_some() {
        return Ok(gym_row(
            n,
            "rejected",
            Some("still recorded on this device; restoring a backup never deletes a workout"),
            &aggregate_type,
            &id,
            None,
            raw,
        ));
    }
    let event = events::append_local(conn, ctx, tombstone(&aggregate_type, id.clone()))?;
    apply(conn, &event)?;
    Ok(gym_row(n, "accepted", None, &aggregate_type, &id, None, raw))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_default_program_is_five_training_days_two_rest_days_and_ninety_working_sets() {
        let days = default_days();
        let days = days.as_array().expect("seven days");
        assert_eq!(days.len(), PLAN_DAYS);
        let training = days.iter().filter(|d| d["day_type"] == "training").count();
        let rest = days.iter().filter(|d| d["day_type"] == "rest").count();
        assert_eq!((training, rest), (5, 2));
        let planned: i64 = days
            .iter()
            .flat_map(|d| d["exercises"].as_array().cloned().unwrap_or_default())
            .filter_map(|e| e["planned_sets"].as_i64())
            .sum();
        assert_eq!(planned, 90);
        for day in days.iter().filter(|d| d["day_type"] == "rest") {
            assert_eq!(day["exercises"].as_array().unwrap().len(), 0);
        }
    }

    #[test]
    fn the_default_program_passes_its_own_validation() {
        let payload = json!({
            "id": "program-1",
            "kind": "gym_program",
            "name": DEFAULT_PROGRAM_NAME,
            "status": "active",
            "anchor_date": "2026-10-22",
            "plan_version": 1,
            "created_at": "2026-10-22T10:00:00.000Z",
            "updated_at": "2026-10-22T10:00:00.000Z",
            "days": default_days(),
        });
        validate_program("program-1", payload.as_object().unwrap()).expect("valid default program");
    }

    #[test]
    fn timestamps_are_utc_and_parse_to_the_right_instant() {
        assert_eq!(epoch_ms("1970-01-01T00:00:00Z").unwrap(), 0);
        assert_eq!(epoch_ms("1970-01-01T00:00:01.250Z").unwrap(), 1_250);
        assert_eq!(epoch_ms("2026-10-22T18:30:00Z").unwrap() - epoch_ms("2026-10-22T18:00:00Z").unwrap(), 1_800_000);
        for bad in [
            "2026-10-22",
            "2026-10-22T18:30:00",
            "2026-10-22T18:30:00+02:00",
            "2026-13-01T00:00:00Z",
            "2026-10-22T24:00:00Z",
        ] {
            assert!(timestamp_value(bad, "at").is_err(), "{bad} must be refused");
        }
    }
}
