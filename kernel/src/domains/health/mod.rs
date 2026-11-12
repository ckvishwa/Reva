//! Manual and imported Health records. The Kernel stores facts and computes summaries; it does not
//! diagnose, recommend medication doses, or send health data to a network service.
//!
//! Provenance: every record carries an optional `source` (`manual` when absent, or `health_connect`)
//! and, for Health Connect records, the `origins` (app package names) Health Connect reported. Health
//! Connect days use one deterministic id per day and type, so a repeated import updates or confirms the
//! same record instead of adding a second one, and a day the user deleted is never re-imported.

use std::collections::{BTreeMap, BTreeSet};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};

use crate::civil::{self, Date};
use crate::error::{DomainError, DomainResult};
use crate::events::{self, Event, EventCtx, EventDraft};
use crate::import::{self, Options, Report, RowResult};
use crate::store::Migration;

pub mod gym;

pub const DOMAIN: &str = "health";
pub const COMMANDS: &[&str] = &[
    "workout.log",
    "sleep.log",
    "meal.log",
    "weight.log",
    "steps.log",
    "heart_rate.log",
    "medication.schedule",
    "medication.mark_taken",
    "record.delete",
    "source.delete",
];
pub const MIGRATION: Migration = Migration {
    version: 2,
    name: "health_records",
    sql: "CREATE TABLE health_records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, date TEXT NOT NULL, data_json TEXT NOT NULL, version INTEGER NOT NULL); \
          CREATE INDEX health_records_date ON health_records (date, kind);",
};

/// Every migration this domain owns, oldest first.
pub fn migrations() -> Vec<Migration> {
    vec![MIGRATION, gym::MIGRATION]
}

/// Every command this domain accepts, health records and gym training together.
pub fn command_names() -> Vec<String> {
    COMMANDS.iter().chain(gym::COMMANDS.iter()).map(|s| s.to_string()).collect()
}

/// The Health backup file written by `export("json")` and read back by `import_data("json")`.
/// v2 adds the `gym` section (GYM-02); a v1 file, which carries health records only, still restores.
pub const EXPORT_FORMAT: &str = "reva-health-v2";
/// The first backup format: health records, no gym training. Accepted on import, never written.
pub const EXPORT_FORMAT_V1: &str = "reva-health-v1";
/// Daily aggregates read from Health Connect on Android (`import_data("health_connect")`).
pub const HEALTH_CONNECT_FORMAT: &str = "reva-health-connect-v1";
const HEALTH_CONNECT: &str = "health_connect";
const MAX_ORIGINS: usize = 16;
const MAX_CONNECT_DAYS: usize = 400;
const BASE_FIELDS: &[&str] = &["id", "kind", "date", "created_at", "source", "origins"];

fn object(value: &Value) -> DomainResult<&Map<String, Value>> {
    value.as_object().ok_or_else(|| DomainError::validation("payload", "must be an object"))
}

fn fields(map: &Map<String, Value>, allowed: &[&str]) -> DomainResult<()> {
    for key in map.keys() {
        if !allowed.contains(&key.as_str()) {
            return Err(DomainError::validation(key, "unknown field"));
        }
    }
    Ok(())
}

fn text(map: &Map<String, Value>, field: &str, max: usize) -> DomainResult<String> {
    let raw = map.get(field).and_then(Value::as_str).ok_or_else(|| DomainError::validation(field, "required text"))?;
    let value = raw.trim();
    if value.is_empty() || value.chars().count() > max || value.chars().any(char::is_control) {
        return Err(DomainError::validation(field, "invalid text"));
    }
    Ok(value.to_string())
}

fn date(map: &Map<String, Value>, field: &str) -> DomainResult<String> {
    let raw = text(map, field, 10)?;
    Date::parse(&raw).ok_or_else(|| DomainError::validation(field, "must be a valid YYYY-MM-DD date"))?;
    Ok(raw)
}

fn ranged(map: &Map<String, Value>, field: &str, min: i64, max: i64) -> DomainResult<i64> {
    let value =
        map.get(field).and_then(Value::as_i64).ok_or_else(|| DomainError::validation(field, "required integer"))?;
    if !(min..=max).contains(&value) {
        return Err(DomainError::validation(field, "out of range"));
    }
    Ok(value)
}

fn positive(map: &Map<String, Value>, field: &str, max: i64) -> DomainResult<i64> {
    ranged(map, field, 1, max)
}

fn nonnegative(map: &Map<String, Value>, field: &str, max: i64) -> DomainResult<i64> {
    ranged(map, field, 0, max)
}

fn record_id(raw: &str) -> DomainResult<String> {
    let ok = !raw.is_empty() && raw.len() <= 64 && raw.chars().all(|c| c.is_ascii_alphanumeric() || c == '-');
    if !ok {
        return Err(DomainError::validation("id", "invalid record id"));
    }
    Ok(raw.to_string())
}

