//! Event envelope (contracts/domain-event.schema.json), log, outbox, tombstones, Lamport clock.
//!
//! Every domain write is an event appended to the log and the outbox in the same
//! transaction as the projection update (ADR-029). Payloads carry the full resulting
//! state of the aggregate, so replaying the log in `(lamport, origin_device_id, seq)`
//! order rebuilds exactly the live projections.

use hmac::{Hmac, Mac};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::Sha256;

use crate::civil;
use crate::error::{DomainError, DomainResult};

pub const EVENT_SCHEMA: &str = "1.0";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Event {
    pub event_schema: String,
    pub event_id: String,
    pub domain: String,
    pub aggregate_type: String,
    pub aggregate_id: String,
    pub version: i64,
    pub origin_device_id: String,
    pub lamport: i64,
    pub kind: String,
    pub created_at: String,
    pub tombstone: bool,
    pub payload: Value,
    pub signature: String,
}

/// What a command decides to write; the store fills in the envelope.
#[derive(Debug, Clone)]
pub struct EventDraft {
    pub aggregate_type: String,
    pub aggregate_id: String,
    pub kind: String,
    pub tombstone: bool,
    pub payload: Value,
}

pub struct EventCtx<'a> {
    pub domain: &'a str,
    pub device_id: &'a str,
    pub tag_key: &'a [u8],
}

#[derive(Debug, PartialEq, Eq)]
pub enum InsertOutcome {
    Inserted,
    Duplicate,
}

/// Deterministic JSON with sorted object keys, independent of serde_json feature flags.
pub fn canonical(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .into_iter()
                .map(|k| format!("{}:{}", serde_json::to_string(k).unwrap_or_default(), canonical(&map[k])))
                .collect();
            format!("{{{}}}", parts.join(","))
        }
        Value::Array(items) => format!("[{}]", items.iter().map(canonical).collect::<Vec<_>>().join(",")),
        other => other.to_string(),
    }
}

/// Integrity tag over the canonical event bytes, keyed by a key derived from the local
/// domain key. It proves the event was not altered on this device. It is NOT yet a
/// public-key signature: cross-device verification arrives with device pairing (S13).
pub fn sign(tag_key: &[u8], event: &Event) -> String {
    let mut body = serde_json::to_value(event).unwrap_or(Value::Null);
    if let Value::Object(map) = &mut body {
        map.remove("signature");
    }
    let mut mac = Hmac::<Sha256>::new_from_slice(tag_key).expect("HMAC accepts any key length");
    mac.update(canonical(&body).as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

pub fn next_lamport(conn: &Connection) -> DomainResult<i64> {
    let current = crate::store::meta_get(conn, "lamport")?.and_then(|v| v.parse::<i64>().ok()).unwrap_or(0);
    let next = current + 1;
    crate::store::meta_set(conn, "lamport", &next.to_string())?;
    Ok(next)
}

/// Lamport rule on receive: local clock becomes max(local, remote).
pub fn observe_lamport(conn: &Connection, remote: i64) -> DomainResult<()> {
    let current = crate::store::meta_get(conn, "lamport")?.and_then(|v| v.parse::<i64>().ok()).unwrap_or(0);
    if remote > current {
        crate::store::meta_set(conn, "lamport", &remote.to_string())?;
    }
    Ok(())
}

pub fn aggregate_version(conn: &Connection, aggregate_type: &str, aggregate_id: &str) -> DomainResult<i64> {
    Ok(conn.query_row(
        "SELECT COALESCE(MAX(version), 0) FROM events WHERE aggregate_type = ?1 AND aggregate_id = ?2",
        params![aggregate_type, aggregate_id],
        |r| r.get(0),
    )?)
}

/// Append a local event to the log and the outbox.
pub fn append_local(conn: &Connection, ctx: &EventCtx, draft: EventDraft) -> DomainResult<Event> {
    let version = aggregate_version(conn, &draft.aggregate_type, &draft.aggregate_id)? + 1;
    let lamport = next_lamport(conn)?;
    let mut event = Event {
        event_schema: EVENT_SCHEMA.to_string(),
        event_id: uuid::Uuid::new_v4().to_string(),
        domain: ctx.domain.to_string(),
        aggregate_type: draft.aggregate_type,
        aggregate_id: draft.aggregate_id,
        version,
        origin_device_id: ctx.device_id.to_string(),
        lamport,
        kind: draft.kind,
        created_at: civil::now_iso(),
        tombstone: draft.tombstone,
        payload: draft.payload,
        signature: String::new(),
    };
    event.signature = sign(ctx.tag_key, &event);
    insert_row(conn, &event, true)?;
    conn.execute("INSERT INTO outbox (event_id) VALUES (?1)", [&event.event_id])?;
    if event.tombstone {
        record_tombstone(conn, &event)?;
    }
    Ok(event)
}

fn insert_row(conn: &Connection, e: &Event, local: bool) -> DomainResult<()> {
    conn.execute(
        "INSERT INTO events (event_id, domain, aggregate_type, aggregate_id, version, origin_device_id,
                             lamport, kind, created_at, tombstone, payload, signature, local)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13)",
        params![
            e.event_id,
            e.domain,
            e.aggregate_type,
            e.aggregate_id,
            e.version,
            e.origin_device_id,
            e.lamport,
            e.kind,
            e.created_at,
            e.tombstone,
            serde_json::to_string(&e.payload)?,
            e.signature,
            local
        ],
    )?;
    Ok(())
}

