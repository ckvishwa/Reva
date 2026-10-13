//! Finance projection tables and the generic load/upsert helpers over them.
//!
//! Projections hold the *current state* of each aggregate (the payload of its newest
//! event). They are derived data: `rebuild` drops and recreates them from the log.

use rusqlite::types::{Value as SqlValue, ValueRef};
use rusqlite::{params_from_iter, Connection, OptionalExtension};
use serde_json::{Map, Value};

use crate::error::DomainResult;
use crate::store::Migration;

pub const MIGRATION_V2: Migration = Migration {
    version: 2,
    name: "finance_projections",
    sql: r#"
CREATE TABLE accounts (
  id                    TEXT PRIMARY KEY,
  name                  TEXT NOT NULL,
  kind                  TEXT NOT NULL,
  currency              TEXT NOT NULL,
  opening_balance_minor INTEGER NOT NULL,
  archived              INTEGER NOT NULL,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL,
  version               INTEGER NOT NULL
);
CREATE TABLE categories (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  kind       TEXT NOT NULL,
  parent_id  TEXT,
  aliases    TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version    INTEGER NOT NULL
);
CREATE TABLE category_aliases (
  category_id TEXT NOT NULL,
  alias       TEXT NOT NULL
);
CREATE INDEX category_aliases_alias ON category_aliases (alias);
CREATE TABLE transactions (
  id              TEXT PRIMARY KEY,
  account_id      TEXT NOT NULL,
  date            TEXT NOT NULL,
  amount_minor    INTEGER NOT NULL,
  currency        TEXT NOT NULL,
  description     TEXT NOT NULL,
  merchant        TEXT,
  category_id     TEXT,
  notes           TEXT,
  import_batch_id TEXT,
  fingerprint     TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  version         INTEGER NOT NULL
);
CREATE INDEX transactions_date ON transactions (date);
CREATE INDEX transactions_account_date ON transactions (account_id, date);
CREATE INDEX transactions_category_date ON transactions (category_id, date);
CREATE INDEX transactions_fingerprint ON transactions (fingerprint);
CREATE TABLE budgets (
  id           TEXT PRIMARY KEY,
  category_id  TEXT NOT NULL,
  period       TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency     TEXT NOT NULL,
  start_month  TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  version      INTEGER NOT NULL
);
CREATE TABLE bills (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  kind           TEXT NOT NULL,
  amount_minor   INTEGER NOT NULL,
  currency       TEXT NOT NULL,
  recurrence     TEXT NOT NULL,
  due_date       TEXT NOT NULL,
  anchor_day     INTEGER NOT NULL,
  account_id     TEXT,
  category_id    TEXT,
  notes          TEXT,
  last_paid_date TEXT,
  active         INTEGER NOT NULL,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  version        INTEGER NOT NULL
);
CREATE INDEX bills_due ON bills (due_date);
CREATE TABLE networth_snapshots (
  id          TEXT PRIMARY KEY,
  as_of       TEXT NOT NULL,
  by_currency TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  version     INTEGER NOT NULL
);
"#,
};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Col {
    Text,
    Int,
    Bool,
    Json,
}

pub struct Table {
    pub aggregate_type: &'static str,
    pub name: &'static str,
    pub columns: &'static [(&'static str, Col)],
}

pub const TABLES: &[Table] = &[
    Table {
        aggregate_type: "account",
        name: "accounts",
        columns: &[
            ("id", Col::Text),
            ("name", Col::Text),
            ("kind", Col::Text),
            ("currency", Col::Text),
            ("opening_balance_minor", Col::Int),
            ("archived", Col::Bool),
            ("created_at", Col::Text),
            ("updated_at", Col::Text),
            ("version", Col::Int),
        ],
    },
    Table {
        aggregate_type: "category",
        name: "categories",
        columns: &[
            ("id", Col::Text),
            ("name", Col::Text),
            ("kind", Col::Text),
            ("parent_id", Col::Text),
            ("aliases", Col::Json),
            ("created_at", Col::Text),
            ("updated_at", Col::Text),
            ("version", Col::Int),
        ],
    },
    Table {
        aggregate_type: "transaction",
        name: "transactions",
        columns: &[
            ("id", Col::Text),
            ("account_id", Col::Text),
            ("date", Col::Text),
            ("amount_minor", Col::Int),
            ("currency", Col::Text),
            ("description", Col::Text),
            ("merchant", Col::Text),
            ("category_id", Col::Text),
            ("notes", Col::Text),
            ("import_batch_id", Col::Text),
            ("fingerprint", Col::Text),
            ("created_at", Col::Text),
            ("updated_at", Col::Text),
            ("version", Col::Int),
        ],
    },
    Table {
        aggregate_type: "budget",
        name: "budgets",
        columns: &[
            ("id", Col::Text),
            ("category_id", Col::Text),
            ("period", Col::Text),
            ("amount_minor", Col::Int),
            ("currency", Col::Text),
            ("start_month", Col::Text),
            ("created_at", Col::Text),
            ("updated_at", Col::Text),
            ("version", Col::Int),
        ],
    },
    Table {
        aggregate_type: "bill",
        name: "bills",
        columns: &[
            ("id", Col::Text),
            ("name", Col::Text),
            ("kind", Col::Text),
            ("amount_minor", Col::Int),
            ("currency", Col::Text),
            ("recurrence", Col::Text),
            ("due_date", Col::Text),
            ("anchor_day", Col::Int),
            ("account_id", Col::Text),
            ("category_id", Col::Text),
            ("notes", Col::Text),
            ("last_paid_date", Col::Text),
            ("active", Col::Bool),
            ("created_at", Col::Text),
            ("updated_at", Col::Text),
            ("version", Col::Int),
        ],
    },
    Table {
        aggregate_type: "networth_snapshot",
        name: "networth_snapshots",
        columns: &[
            ("id", Col::Text),
            ("as_of", Col::Text),
            ("by_currency", Col::Json),
            ("created_at", Col::Text),
            ("updated_at", Col::Text),
            ("version", Col::Int),
        ],
    },
];