/// App package names as Health Connect reports them, sorted and de-duplicated.
fn origins(value: &Value) -> DomainResult<Vec<String>> {
    let items = value.as_array().ok_or_else(|| DomainError::validation("origins", "must be a list"))?;
    if items.len() > MAX_ORIGINS {
        return Err(DomainError::validation("origins", "too many"));
    }
    let mut out = BTreeSet::new();
    for item in items {
        let name = item.as_str().unwrap_or("");
        let ok = !name.is_empty()
            && name.len() <= 255
            && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_');
        if !ok {
            return Err(DomainError::validation("origins", "invalid app package name"));
        }
        out.insert(name.to_string());
    }
    Ok(out.into_iter().collect())
}

fn source_of(data: &Value) -> &str {
    data["source"].as_str().unwrap_or("manual")
}

/// The deterministic id of a Health Connect day record.
fn connect_id(record_kind: &str, day: &str) -> String {
    match record_kind {
        "steps_day" => format!("hc-steps-{day}"),
        _ => format!("hc-hr-{day}"),
    }
}

/// Checks a stored or imported record and returns its `(kind, date)`. Every write path ends here.
fn validate_record(id: &str, payload: &Map<String, Value>) -> DomainResult<(String, String)> {
    let kind = text(payload, "kind", 32)?;
    let day = date(payload, "date")?;
    if text(payload, "id", 64)? != id {
        return Err(DomainError::validation("id", "record id mismatch"));
    }
    text(payload, "created_at", 64)?;
    let source = match payload.get("source") {
        None => "manual".to_string(),
        Some(_) => text(payload, "source", 32)?,
    };
    match source.as_str() {
        "manual" => {
            if payload.contains_key("origins") {
                return Err(DomainError::validation("origins", "only Health Connect records carry origins"));
            }
        }
        HEALTH_CONNECT => {
            if !matches!(kind.as_str(), "steps_day" | "heart_rate_day") {
                return Err(DomainError::validation(
                    "source",
                    "Health Connect provides only daily steps and heart rate",
                ));
            }
            if id != connect_id(&kind, &day) {
                return Err(DomainError::validation("id", "Health Connect record id does not match its day"));
            }
            origins(payload.get("origins").unwrap_or(&json!([])))?;
        }
        _ => return Err(DomainError::validation("source", "unknown source")),
    }
    let extra: &[&str] = match kind.as_str() {
        "workout" => {
            text(payload, "activity", 120)?;
            positive(payload, "duration_minutes", 1440)?;
            &["activity", "duration_minutes"]
        }
        "sleep" => {
            positive(payload, "duration_minutes", 1440)?;
            &["duration_minutes"]
        }
        "meal" => {
            text(payload, "description", 500)?;
            &["description"]
        }
        "weight" => {
            positive(payload, "weight_grams", 1_000_000)?;
            &["weight_grams"]
        }
        "steps_day" => {
            nonnegative(payload, "steps", 200_000)?;
            &["steps"]
        }
        "heart_rate_sample" => {
            positive(payload, "bpm", 300)?;
            &["bpm"]
        }
        "heart_rate_day" => {
            if source != HEALTH_CONNECT {
                return Err(DomainError::validation("kind", "daily heart-rate ranges come only from Health Connect"));
            }
            let (min, max) = (positive(payload, "min_bpm", 300)?, positive(payload, "max_bpm", 300)?);
            if min > max {
                return Err(DomainError::validation("min_bpm", "greater than max_bpm"));
            }
            positive(payload, "samples", 1_000_000)?;
            &["min_bpm", "max_bpm", "samples"]
        }
        "medication_schedule" => {
            text(payload, "name", 120)?;
            &["name"]
        }
        "medication_taken" => {
            record_id(&text(payload, "schedule_id", 64)?)?;
            &["schedule_id"]
        }
        _ => return Err(DomainError::validation("kind", "unknown health record")),
    };
    let allowed: Vec<&str> = BASE_FIELDS.iter().chain(extra.iter()).copied().collect();
    fields(payload, &allowed)?;
    Ok((kind, day))
}

fn draft(kind: &str, date: String, mut data: Map<String, Value>) -> EventDraft {
    let id = uuid::Uuid::new_v4().to_string();
    data.insert("id".into(), json!(id));
    data.insert("date".into(), json!(date));
    data.insert("kind".into(), json!(kind));
    data.insert("created_at".into(), json!(civil::now_iso()));
    EventDraft {
        aggregate_type: "health_record".into(),
        aggregate_id: id,
        kind: format!("{kind}.created"),
        tombstone: false,
        payload: Value::Object(data),
    }
}

fn tombstone(id: String) -> EventDraft {
    EventDraft {
        aggregate_type: "health_record".into(),
        aggregate_id: id,
        kind: "health_record.deleted".into(),
        tombstone: true,
        payload: json!({}),
    }
}

