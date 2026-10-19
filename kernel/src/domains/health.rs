//! Manual Health records. The Kernel stores facts and computes summaries; it does not diagnose,
//! recommend medication doses, or send health data to a network service.

use std::collections::BTreeSet;

use rusqlite::{params, Connection};
use serde_json::{json, Map, Value};

use crate::civil::{self, Date};
use crate::error::{DomainError, DomainResult};
use crate::events::{self, Event, EventDraft};
use crate::store::Migration;

pub const DOMAIN: &str = "health";
pub const COMMANDS: &[&str] = &[
    "workout.log",
    "sleep.log",
    "meal.log",
    "weight.log",
    "medication.schedule",
    "medication.mark_taken",
    "record.delete",
];
pub const MIGRATION: Migration = Migration {
    version: 2,
    name: "health_records",
    sql: "CREATE TABLE health_records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, date TEXT NOT NULL, data_json TEXT NOT NULL, version INTEGER NOT NULL); \
          CREATE INDEX health_records_date ON health_records (date, kind);",
};

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

fn positive(map: &Map<String, Value>, field: &str, max: i64) -> DomainResult<i64> {
    let value =
        map.get(field).and_then(Value::as_i64).ok_or_else(|| DomainError::validation(field, "required integer"))?;
    if !(1..=max).contains(&value) {
        return Err(DomainError::validation(field, "out of range"));
    }
    Ok(value)
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

pub fn command(conn: &Connection, kind: &str, payload: &Value) -> DomainResult<Vec<EventDraft>> {
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
        "medication.schedule" => {
            fields(map, &["name", "start_date"])?;
            ("medication_schedule", date(map, "start_date")?, json!({"name":text(map,"name",120)?}))
        }
        "medication.mark_taken" => {
            fields(map, &["schedule_id", "date"])?;
            let schedule_id = text(map, "schedule_id", 64)?;
            let start: Option<String> = conn
                .query_row(
                    "SELECT date FROM health_records WHERE id=?1 AND kind='medication_schedule'",
                    [&schedule_id],
                    |r| r.get(0),
                )
                .ok();
            let start = start.ok_or_else(|| DomainError::not_found("medication schedule"))?;
            let day = date(map, "date")?;
            if day < start {
                return Err(DomainError::validation("date", "before schedule starts"));
            }
            let duplicate: i64 = conn.query_row("SELECT COUNT(*) FROM health_records WHERE kind='medication_taken' AND date=?1 AND json_extract(data_json,'$.schedule_id')=?2", params![day,schedule_id], |r|r.get(0))?;
            if duplicate != 0 {
                return Err(DomainError::conflict("medication already recorded as taken for this date"));
            }
            ("medication_taken", day, json!({"schedule_id":schedule_id}))
        }
        "record.delete" => {
            fields(map, &["id"])?;
            let id = text(map, "id", 64)?;
            let kind: Option<String> =
                conn.query_row("SELECT kind FROM health_records WHERE id=?1", [&id], |r| r.get(0)).ok();
            if kind.is_none() {
                return Err(DomainError::not_found("health record"));
            }
            let mut ids = Vec::new();
            if kind.as_deref() == Some("medication_schedule") {
                let mut stmt = conn.prepare("SELECT id FROM health_records WHERE kind='medication_taken' AND json_extract(data_json,'$.schedule_id')=?1 ORDER BY id")?;
                ids.extend(stmt.query_map([&id], |r| r.get::<_, String>(0))?.collect::<Result<Vec<_>, _>>()?);
            }
            ids.push(id);
            return Ok(ids
                .into_iter()
                .map(|id| EventDraft {
                    aggregate_type: "health_record".into(),
                    aggregate_id: id,
                    kind: "health_record.deleted".into(),
                    tombstone: true,
                    payload: json!({}),
                })
                .collect());
        }
        _ => return Err(DomainError::validation("kind", "unknown health command")),
    };
    let data = data.as_object().cloned().ok_or_else(|| DomainError::internal("record data"))?;
    Ok(vec![draft(record_kind, record_date, data)])
}

pub fn apply(conn: &Connection, event: &Event) -> DomainResult<()> {
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
    let kind = text(payload, "kind", 32)?;
    let day = date(payload, "date")?;
    if text(payload, "id", 64)? != event.aggregate_id || event.kind != format!("{kind}.created") {
        return Err(DomainError::validation("event", "health record identity or kind mismatch"));
    }
    match kind.as_str() {
        "workout" => {
            fields(payload, &["id", "kind", "date", "created_at", "activity", "duration_minutes"])?;
            text(payload, "activity", 120)?;
            positive(payload, "duration_minutes", 1440)?;
        }
        "sleep" => {
            fields(payload, &["id", "kind", "date", "created_at", "duration_minutes"])?;
            positive(payload, "duration_minutes", 1440)?;
        }
        "meal" => {
            fields(payload, &["id", "kind", "date", "created_at", "description"])?;
            text(payload, "description", 500)?;
        }
        "weight" => {
            fields(payload, &["id", "kind", "date", "created_at", "weight_grams"])?;
            positive(payload, "weight_grams", 1_000_000)?;
        }
        "medication_schedule" => {
            fields(payload, &["id", "kind", "date", "created_at", "name"])?;
            text(payload, "name", 120)?;
        }
        "medication_taken" => {
            fields(payload, &["id", "kind", "date", "created_at", "schedule_id"])?;
            text(payload, "schedule_id", 64)?;
        }
        _ => return Err(DomainError::validation("kind", "unknown health record")),
    }
    conn.execute("INSERT INTO health_records (id,kind,date,data_json,version) VALUES (?1,?2,?3,?4,?5) \
                  ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,date=excluded.date,data_json=excluded.data_json,version=excluded.version",
        params![event.aggregate_id,kind,day,event.payload.to_string(),event.version])?;
    Ok(())
}