pub fn table_for(aggregate_type: &str) -> Option<&'static Table> {
    TABLES.iter().find(|t| t.aggregate_type == aggregate_type)
}

fn to_sql(value: Option<&Value>, col: Col) -> SqlValue {
    match (value, col) {
        (None, _) | (Some(Value::Null), _) => SqlValue::Null,
        (Some(Value::Bool(b)), _) => SqlValue::Integer(i64::from(*b)),
        (Some(Value::Number(n)), _) => match n.as_i64() {
            Some(i) => SqlValue::Integer(i),
            None => SqlValue::Real(n.as_f64().unwrap_or(0.0)),
        },
        (Some(Value::String(s)), _) => SqlValue::Text(s.clone()),
        (Some(other), _) => SqlValue::Text(crate::events::canonical(other)),
    }
}

/// Insert or replace the row for `aggregate_type` from a full-state payload.
pub fn upsert(conn: &Connection, aggregate_type: &str, state: &Map<String, Value>) -> DomainResult<()> {
    let Some(table) = table_for(aggregate_type) else {
        return Ok(());
    };
    let names: Vec<&str> = table.columns.iter().map(|(n, _)| *n).collect();
    let placeholders: Vec<String> = (1..=names.len()).map(|i| format!("?{i}")).collect();
    let sql =
        format!("INSERT OR REPLACE INTO {} ({}) VALUES ({})", table.name, names.join(", "), placeholders.join(", "));
    let values: Vec<SqlValue> = table.columns.iter().map(|(n, c)| to_sql(state.get(*n), *c)).collect();
    conn.execute(&sql, params_from_iter(values))?;
    Ok(())
}

pub fn delete(conn: &Connection, aggregate_type: &str, id: &str) -> DomainResult<()> {
    if let Some(table) = table_for(aggregate_type) {
        conn.execute(&format!("DELETE FROM {} WHERE id = ?1", table.name), [id])?;
    }
    Ok(())
}

fn row_to_map(table: &Table, row: &rusqlite::Row<'_>) -> rusqlite::Result<Map<String, Value>> {
    let mut map = Map::new();
    for (index, (name, col)) in table.columns.iter().enumerate() {
        let value = match row.get_ref(index)? {
            ValueRef::Null => Value::Null,
            ValueRef::Integer(i) => match col {
                Col::Bool => Value::Bool(i != 0),
                _ => Value::from(i),
            },
            ValueRef::Real(f) => Value::from(f),
            ValueRef::Text(t) => {
                let text = String::from_utf8_lossy(t).to_string();
                if *col == Col::Json {
                    serde_json::from_str(&text).unwrap_or(Value::Null)
                } else {
                    Value::String(text)
                }
            }
            ValueRef::Blob(_) => Value::Null,
        };
        map.insert((*name).to_string(), value);
    }
    Ok(map)
}

pub fn load(conn: &Connection, aggregate_type: &str, id: &str) -> DomainResult<Option<Map<String, Value>>> {
    let Some(table) = table_for(aggregate_type) else {
        return Ok(None);
    };
    let names: Vec<&str> = table.columns.iter().map(|(n, _)| *n).collect();
    let sql = format!("SELECT {} FROM {} WHERE id = ?1", names.join(", "), table.name);
    Ok(conn.query_row(&sql, [id], |r| row_to_map(table, r)).optional()?)
}

/// Run a SELECT over the columns of `aggregate_type`'s table and return rows as JSON objects.
/// `tail` is appended after `FROM <table>` (WHERE / ORDER BY / LIMIT).
pub fn select(
    conn: &Connection,
    aggregate_type: &str,
    tail: &str,
    params: Vec<SqlValue>,
) -> DomainResult<Vec<Map<String, Value>>> {
    let Some(table) = table_for(aggregate_type) else {
        return Ok(Vec::new());
    };
    let names: Vec<&str> = table.columns.iter().map(|(n, _)| *n).collect();
    let sql = format!("SELECT {} FROM {} {}", names.join(", "), table.name, tail);
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map(params_from_iter(params), |r| row_to_map(table, r))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row?);
    }
    Ok(out)
}

pub fn clear_projections(conn: &Connection) -> DomainResult<()> {
    for table in TABLES {
        conn.execute(&format!("DELETE FROM {}", table.name), [])?;
    }
    conn.execute("DELETE FROM category_aliases", [])?;
    Ok(())
}