fn manual_steps_on(conn: &Connection, day: &str) -> DomainResult<i64> {
    Ok(conn.query_row(
        "SELECT COUNT(*) FROM health_records WHERE kind='steps_day' AND date=?1 \
         AND COALESCE(json_extract(data_json,'$.source'),'manual')='manual'",
        [day],
        |r| r.get(0),
    )?)
}

fn schedule_start(conn: &Connection, schedule_id: &str) -> DomainResult<Option<String>> {
    Ok(conn
        .query_row("SELECT date FROM health_records WHERE id=?1 AND kind='medication_schedule'", [schedule_id], |r| {
            r.get(0)
        })
        .optional()?)
}

fn taken_on(conn: &Connection, schedule_id: &str, day: &str) -> DomainResult<i64> {
    Ok(conn.query_row(
        "SELECT COUNT(*) FROM health_records WHERE kind='medication_taken' AND date=?1 \
         AND json_extract(data_json,'$.schedule_id')=?2",
        params![day, schedule_id],
        |r| r.get(0),
    )?)
}

pub fn command(conn: &Connection, kind: &str, payload: &Value) -> DomainResult<Vec<EventDraft>> {
    if kind.starts_with("gym.") {
        return gym::command(conn, kind, payload);
    }
    let map = object(payload)?;
    let (record_kind, record_date, data) = match kind {
        "workout.log" => {
            fields(map, &["date", "activity", "duration_minutes"])?;
            (
                "workout",
                date(map, "date")?,
                json!({"activity":text(map,"activity",120)?,"duration_minutes":positive(map,"duration_minutes",1440)?}),
            )
        }
        "sleep.log" => {
            fields(map, &["date", "duration_minutes"])?;
            ("sleep", date(map, "date")?, json!({"duration_minutes":positive(map,"duration_minutes",1440)?}))
        }
        "meal.log" => {
            fields(map, &["date", "description"])?;
            ("meal", date(map, "date")?, json!({"description":text(map,"description",500)?}))
        }
        "weight.log" => {
            fields(map, &["date", "weight_grams"])?;
            ("weight", date(map, "date")?, json!({"weight_grams":positive(map,"weight_grams",1_000_000)?}))
        }
        "steps.log" => {
            fields(map, &["date", "steps"])?;
            let day = date(map, "date")?;
            if manual_steps_on(conn, &day)? != 0 {
                return Err(DomainError::conflict(
                    "steps already recorded for this day; delete the old entry before replacing it",
                ));
            }
            ("steps_day", day, json!({"steps":nonnegative(map,"steps",200_000)?}))
        }
        "heart_rate.log" => {
            fields(map, &["date", "bpm"])?;
            ("heart_rate_sample", date(map, "date")?, json!({"bpm":positive(map,"bpm",300)?}))
        }
        "medication.schedule" => {
            fields(map, &["name", "start_date"])?;
            ("medication_schedule", date(map, "start_date")?, json!({"name":text(map,"name",120)?}))
        }
        "medication.mark_taken" => {
            fields(map, &["schedule_id", "date"])?;
            let schedule_id = text(map, "schedule_id", 64)?;
            let start =
                schedule_start(conn, &schedule_id)?.ok_or_else(|| DomainError::not_found("medication schedule"))?;
            let day = date(map, "date")?;
            if day < start {
                return Err(DomainError::validation("date", "before schedule starts"));
            }
            if taken_on(conn, &schedule_id, &day)? != 0 {
                return Err(DomainError::conflict("medication already recorded as taken for this date"));
            }
            ("medication_taken", day, json!({"schedule_id":schedule_id}))
        }
        "record.delete" => {
            fields(map, &["id"])?;
            let id = text(map, "id", 64)?;
            let kind: Option<String> =
                conn.query_row("SELECT kind FROM health_records WHERE id=?1", [&id], |r| r.get(0)).optional()?;
            if kind.is_none() {
                return Err(DomainError::not_found("health record"));
            }
            let mut ids = Vec::new();
            if kind.as_deref() == Some("medication_schedule") {
                let mut stmt = conn.prepare("SELECT id FROM health_records WHERE kind='medication_taken' AND json_extract(data_json,'$.schedule_id')=?1 ORDER BY id")?;
                ids.extend(stmt.query_map([&id], |r| r.get::<_, String>(0))?.collect::<Result<Vec<_>, _>>()?);
            }
            ids.push(id);
            return Ok(ids.into_iter().map(tombstone).collect());
        }
        "source.delete" => {
            // Forget everything read from one external source (only Health Connect exists). Manual entries
            // are deleted one at a time with `record.delete`.
            fields(map, &["source"])?;
            if text(map, "source", 32)? != HEALTH_CONNECT {
                return Err(DomainError::validation("source", "only health_connect records can be deleted together"));
            }
            let mut stmt =
                conn.prepare("SELECT id FROM health_records WHERE json_extract(data_json,'$.source')=?1 ORDER BY id")?;
            let ids = stmt.query_map([HEALTH_CONNECT], |r| r.get::<_, String>(0))?.collect::<Result<Vec<_>, _>>()?;
            if ids.is_empty() {
                return Err(DomainError::not_found("no records from this source"));
            }
            return Ok(ids.into_iter().map(tombstone).collect());
        }
        _ => return Err(DomainError::validation("kind", "unknown health command")),
    };
    let data = data.as_object().cloned().ok_or_else(|| DomainError::internal("record data"))?;
    Ok(vec![draft(record_kind, record_date, data)])
}