pub fn rebuild(conn: &Connection) -> DomainResult<u64> {
    conn.execute("DELETE FROM health_records", [])?;
    let mut count = 0;
    for event in events::all_ordered(conn)? {
        apply(conn, &event)?;
        count += 1;
    }
    Ok(count)
}

pub fn query(conn: &Connection, name: &str, params: &Value) -> DomainResult<(Value, Vec<String>)> {
    let params = object(params)?;
    fields(params, &["date"])?;
    let day = date(params, "date")?;
    let mut stmt = conn.prepare("SELECT id,kind,date,data_json FROM health_records WHERE date=?1 OR (kind='medication_schedule' AND date<=?1) ORDER BY date,id")?;
    let mut records = Vec::new();
    for row in stmt.query_map([&day], |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?))
    })? {
        let (id, kind, record_date, data_json) = row?;
        records.push((id, kind, record_date, serde_json::from_str::<Value>(&data_json)?));
    }
    match name {
        "list_schedules" => {
            let items: Vec<_> = records
                .iter()
                .filter(|(_, kind, _, _)| kind == "medication_schedule")
                .map(|(_, _, _, v)| v.clone())
                .collect();
            let ids = records
                .iter()
                .filter(|(_, kind, _, _)| kind == "medication_schedule")
                .map(|(id, _, _, _)| id.clone())
                .collect();
            Ok((Value::Array(items), ids))
        }
        "daily_records" => {
            let items: Vec<_> = records
                .iter()
                .filter(|(_, kind, d, _)| d == &day && kind != "medication_schedule")
                .map(|(_, _, _, v)| v.clone())
                .collect();
            let ids = records
                .iter()
                .filter(|(_, kind, d, _)| d == &day && kind != "medication_schedule")
                .map(|(id, _, _, _)| id.clone())
                .collect();
            Ok((Value::Array(items), ids))
        }
        "daily_summary" => {
            let current: Vec<_> =
                records.iter().filter(|(_, kind, d, _)| d == &day && kind != "medication_schedule").collect();
            let workout_minutes: i64 = current
                .iter()
                .filter(|(_, k, _, _)| k == "workout")
                .filter_map(|(_, _, _, v)| v["duration_minutes"].as_i64())
                .sum();
            let workout_count = current.iter().filter(|(_, k, _, _)| k == "workout").count();
            let sleep_minutes: i64 = current
                .iter()
                .filter(|(_, k, _, _)| k == "sleep")
                .filter_map(|(_, _, _, v)| v["duration_minutes"].as_i64())
                .sum();
            let sleep_count = current.iter().filter(|(_, k, _, _)| k == "sleep").count();
            let meal_count = current.iter().filter(|(_, k, _, _)| k == "meal").count();
            let weight_grams = current
                .iter()
                .filter(|(_, k, _, _)| k == "weight")
                .max_by(|a, b| (a.3["created_at"].as_str(), &a.0).cmp(&(b.3["created_at"].as_str(), &b.0)))
                .and_then(|(_, _, _, v)| v["weight_grams"].as_i64());
            let medications_scheduled = records.iter().filter(|(_, k, _, _)| k == "medication_schedule").count();
            let schedule_ids: BTreeSet<&str> = records
                .iter()
                .filter(|(_, k, _, _)| k == "medication_schedule")
                .map(|(id, _, _, _)| id.as_str())
                .collect();
            let medications_taken = current
                .iter()
                .filter(|(_, k, _, v)| {
                    k == "medication_taken" && v["schedule_id"].as_str().is_some_and(|id| schedule_ids.contains(id))
                })
                .filter_map(|(_, _, _, v)| v["schedule_id"].as_str())
                .collect::<BTreeSet<_>>()
                .len();
            let ids = records
                .iter()
                .filter(|(_, kind, d, _)| d == &day || kind == "medication_schedule")
                .map(|(id, _, _, _)| id.clone())
                .collect();
            Ok((
                json!([{"date":day,"workout_minutes":workout_minutes,"workout_count":workout_count,"sleep_minutes":sleep_minutes,"sleep_count":sleep_count,"meal_count":meal_count,
                "weight_grams":weight_grams,"medications_scheduled":medications_scheduled,"medications_taken":medications_taken}]),
                ids,
            ))
        }
        _ => Err(DomainError::validation("name", "unknown health query")),
    }
}

pub fn digest_rows(conn: &Connection) -> DomainResult<Vec<(String, String)>> {
    let mut stmt = conn.prepare("SELECT id,data_json FROM health_records ORDER BY id")?;
    let rows = stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<Result<_, _>>()?;
    Ok(rows)
}

pub fn export(conn: &Connection, format: &str) -> DomainResult<Vec<u8>> {
    if format != "json" {
        return Err(DomainError::validation("format", "Health supports JSON export only"));
    }
    let records: Vec<Value> =
        digest_rows(conn)?.into_iter().map(|(_, v)| serde_json::from_str(&v)).collect::<Result<_, _>>()?;
    Ok(serde_json::to_vec_pretty(&json!({"format":"reva-health-v1","records":records}))?)
}
