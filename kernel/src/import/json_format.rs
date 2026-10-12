//! Import of the Kernel's own JSON export (restore into a fresh install, or merge).
//! Rows go through the same validating commands as live writes and are recorded as
//! `*.imported` events; ids that already exist are reported as duplicates.

use rusqlite::Connection;
use serde_json::{json, Map, Value};

use super::{Options, Report, RowResult, MAX_FILE_BYTES, MAX_ROWS};
use crate::domains::finance::{commands, project, schema};
use crate::error::{DomainError, DomainResult};
use crate::events::{self, EventCtx, EventDraft};

pub const FORMAT_NAME: &str = "reva-finance-export";
pub const FORMAT_VERSION: i64 = 1;

/// (collection in the file, aggregate type, create command, fields passed to the command)
const SECTIONS: &[(&str, &str, &str, &[&str])] = &[
    ("accounts", "account", "account.create", &["id", "name", "kind", "currency", "opening_balance_minor"]),
    ("categories", "category", "category.create", &["id", "name", "kind", "parent_id", "aliases"]),
    ("budgets", "budget", "budget.set", &["id", "category_id", "amount_minor", "currency", "start_month"]),
    (
        "bills",
        "bill",
        "bill.create",
        &[
            "id",
            "name",
            "kind",
            "amount_minor",
            "currency",
            "recurrence",
            "due_date",
            "account_id",
            "category_id",
            "notes",
        ],
    ),
    (
        "transactions",
        "transaction",
        "transaction.create",
        &["id", "account_id", "date", "amount_minor", "currency", "description", "merchant", "category_id", "notes"],
    ),
    ("networth_snapshots", "networth_snapshot", "", &[]),
];

/// Fields copied verbatim onto the state after the command validated the rest.
const CARRY: &[(&str, &[&str])] = &[
    ("account", &["archived", "created_at", "updated_at"]),
    ("category", &["created_at", "updated_at"]),
    ("budget", &["created_at", "updated_at"]),
    ("bill", &["last_paid_date", "active", "anchor_day", "created_at", "updated_at"]),
    ("transaction", &["import_batch_id", "fingerprint", "created_at", "updated_at"]),
    ("networth_snapshot", &["created_at", "updated_at"]),
];

pub fn run(conn: &Connection, ctx: &EventCtx, bytes: &[u8], options: &Options, now: &str) -> DomainResult<Report> {
    if bytes.len() > MAX_FILE_BYTES {
        return Err(DomainError::validation("file", "larger than 8 MB"));
    }
    let doc: Value =
        serde_json::from_slice(bytes).map_err(|e| DomainError::validation("file", format!("not JSON: {e}")))?;
    if doc["format"] != json!(FORMAT_NAME) || doc["version"] != json!(FORMAT_VERSION) {
        return Err(DomainError::validation("file", format!("expected {FORMAT_NAME} version {FORMAT_VERSION}")));
    }
    let total: usize = SECTIONS.iter().map(|(k, ..)| doc[*k].as_array().map(Vec::len).unwrap_or(0)).sum();
    if total > MAX_ROWS {
        return Err(DomainError::validation("file", "more than 50,000 records"));
    }

    let batch_id = uuid::Uuid::new_v4().to_string();
    let mut rows = Vec::new();
    let (mut accepted, mut duplicates) = (0_u64, 0_u64);
    let mut counter = 0_u64;

    for (collection, aggregate_type, command, fields) in SECTIONS {
        let Some(items) = doc[*collection].as_array() else { continue };
        // Parents before children for categories.
        let mut ordered: Vec<&Value> = items.iter().collect();
        if *aggregate_type == "category" {
            ordered.sort_by_key(|v| v["parent_id"].as_str().is_some());
        }
        for item in ordered {
            counter += 1;
            let id = item["id"].as_str().unwrap_or("").to_string();
            let raw = format!("{aggregate_type} {id}");
            let row = |status: &str, reason: Option<String>| RowResult {
                row: counter,
                status: status.to_string(),
                reason,
                date: None,
                amount_minor: None,
                description: item["name"].as_str().or_else(|| item["description"].as_str()).map(str::to_string),
                record_id: Some(id.clone()),
                warning: None,
                raw: raw.clone(),
            };
            let Some(obj) = item.as_object() else {
                rows.push(RowResult::rejected(counter, "record is not an object".to_string(), raw));
                continue;
            };
            if events::is_tombstoned(conn, aggregate_type, &id)? {
                rows.push(row("rejected", Some("deleted on this device".to_string())));
                continue;
            }
            if schema::load(conn, aggregate_type, &id)?.is_some() {
                duplicates += 1;
                rows.push(row("duplicate", Some("already present".to_string())));
                continue;
            }

            let drafts = if command.is_empty() {
                // Net-worth snapshots are historical facts: restore them as recorded.
                let mut state = Map::new();
                for key in ["id", "as_of", "by_currency"] {
                    state.insert(key.to_string(), obj.get(key).cloned().unwrap_or(Value::Null));
                }
                if crate::civil::Date::parse(state["as_of"].as_str().unwrap_or("")).is_none()
                    || !state["by_currency"].is_object()
                {
                    rows.push(row("rejected", Some("as_of or by_currency is invalid".to_string())));
                    continue;
                }
                vec![EventDraft {
                    aggregate_type: "networth_snapshot".to_string(),
                    aggregate_id: id.clone(),
                    kind: "networth_snapshot.created".to_string(),
                    tombstone: false,
                    payload: Value::Object(state),
                }]
            } else {
                let mut payload = Map::new();
                for key in *fields {
                    if let Some(v) = obj.get(*key) {
                        if !v.is_null() {
                            payload.insert((*key).to_string(), v.clone());
                        }
                    }
                }
                match commands::handle(conn, command, &Value::Object(payload)) {
                    Ok(d) => d,
                    Err(DomainError::Validation { field, reason }) => {
                        rows.push(row("rejected", Some(format!("{field}: {reason}"))));
                        continue;
                    }
                    Err(DomainError::Conflict { detail: message })
                    | Err(DomainError::NotFound { detail: message })
                    | Err(DomainError::Deleted { detail: message }) => {
                        rows.push(row("rejected", Some(message)));
                        continue;
                    }
                    Err(other) => return Err(other),
                }
            };

            for mut d in drafts {
                if let (Some(state), Some((_, carry))) =
                    (d.payload.as_object_mut(), CARRY.iter().find(|(t, _)| *t == d.aggregate_type))
                {
                    for key in *carry {
                        if let Some(v) = obj.get(*key) {
                            state.insert((*key).to_string(), v.clone());
                        }
                    }
                    if d.aggregate_type == "budget" {
                        // `budget.set` may have re-used the id of an existing budget for this category.
                        state.insert("id".to_string(), Value::String(d.aggregate_id.clone()));
                    }
                }
                d.kind = d.kind.replace(".created", ".imported").replace(".updated", ".imported");
                let event = events::append_local(conn, ctx, d)?;
                project::apply(conn, &event)?;
            }
            accepted += 1;
            rows.push(row("accepted", None));
        }
    }
    let rejected = rows.iter().filter(|r| r.status == "rejected").cloned().collect();
    let _ = now;
    Ok(Report { accepted, duplicates, rejected, rows, dry_run: options.dry_run, batch_id })
}