pub fn apply(conn: &Connection, event: &Event) -> DomainResult<()> {
    if gym::owns(&event.aggregate_type) {
        return gym::apply(conn, event);
    }
    if event.aggregate_type != "health_record" {
        return Err(DomainError::validation("aggregate_type", "not a health record"));
    }
    if event.tombstone {
        conn.execute("DELETE FROM health_records WHERE id=?1", [&event.aggregate_id])?;
        return Ok(());
    }
    if events::is_tombstoned(conn, &event.aggregate_type, &event.aggregate_id)? {
        return Ok(());
    }
    let payload = object(&event.payload)?;
    let (kind, day) = validate_record(&event.aggregate_id, payload)?;
    if event.kind != format!("{kind}.created") && event.kind != format!("{kind}.updated") {
        return Err(DomainError::validation("event", "health record identity or kind mismatch"));
    }
    conn.execute("INSERT INTO health_records (id,kind,date,data_json,version) VALUES (?1,?2,?3,?4,?5) \
                  ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,date=excluded.date,data_json=excluded.data_json,version=excluded.version",
        params![event.aggregate_id,kind,day,event.payload.to_string(),event.version])?;
    Ok(())
}

pub fn rebuild(conn: &Connection) -> DomainResult<u64> {
    conn.execute("DELETE FROM health_records", [])?;
    gym::clear(conn)?;
    let mut count = 0;
    for event in events::all_ordered(conn)? {
        apply(conn, &event)?;
        count += 1;
    }
    Ok(count)
}

/// One day's step records by source. A manual entry is the user's own statement and is what totals use;
/// a Health Connect day for the same date is reported next to it, never added to it.
#[derive(Default)]
struct StepsDay {
    manual: Option<(String, String, i64)>,
    connect: Option<(String, String, i64)>,
}

impl StepsDay {
    fn add(&mut self, id: &str, data: &Value) -> DomainResult<()> {
        let count = data["steps"].as_i64().ok_or_else(|| DomainError::validation("steps", "corrupt steps"))?;
        let stamp = data["created_at"].as_str().unwrap_or("").to_string();
        let slot = if source_of(data) == HEALTH_CONNECT { &mut self.connect } else { &mut self.manual };
        let replace = slot.as_ref().is_none_or(|(old_stamp, old_id, _)| (&stamp, id) > (old_stamp, old_id.as_str()));
        if replace {
            *slot = Some((stamp, id.to_string(), count));
        }
        Ok(())
    }

    fn chosen(&self) -> Option<(&str, &str, i64)> {
        self.manual
            .as_ref()
            .map(|(_, id, n)| ("manual", id.as_str(), *n))
            .or_else(|| self.connect.as_ref().map(|(_, id, n)| (HEALTH_CONNECT, id.as_str(), *n)))
    }

    fn conflict(&self) -> bool {
        matches!((&self.manual, &self.connect), (Some((_, _, a)), Some((_, _, b))) if a != b)
    }

    fn ids(&self) -> Vec<String> {
        self.manual.iter().chain(self.connect.iter()).map(|(_, id, _)| id.clone()).collect()
    }
}

/// Manual readings plus Health Connect daily ranges: count, minimum and maximum, without interpretation.
#[derive(Default)]
struct HeartRate {
    count: i64,
    min: Option<i64>,
    max: Option<i64>,
}

impl HeartRate {
    fn add(&mut self, kind: &str, data: &Value) -> DomainResult<()> {
        let corrupt = || DomainError::validation("bpm", "corrupt heart rate");
        let (count, low, high) = if kind == "heart_rate_day" {
            (
                data["samples"].as_i64().ok_or_else(corrupt)?,
                data["min_bpm"].as_i64().ok_or_else(corrupt)?,
                data["max_bpm"].as_i64().ok_or_else(corrupt)?,
            )
        } else {
            let bpm = data["bpm"].as_i64().ok_or_else(corrupt)?;
            (1, bpm, bpm)
        };
        self.count += count;
        self.min = Some(self.min.map_or(low, |old| old.min(low)));
        self.max = Some(self.max.map_or(high, |old| old.max(high)));
        Ok(())
    }
}

type Row = (String, String, String, Value);

