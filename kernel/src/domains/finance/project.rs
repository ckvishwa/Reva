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
    let mut state: Map<String, Value> = event.payload.as_object().cloned().unwrap_or_default();
    state.insert("id".to_string(), Value::String(event.aggregate_id.clone()));
    state.insert("version".to_string(), Value::from(event.version));
    state.entry("created_at".to_string()).or_insert_with(|| Value::String(event.created_at.clone()));
    state.entry("updated_at".to_string()).or_insert_with(|| Value::String(event.created_at.clone()));
    schema::upsert(conn, &event.aggregate_type, &state)?;
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
