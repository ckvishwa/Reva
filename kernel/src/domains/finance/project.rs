//! Apply events to the Finance projection tables, and rebuild them from the log.

use rusqlite::Connection;
use serde_json::{Map, Value};

use super::schema;
use crate::error::DomainResult;
use crate::events::{self, Event};

pub fn apply(conn: &Connection, event: &Event) -> DomainResult<()> {
    if event.tombstone {
        schema::delete(conn, &event.aggregate_type, &event.aggregate_id)?;
        if event.aggregate_type == "category" {
            conn.execute("DELETE FROM category_aliases WHERE category_id = ?1", [&event.aggregate_id])?;
        }
        return Ok(());
    }
    // A deleted record stays deleted: a concurrent or late edit never brings it back (AR-DATA-011).
    if events::is_tombstoned(conn, &event.aggregate_type, &event.aggregate_id)? {
        return Ok(());
    }
    let mut state: Map<String, Value> = event.payload.as_object().cloned().unwrap_or_default();
    state.insert("id".to_string(), Value::String(event.aggregate_id.clone()));
    state.insert("version".to_string(), Value::from(event.version));
    state.entry("created_at".to_string()).or_insert_with(|| Value::String(event.created_at.clone()));
    state.entry("updated_at".to_string()).or_insert_with(|| Value::String(event.created_at.clone()));
    schema::upsert(conn, &event.aggregate_type, &state)?;
    if let Some(resolved) = state.get("resolves_conflict").and_then(Value::as_object) {
        // A conflict-resolution event: mark the matching conflict resolved on every device. Each
        // device records the pair from its own point of view (local/remote swapped), so match the
        // two event ids in either order.
        let local = resolved.get("local_event_id").and_then(Value::as_str).unwrap_or("");
        let remote = resolved.get("remote_event_id").and_then(Value::as_str).unwrap_or("");
        conn.execute(
            "UPDATE conflicts SET resolved = 1
              WHERE (local_event_id = ?1 AND remote_event_id = ?2) OR (local_event_id = ?2 AND remote_event_id = ?1)",
            [local, remote],
        )?;
    }
    if event.aggregate_type == "category" {
        refresh_aliases(conn, &event.aggregate_id, &state)?;
    }
    Ok(())
}

fn refresh_aliases(conn: &Connection, category_id: &str, state: &Map<String, Value>) -> DomainResult<()> {
    conn.execute("DELETE FROM category_aliases WHERE category_id = ?1", [category_id])?;
    if let Some(Value::Array(items)) = state.get("aliases") {
        for alias in items.iter().filter_map(Value::as_str) {
            conn.execute("INSERT INTO category_aliases (category_id, alias) VALUES (?1, ?2)", [category_id, alias])?;
        }
    }
    Ok(())
}

/// Drop every projection and replay the log in `(lamport, origin_device_id, seq)` order.
pub fn rebuild(conn: &Connection) -> DomainResult<u64> {
    schema::clear_projections(conn)?;
    let mut applied = 0;
    for event in events::all_ordered(conn)? {
        apply(conn, &event)?;
        applied += 1;
    }
    Ok(applied)
}