fn rows_where(conn: &Connection, sql: &str, args: &[&dyn rusqlite::ToSql]) -> DomainResult<Vec<Row>> {
    let mut stmt = conn.prepare(sql)?;
    let raw = stmt
        .query_map(args, |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    raw.into_iter().map(|(id, kind, day, data)| Ok((id, kind, day, serde_json::from_str(&data)?))).collect()
}

pub fn query(conn: &Connection, name: &str, params: &Value) -> DomainResult<(Value, Vec<String>)> {
    if gym::QUERIES.contains(&name) {
        return gym::query(conn, name, params);
    }
    let params = object(params)?;
    fields(params, &["date"])?;
    let day = date(params, "date")?;
    if name == "weekly_summary" {
        return weekly(conn, &day);
    }
    let records = rows_where(
        conn,
        "SELECT id,kind,date,data_json FROM health_records WHERE date=?1 OR (kind='medication_schedule' AND date<=?1) ORDER BY date,id",
        &[&day],
    )?;
    let current: Vec<&Row> =
        records.iter().filter(|(_, kind, d, _)| d == &day && kind != "medication_schedule").collect();
    match name {
        "list_schedules" => {
            let schedules: Vec<&Row> = records.iter().filter(|(_, kind, _, _)| kind == "medication_schedule").collect();
            Ok((
                Value::Array(schedules.iter().map(|(_, _, _, v)| v.clone()).collect()),
                schedules.iter().map(|(id, _, _, _)| id.clone()).collect(),
            ))
        }
        "daily_records" => Ok((
            Value::Array(current.iter().map(|(_, _, _, v)| v.clone()).collect()),
            current.iter().map(|(id, _, _, _)| id.clone()).collect(),
        )),
        "daily_summary" => {
            let minutes = |kind: &str| -> i64 {
                current
                    .iter()
                    .filter(|(_, k, _, _)| k == kind)
                    .filter_map(|(_, _, _, v)| v["duration_minutes"].as_i64())
                    .sum()
            };
            let count = |kind: &str| current.iter().filter(|(_, k, _, _)| k == kind).count();
            let mut steps = StepsDay::default();
            let mut heart = HeartRate::default();
            for (id, kind, _, data) in &current {
                match kind.as_str() {
                    "steps_day" => steps.add(id, data)?,
                    "heart_rate_sample" | "heart_rate_day" => heart.add(kind, data)?,
                    _ => {}
                }
            }
            let weight_grams = current
                .iter()
                .filter(|(_, k, _, _)| k == "weight")
                .max_by(|a, b| (a.3["created_at"].as_str(), &a.0).cmp(&(b.3["created_at"].as_str(), &b.0)))
                .and_then(|(_, _, _, v)| v["weight_grams"].as_i64());
            let schedule_ids: BTreeSet<&str> = records
                .iter()
                .filter(|(_, k, _, _)| k == "medication_schedule")
                .map(|(id, _, _, _)| id.as_str())
                .collect();
            let medications_taken = current
                .iter()
                .filter(|(_, k, _, _)| k == "medication_taken")
                .filter_map(|(_, _, _, v)| v["schedule_id"].as_str())
                .filter(|id| schedule_ids.contains(id))
                .collect::<BTreeSet<_>>()
                .len();
            let chosen = steps.chosen();
            let ids = records
                .iter()
                .filter(|(_, kind, d, _)| d == &day || kind == "medication_schedule")
                .map(|(id, _, _, _)| id.clone())
                .collect();
            Ok((
                json!([{"date":day,"workout_minutes":minutes("workout"),"workout_count":count("workout"),
                "sleep_minutes":minutes("sleep"),"sleep_count":count("sleep"),"meal_count":count("meal"),
                "steps":chosen.map(|(_, _, n)| n),"steps_source":chosen.map(|(s, _, _)| s),
                "steps_count":count("steps_day"),"steps_conflict":steps.conflict(),
                "steps_manual":steps.manual.as_ref().map(|(_, _, n)| *n),
                "steps_health_connect":steps.connect.as_ref().map(|(_, _, n)| *n),
                "heart_rate_count":heart.count,"heart_rate_min_bpm":heart.min,"heart_rate_max_bpm":heart.max,
                "weight_grams":weight_grams,"medications_scheduled":schedule_ids.len(),
                "medications_taken":medications_taken}]),
                ids,
            ))
        }
        _ => Err(DomainError::validation("name", "unknown health query")),
    }
}

fn weekly(conn: &Connection, day: &str) -> DomainResult<(Value, Vec<String>)> {
    let end = Date::parse(day).ok_or_else(|| DomainError::validation("date", "invalid date"))?;
    let start = end.add_days(-6).to_iso();
    let rows = rows_where(
        conn,
        "SELECT id,kind,date,data_json FROM health_records \
         WHERE (date>=?1 AND date<=?2) OR (kind='medication_schedule' AND date<=?2) ORDER BY date,id",
        &[&start, &day],
    )?;
    let mut workout_minutes = 0_i64;
    let mut workout_count = 0;
    let mut sleep_minutes = 0_i64;
    let mut sleep_count = 0;
    let mut meal_count = 0;
    let mut steps_by_day = BTreeMap::<String, StepsDay>::new();
    let mut heart = HeartRate::default();
    let mut scheduled = Vec::new();
    let mut taken = Vec::new();
    let mut ids = Vec::new();
    for (id, kind, record_day, data) in rows {
        match kind.as_str() {
            "workout" => {
                workout_count += 1;
                workout_minutes += data["duration_minutes"]
                    .as_i64()
                    .ok_or_else(|| DomainError::validation("duration_minutes", "corrupt workout"))?;
                ids.push(id);
            }
            "sleep" => {
                sleep_count += 1;
                sleep_minutes += data["duration_minutes"]
                    .as_i64()
                    .ok_or_else(|| DomainError::validation("duration_minutes", "corrupt sleep"))?;
                ids.push(id);
            }
            "meal" => {
                meal_count += 1;
                ids.push(id);
            }
            "steps_day" => steps_by_day.entry(record_day).or_default().add(&id, &data)?,
            "heart_rate_sample" | "heart_rate_day" => {
                heart.add(&kind, &data)?;
                ids.push(id);
            }
            "medication_schedule" => {
                scheduled.push((id.clone(), record_day.clone()));
                ids.push(id);
            }
            "medication_taken" => {
                if let Some(schedule_id) = data["schedule_id"].as_str() {
                    taken.push((schedule_id.to_string(), record_day.clone(), id));
                }
            }
            _ => {}
        }
    }
    let mut medication_expected = 0_i64;
    let mut medication_taken = 0_i64;
    for (schedule_id, schedule_start) in &scheduled {
        let active_start = schedule_start.max(&start);
        let start_date =
            Date::parse(active_start).ok_or_else(|| DomainError::validation("date", "invalid schedule"))?;
        medication_expected += end.to_days() - start_date.to_days() + 1;
        let mut days = BTreeSet::new();
        for (id, taken_day, record_id) in &taken {
            if id == schedule_id && taken_day >= active_start && days.insert(taken_day) {
                medication_taken += 1;
                ids.push(record_id.clone());
            }
        }
    }
    let mut steps_total = 0_i64;
    let mut steps_days = 0;
    let mut conflict_dates = Vec::new();
    for (record_day, steps) in &steps_by_day {
        if let Some((_, _, count)) = steps.chosen() {
            steps_total += count;
            steps_days += 1;
        }
        if steps.conflict() {
            conflict_dates.push(record_day.clone());
        }
        ids.extend(steps.ids());
    }
    Ok((
        json!([{"start_date":start,"end_date":day,"workout_minutes":workout_minutes,
        "workout_count":workout_count,"sleep_minutes":sleep_minutes,"sleep_count":sleep_count,
        "meal_count":meal_count,"steps_total":steps_total,"steps_days":steps_days,
        "steps_conflict_dates":conflict_dates,
        "heart_rate_count":heart.count,"heart_rate_min_bpm":heart.min,"heart_rate_max_bpm":heart.max,
        "medication_expected":medication_expected,"medication_taken":medication_taken}]),
        ids,
    ))
}

pub fn digest_rows(conn: &Connection) -> DomainResult<Vec<(String, String)>> {
    let mut stmt = conn.prepare("SELECT id,data_json FROM health_records ORDER BY id")?;
    let rows = stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<Result<_, _>>()?;
    Ok(rows)
}

/// Every projection row in this domain, for `projection_digest`.
pub fn digest_all(conn: &Connection) -> DomainResult<Vec<(String, String)>> {
    let mut rows = digest_rows(conn)?;
    rows.extend(gym::digest_rows(conn)?);
    Ok(rows)
}

pub fn export(conn: &Connection, format: &str) -> DomainResult<Vec<u8>> {
    if format != "json" {
        return Err(DomainError::validation("format", "Health supports JSON export only"));
    }
    let records: Vec<Value> =
        digest_rows(conn)?.into_iter().map(|(_, v)| serde_json::from_str(&v)).collect::<Result<_, _>>()?;
    Ok(serde_json::to_vec_pretty(&json!({"format":EXPORT_FORMAT,"records":records,"gym":gym::export_section(conn)?}))?)
}

// ---------------------------------------------------------------------------------------------
// Import: the Health JSON backup and Health Connect daily aggregates. Every row is accepted, a
// duplicate, or rejected with a reason; a deleted record is never brought back.

struct RowInfo {
    day: Option<String>,
    id: Option<String>,
    kind: Option<String>,
}

fn row(n: u64, status: &str, reason: Option<String>, info: &RowInfo, raw: &Value) -> RowResult {
    RowResult {
        row: n,
        status: status.to_string(),
        reason,
        date: info.day.clone(),
        amount_minor: None,
        description: info.kind.clone(),
        record_id: info.id.clone(),
        warning: None,
        raw: raw.to_string().chars().take(300).collect(),
    }
}

fn existing(conn: &Connection, id: &str) -> DomainResult<Option<Value>> {
    let data: Option<String> =
        conn.query_row("SELECT data_json FROM health_records WHERE id=?1", [id], |r| r.get(0)).optional()?;
    Ok(match data {
        Some(text) => Some(serde_json::from_str(&text)?),
        None => None,
    })
}

fn append(conn: &Connection, ctx: &EventCtx, id: &str, kind: &str, verb: &str, payload: Value) -> DomainResult<()> {
    let draft = EventDraft {
        aggregate_type: "health_record".into(),
        aggregate_id: id.to_string(),
        kind: format!("{kind}.{verb}"),
        tombstone: false,
        payload,
    };
    let event = events::append_local(conn, ctx, draft)?;
    apply(conn, &event)
}

/// `import_data` for the Health domain. `conn` must be inside an open transaction.
pub fn import(
    conn: &Connection,
    ctx: &EventCtx,
    format: &str,
    bytes: &[u8],
    options: &Options,
    now: &str,
) -> DomainResult<Report> {
    if options.account_id.is_some() || !options.mapping.is_null() {
        return Err(DomainError::validation("options", "Health imports take only dry_run"));
    }
    if bytes.len() > import::MAX_FILE_BYTES {
        return Err(DomainError::validation("file", "larger than 8 MB"));
    }
    let document: Value =
        serde_json::from_slice(bytes).map_err(|e| DomainError::validation("file", format!("not valid JSON: {e}")))?;
    let top = document.as_object().ok_or_else(|| DomainError::validation("file", "must be a JSON object"))?;
    let rows = match format {
        "json" => restore(conn, ctx, top)?,
        HEALTH_CONNECT => connect(conn, ctx, top, now)?,
        _ => return Err(DomainError::validation("format", "Health imports json backups or health_connect days")),
    };
    let accepted = rows.iter().filter(|r| r.status == "accepted" || r.status == "updated").count() as u64;
    let duplicates = rows.iter().filter(|r| r.status == "duplicate").count() as u64;
    let rejected = rows.iter().filter(|r| r.status == "rejected").cloned().collect();
    Ok(Report {
        accepted,
        duplicates,
        rejected,
        rows,
        dry_run: options.dry_run,
        batch_id: uuid::Uuid::new_v4().to_string(),
    })
}

/// Why a valid backup record cannot be restored on this device, if it cannot.
fn restore_refusal(conn: &Connection, kind: &str, day: &str, raw: &Value) -> DomainResult<Option<&'static str>> {
    if kind == "steps_day" && source_of(raw) == "manual" && manual_steps_on(conn, day)? != 0 {
        return Ok(Some("steps already recorded by hand for this day"));
    }
    if kind == "medication_taken" {
        let schedule_id = raw["schedule_id"].as_str().unwrap_or("");
        return Ok(match schedule_start(conn, schedule_id)? {
            None => Some("medication schedule not found"),
            Some(start) if day < start.as_str() => Some("before schedule starts"),
            Some(_) if taken_on(conn, schedule_id, day)? != 0 => {
                Some("medication already recorded as taken for this date")
            }
            Some(_) => None,
        });
    }
    Ok(None)
}