fn record_tombstone(conn: &Connection, e: &Event) -> DomainResult<()> {
    conn.execute(
        "INSERT OR REPLACE INTO tombstones (aggregate_type, aggregate_id, event_id, deleted_at) VALUES (?1, ?2, ?3, ?4)",
        params![e.aggregate_type, e.aggregate_id, e.event_id, e.created_at],
    )?;
    Ok(())
}

pub fn is_tombstoned(conn: &Connection, aggregate_type: &str, aggregate_id: &str) -> DomainResult<bool> {
    let found: Option<i64> = conn
        .query_row(
            "SELECT 1 FROM tombstones WHERE aggregate_type = ?1 AND aggregate_id = ?2",
            params![aggregate_type, aggregate_id],
            |r| r.get(0),
        )
        .optional()?;
    Ok(found.is_some())
}

/// Shape checks for events from another device (AR-DATA: reject, never guess).
pub fn validate_remote(event: &Event, expected_domain: &str) -> DomainResult<()> {
    let bad = |field: &str, reason: &str| Err(DomainError::validation(field, reason));
    if event.event_schema != EVENT_SCHEMA {
        return bad("event_schema", "unsupported event schema");
    }
    if event.domain != expected_domain {
        return bad("domain", "event belongs to another domain");
    }
    if !(8..=64).contains(&event.event_id.len()) {
        return bad("event_id", "must be 8-64 characters");
    }
    if !(8..=64).contains(&event.aggregate_id.len()) {
        return bad("aggregate_id", "must be 8-64 characters");
    }
    if !(8..=64).contains(&event.origin_device_id.len()) {
        return bad("origin_device_id", "must be 8-64 characters");
    }
    let t = &event.aggregate_type;
    if !(2..=40).contains(&t.len()) || !t.bytes().all(|b| b.is_ascii_lowercase() || b == b'_') {
        return bad("aggregate_type", "must match ^[a-z_]{2,40}$");
    }
    if event.version < 1 {
        return bad("version", "must be >= 1");
    }
    if event.lamport < 0 {
        return bad("lamport", "must be >= 0");
    }
    let Some((head, action)) = event.kind.rsplit_once('.') else {
        return bad("kind", "must look like aggregate.action");
    };
    if head.is_empty()
        || !head.bytes().all(|b| b.is_ascii_lowercase() || b == b'_')
        || !["created", "updated", "deleted", "imported"].contains(&action)
    {
        return bad("kind", "must match ^[a-z_]+\\.(created|updated|deleted|imported)$");
    }
    if event.tombstone != (action == "deleted") {
        return bad("tombstone", "must be true exactly for .deleted events");
    }
    if civil::Date::parse(event.created_at.get(0..10).unwrap_or("")).is_none() {
        return bad("created_at", "must be an RFC 3339 timestamp");
    }
    if !event.payload.is_object() {
        return bad("payload", "must be an object");
    }
    if event.signature.is_empty() {
        return bad("signature", "required");
    }
    Ok(())
}

pub fn insert_remote(conn: &Connection, event: &Event) -> DomainResult<InsertOutcome> {
    let exists: Option<i64> =
        conn.query_row("SELECT 1 FROM events WHERE event_id = ?1", [&event.event_id], |r| r.get(0)).optional()?;
    if exists.is_some() {
        return Ok(InsertOutcome::Duplicate);
    }
    observe_lamport(conn, event.lamport)?;
    insert_row(conn, event, false)?;
    if event.tombstone {
        record_tombstone(conn, event)?;
    }
    Ok(InsertOutcome::Inserted)
}

