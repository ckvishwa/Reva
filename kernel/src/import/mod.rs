//! Import: CSV (configurable mapping), OFX and the Kernel's own JSON export.
//!
//! Every row ends up accepted, a duplicate, or rejected *with a reason*; nothing is dropped
//! silently (AR-DOM-012). A dry run executes exactly the same code inside a transaction
//! that is rolled back, so its report equals the real run's and nothing is committed.

pub mod csv_format;
pub mod json_format;
pub mod ofx;

use std::collections::{BTreeMap, BTreeSet};

use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::civil::Date;
use crate::domains::finance::{commands, project, queries};
use crate::error::{DomainError, DomainResult};
use crate::events::{self, EventCtx, EventDraft};

pub const MAX_FILE_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_ROWS: usize = 50_000;

#[derive(Debug, Clone)]
pub struct Candidate {
    pub row: u64,
    pub date: Date,
    pub amount_minor: i64,
    pub description: String,
    pub merchant: Option<String>,
    pub category: Option<String>,
    pub notes: Option<String>,
    pub fitid: Option<String>,
    pub raw: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RowResult {
    pub row: u64,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub date: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub amount_minor: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub record_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub warning: Option<String>,
    pub raw: String,
}

impl RowResult {
    pub fn rejected(row: u64, reason: String, raw: String) -> RowResult {
        RowResult {
            row,
            status: "rejected".to_string(),
            reason: Some(reason),
            date: None,
            amount_minor: None,
            description: None,
            record_id: None,
            warning: None,
            raw: raw.chars().take(300).collect(),
        }
    }
}

#[derive(Default)]
pub struct ParseOutcome {
    pub candidates: Vec<Candidate>,
    pub rejected: Vec<RowResult>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Options {
    pub account_id: Option<String>,
    #[serde(default)]
    pub dry_run: bool,
    #[serde(default)]
    pub mapping: Value,
}

#[derive(Debug, Clone)]
pub struct Report {
    pub accepted: u64,
    pub duplicates: u64,
    pub rejected: Vec<RowResult>,
    pub rows: Vec<RowResult>,
    pub dry_run: bool,
    pub batch_id: String,
}

fn norm(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

fn fingerprint(parts: &[&str]) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(part.as_bytes());
        hasher.update([0x1f]);
    }
    hex::encode(hasher.finalize())
}

/// Parse options JSON (`{account_id, dry_run, mapping}`).
pub fn parse_options(options_json: &str) -> DomainResult<Options> {
    if options_json.trim().is_empty() {
        return Ok(Options::default());
    }
    serde_json::from_str(options_json).map_err(|e| DomainError::validation("options", e.to_string()))
}

/// Run a CSV or OFX import on `conn`, which must be inside an open transaction.
pub fn run_statement(
    conn: &Connection,
    ctx: &EventCtx,
    format: &str,
    bytes: &[u8],
    options: &Options,
    now: &str,
) -> DomainResult<Report> {
    if bytes.len() > MAX_FILE_BYTES {
        return Err(DomainError::validation("file", "larger than 8 MB"));
    }
    let account_id = options
        .account_id
        .clone()
        .ok_or_else(|| DomainError::validation("options.account_id", "required for csv and ofx imports"))?;
    let account = crate::domains::finance::schema::load(conn, "account", &account_id)?
        .ok_or_else(|| DomainError::not_found(format!("account {account_id}")))?;
    let currency = account["currency"].as_str().unwrap_or("").to_string();

    let parsed = match format {
        "csv" => csv_format::parse(bytes, &options.mapping, &currency)?,
        "ofx" => ofx::parse(bytes, &currency)?,
        other => return Err(DomainError::validation("format", format!("unsupported import format {other:?}"))),
    };
    if parsed.candidates.len() + parsed.rejected.len() > MAX_ROWS {
        return Err(DomainError::validation("file", "more than 50,000 rows"));
    }

    let batch_id = uuid::Uuid::new_v4().to_string();
    let mut rows: Vec<RowResult> = parsed.rejected.clone();
    let mut accepted = 0_u64;
    let mut duplicates = 0_u64;
    let mut seen_in_file: BTreeMap<String, u32> = BTreeMap::new();
    let mut claimed_manual: BTreeSet<String> = BTreeSet::new();

    for c in parsed.candidates {
        let date = c.date.to_iso();
        let amount = c.amount_minor.to_string();
        let desc_norm = norm(&c.description);
        let fp = match &c.fitid {
            Some(fitid) => fingerprint(&["ofx", &account_id, fitid]),
            None => {
                let base = fingerprint(&["csv", &account_id, &date, &amount, &desc_norm]);
                let n = seen_in_file.entry(base.clone()).or_insert(0);
                *n += 1;
                fingerprint(&[&base, &n.to_string()])
            }
        };
        let summary =
            |status: &str, reason: Option<String>, record_id: Option<String>, warning: Option<String>| RowResult {
                row: c.row,
                status: status.to_string(),
                reason,
                date: Some(date.clone()),
                amount_minor: Some(c.amount_minor),
                description: Some(c.description.clone()),
                record_id,
                warning,
                raw: c.raw.chars().take(300).collect(),
            };

        let fp_hit: Option<String> =
            conn.query_row("SELECT id FROM transactions WHERE fingerprint = ?1 LIMIT 1", [&fp], |r| r.get(0)).ok();
        if let Some(existing) = fp_hit {
            duplicates += 1;
            rows.push(summary("duplicate", Some("already imported".to_string()), Some(existing), None));
            continue;
        }
        // A manually entered transaction (no fingerprint) with the same account, date, amount
        // and description counts as the same transaction, once per manual record.
        let manual: Option<String> = conn
            .query_row(
                "SELECT id FROM transactions
                  WHERE fingerprint IS NULL AND account_id = ?1 AND date = ?2 AND amount_minor = ?3
                    AND lower(trim(description)) = ?4 LIMIT 1",
                rusqlite::params![account_id, date, c.amount_minor, desc_norm],
                |r| r.get(0),
            )
            .ok();
        if let Some(existing) = manual {
            if claimed_manual.insert(existing.clone()) {
                duplicates += 1;
                rows.push(summary(
                    "duplicate",
                    Some("matches a manually entered transaction".to_string()),
                    Some(existing),
                    None,
                ));
                continue;
            }
        }

        let mut warning = None;
        let category_id = match &c.category {
            Some(text) => match queries::resolve_category(conn, text)? {
                Some(id) => Some(id),
                None => {
                    warning = Some(format!("category {text:?} not found; left uncategorized"));
                    None
                }
            },
            None => None,
        };
        let built = commands::build_transaction(
            conn,
            commands::NewTransaction {
                id: None,
                account_id: account_id.clone(),
                date: c.date,
                amount_minor: c.amount_minor,
                currency: None,
                description: c.description.clone(),
                merchant: c.merchant.clone(),
                category_id,
                notes: c.notes.clone(),
                import_batch_id: Some(batch_id.clone()),
                fingerprint: Some(fp),
                source: Some(format.to_string()),
            },
            now,
        );
        match built {
            Ok((id, state)) => {
                let draft = EventDraft {
                    aggregate_type: "transaction".to_string(),
                    aggregate_id: id.clone(),
                    kind: "transaction.imported".to_string(),
                    tombstone: false,
                    payload: Value::Object(state),
                };
                let event = events::append_local(conn, ctx, draft)?;
                project::apply(conn, &event)?;
                accepted += 1;
                rows.push(summary("accepted", None, Some(id), warning));
            }
            Err(DomainError::Validation { field, reason }) => {
                rows.push(RowResult::rejected(c.row, format!("{field}: {reason}"), c.raw.clone()));
            }
            Err(DomainError::Conflict { detail: message }) => {
                rows.push(RowResult::rejected(c.row, message, c.raw.clone()));
            }
            Err(other) => return Err(other),
        }
    }
    rows.sort_by_key(|r| r.row);
    let rejected = rows.iter().filter(|r| r.status == "rejected").cloned().collect();
    Ok(Report { accepted, duplicates, rejected, rows, dry_run: options.dry_run, batch_id })
}

pub fn rows_json(rows: &[RowResult]) -> String {
    serde_json::to_string(&json!(rows)).unwrap_or_else(|_| "[]".to_string())
}