fn restore(conn: &Connection, ctx: &EventCtx, top: &Map<String, Value>) -> DomainResult<Vec<RowResult>> {
    fields(top, &["format", "records", "gym"])?;
    let gym_section = match top.get("format").and_then(Value::as_str) {
        Some(EXPORT_FORMAT) => top.get("gym"),
        // A backup written before gym training existed. It restores as it always did.
        Some(EXPORT_FORMAT_V1) if !top.contains_key("gym") => None,
        Some(EXPORT_FORMAT_V1) => return Err(DomainError::validation("gym", "a v1 backup carries no gym training")),
        _ => return Err(DomainError::validation("format", "not a REVA Health backup")),
    };
    let records = top
        .get("records")
        .and_then(Value::as_array)
        .ok_or_else(|| DomainError::validation("records", "must be a list"))?;
    let gym_rows = match gym_section {
        Some(section) => gym::section_len(section)?,
        None => 0,
    };
    if records.len() + gym_rows > import::MAX_ROWS {
        return Err(DomainError::validation("records", "too many records"));
    }
    // Schedules first, so taken entries can be checked against them whatever order the file uses.
    let mut order: Vec<(usize, &Value)> = records.iter().enumerate().collect();
    order.sort_by_key(|(i, r)| (r["kind"].as_str() != Some("medication_schedule"), *i));
    let mut out = Vec::with_capacity(records.len());
    for (index, raw) in order {
        let n = index as u64 + 1;
        let id = raw["id"].as_str().map(str::to_string);
        let checked = raw
            .as_object()
            .ok_or_else(|| DomainError::validation("record", "must be an object"))
            .and_then(|map| record_id(id.as_deref().unwrap_or("")).and_then(|id| validate_record(&id, map)));
        let (kind, day) = match checked {
            Ok(v) => v,
            Err(e) => {
                out.push(row(n, "rejected", Some(e.to_string()), &RowInfo { day: None, id, kind: None }, raw));
                continue;
            }
        };
        let id = id.unwrap_or_default();
        let info = RowInfo { day: Some(day.clone()), id: Some(id.clone()), kind: Some(kind.clone()) };
        let refusal = if events::is_tombstoned(conn, "health_record", &id)? {
            Some("deleted on this device; not restored")
        } else if let Some(current) = existing(conn, &id)? {
            if events::canonical(&current) == events::canonical(raw) {
                out.push(row(n, "duplicate", None, &info, raw));
                continue;
            }
            Some("a different record with this id already exists")
        } else {
            restore_refusal(conn, &kind, &day, raw)?
        };
        if let Some(reason) = refusal {
            out.push(row(n, "rejected", Some(reason.to_string()), &info, raw));
            continue;
        }
        append(conn, ctx, &id, &kind, "created", raw.clone())?;
        out.push(row(n, "accepted", None, &info, raw));
    }
    // Gym training continues the same row numbering, so one report still covers the whole file.
    if let Some(section) = gym_section {
        out.extend(gym::restore(conn, ctx, section, records.len() as u64)?);
    }
    out.sort_by_key(|r| r.row);
    Ok(out)
}