/// True if `event` is the newest event of its aggregate in `(lamport, device, seq)` order,
/// i.e. its payload is the aggregate's current state.
pub fn is_aggregate_head(conn: &Connection, event: &Event) -> DomainResult<bool> {
    let newer: Option<i64> = conn
        .query_row(
            "SELECT 1 FROM events
              WHERE aggregate_type = ?1 AND aggregate_id = ?2 AND event_id != ?3
                AND (lamport > ?4 OR (lamport = ?4 AND origin_device_id > ?5))
              LIMIT 1",
            params![event.aggregate_type, event.aggregate_id, event.event_id, event.lamport, event.origin_device_id],
            |r| r.get(0),
        )
        .optional()?;
    Ok(newer.is_none())
}

fn row_to_event(r: &rusqlite::Row<'_>) -> rusqlite::Result<(Event, i64)> {
    let payload: String = r.get(10)?;
    Ok((
        Event {
            event_schema: EVENT_SCHEMA.to_string(),
            event_id: r.get(1)?,
            domain: r.get(2)?,
            aggregate_type: r.get(3)?,
            aggregate_id: r.get(4)?,
            version: r.get(5)?,
            origin_device_id: r.get(6)?,
            lamport: r.get(7)?,
            kind: r.get(8)?,
            created_at: r.get(9)?,
            tombstone: r.get::<_, i64>(11)? != 0,
            payload: serde_json::from_str(&payload).unwrap_or(Value::Null),
            signature: r.get(12)?,
        },
        r.get(0)?,
    ))
}

const EVENT_COLUMNS: &str = "e.seq, e.event_id, e.domain, e.aggregate_type, e.aggregate_id, e.version,
     e.origin_device_id, e.lamport, e.kind, e.created_at, e.payload, e.tombstone, e.signature";

/// Events not yet acknowledged by the sync transport, oldest first, with the outbox cursor.
pub fn pending(conn: &Connection, limit: u32) -> DomainResult<(Vec<Event>, i64)> {
    let sql = format!(
        "SELECT o.seq, {EVENT_COLUMNS} FROM outbox o JOIN events e ON e.event_id = o.event_id
          ORDER BY o.seq LIMIT ?1"
    );
    let mut stmt = conn.prepare(&sql)?;
    let mut rows = stmt.query([limit])?;
    let mut events = Vec::new();
    let mut cursor = 0;
    while let Some(row) = rows.next()? {
        cursor = row.get::<_, i64>(0)?;
        let payload: String = row.get(11)?;
        events.push(Event {
            event_schema: EVENT_SCHEMA.to_string(),
            event_id: row.get(2)?,
            domain: row.get(3)?,
            aggregate_type: row.get(4)?,
            aggregate_id: row.get(5)?,
            version: row.get(6)?,
            origin_device_id: row.get(7)?,
            lamport: row.get(8)?,
            kind: row.get(9)?,
            created_at: row.get(10)?,
            tombstone: row.get::<_, i64>(12)? != 0,
            payload: serde_json::from_str(&payload).unwrap_or(Value::Null),
            signature: row.get(13)?,
        });
    }
    Ok((events, cursor))
}

pub fn ack(conn: &Connection, cursor: i64) -> DomainResult<u64> {
    Ok(conn.execute("DELETE FROM outbox WHERE seq <= ?1", [cursor])? as u64)
}

/// The whole log in replay order.
pub fn all_ordered(conn: &Connection) -> DomainResult<Vec<Event>> {
    let sql = format!("SELECT {EVENT_COLUMNS} FROM events e ORDER BY e.lamport, e.origin_device_id, e.seq");
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([], row_to_event)?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row?.0);
    }
    Ok(out)
}

pub fn count(conn: &Connection) -> DomainResult<i64> {
    Ok(conn.query_row("SELECT COUNT(*) FROM events", [], |r| r.get(0))?)
}

pub fn get(conn: &Connection, event_id: &str) -> DomainResult<Option<Event>> {
    let sql = format!("SELECT {EVENT_COLUMNS} FROM events e WHERE e.event_id = ?1");
    Ok(conn.query_row(&sql, [event_id], row_to_event).optional()?.map(|(e, _)| e))
}