/// One Health Connect day, checked: `(record kind, date, data fields)`.
fn connect_day(raw: &Value) -> DomainResult<(String, String, Map<String, Value>)> {
    let map = object(raw)?;
    let day = date(map, "date")?;
    let origins = origins(map.get("origins").unwrap_or(&json!([])))?;
    let (kind, data) = match map.get("type").and_then(Value::as_str) {
        Some("steps") => {
            fields(map, &["date", "type", "steps", "origins"])?;
            ("steps_day", json!({"steps":nonnegative(map,"steps",200_000)?}))
        }
        Some("heart_rate") => {
            fields(map, &["date", "type", "min_bpm", "max_bpm", "samples", "origins"])?;
            let (min, max) = (positive(map, "min_bpm", 300)?, positive(map, "max_bpm", 300)?);
            if min > max {
                return Err(DomainError::validation("min_bpm", "greater than max_bpm"));
            }
            ("heart_rate_day", json!({"min_bpm":min,"max_bpm":max,"samples":positive(map,"samples",1_000_000)?}))
        }
        _ => return Err(DomainError::validation("type", "must be steps or heart_rate")),
    };
    let mut data = data.as_object().cloned().unwrap_or_default();
    data.insert("origins".into(), json!(origins));
    Ok((kind.to_string(), day, data))
}

fn connect(conn: &Connection, ctx: &EventCtx, top: &Map<String, Value>, now: &str) -> DomainResult<Vec<RowResult>> {
    fields(top, &["format", "days"])?;
    if top.get("format").and_then(Value::as_str) != Some(HEALTH_CONNECT_FORMAT) {
        return Err(DomainError::validation("format", "not a Health Connect import"));
    }
    let days =
        top.get("days").and_then(Value::as_array).ok_or_else(|| DomainError::validation("days", "must be a list"))?;
    if days.len() > MAX_CONNECT_DAYS {
        return Err(DomainError::validation("days", "too many days"));
    }
    let mut seen = BTreeSet::new();
    let mut out = Vec::with_capacity(days.len());
    for (index, raw) in days.iter().enumerate() {
        let n = index as u64 + 1;
        let (kind, day, data) = match connect_day(raw) {
            Ok(v) => v,
            Err(e) => {
                out.push(row(n, "rejected", Some(e.to_string()), &RowInfo { day: None, id: None, kind: None }, raw));
                continue;
            }
        };
        let id = connect_id(&kind, &day);
        let info = RowInfo { day: Some(day.clone()), id: Some(id.clone()), kind: Some(kind.clone()) };
        if !seen.insert(id.clone()) {
            out.push(row(
                n,
                "rejected",
                Some("this day and type appear more than once in the import".into()),
                &info,
                raw,
            ));
            continue;
        }
        if events::is_tombstoned(conn, "health_record", &id)? {
            out.push(row(n, "rejected", Some("deleted on this device; not re-imported".into()), &info, raw));
            continue;
        }
        let current = existing(conn, &id)?;
        if current.as_ref().is_some_and(|c| data.iter().all(|(k, v)| &c[k] == v)) {
            out.push(row(n, "duplicate", None, &info, raw));
            continue;
        }
        let created_at = current.as_ref().and_then(|c| c["created_at"].as_str()).unwrap_or(now).to_string();
        let mut payload = data;
        payload.insert("id".into(), json!(id));
        payload.insert("kind".into(), json!(kind));
        payload.insert("date".into(), json!(day));
        payload.insert("created_at".into(), json!(created_at));
        payload.insert("source".into(), json!(HEALTH_CONNECT));
        let (verb, status) = if current.is_some() { ("updated", "updated") } else { ("created", "accepted") };
        append(conn, ctx, &id, &kind, verb, Value::Object(payload))?;
        out.push(row(n, status, None, &info, raw));
    }
    Ok(out)
}
