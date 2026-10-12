//! `DomainHandle`: the object hosts hold. All methods are synchronous and short; hosts must
//! call them off the UI thread (AR-DOM-015). Access to one domain file is serialized by a mutex.

use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard};

use rusqlite::TransactionBehavior;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::civil;
use crate::domains::finance::{self, commands, project, queries};
use crate::error::{DomainError, DomainResult};
use crate::events::{self, Event, EventCtx, InsertOutcome};
use crate::export;
use crate::import::{self, json_format};
use crate::key::KeyProvider;
use crate::store::Store;

#[derive(Debug, Clone, uniffi::Record)]
pub struct CommitResult {
    pub event_id: String,
    pub aggregate_id: String,
    pub version: i64,
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct QueryResult {
    pub rows_json: String,
    pub source_ids: Vec<String>,
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct RejectedRow {
    pub row: u64,
    pub reason: String,
    pub raw: String,
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct ImportReport {
    pub accepted: u64,
    pub duplicates: u64,
    pub rejected: Vec<RejectedRow>,
    /// Every row with its status, as a JSON array.
    pub rows_json: String,
    pub dry_run: bool,
    pub batch_id: String,
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct EventBatch {
    /// JSON array of events (contracts/domain-event.schema.json).
    pub events_json: String,
    /// Pass to `ack` once the transport has delivered the batch.
    pub cursor: i64,
    pub count: u64,
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct ConflictInfo {
    pub aggregate_type: String,
    pub aggregate_id: String,
    pub field: String,
    pub local_value: String,
    pub remote_value: String,
    pub local_event_id: String,
    pub remote_event_id: String,
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct ApplyReport {
    pub applied: u64,
    pub duplicates: u64,
    pub conflicts: Vec<ConflictInfo>,
}

struct Inner {
    store: Store,
}

#[derive(uniffi::Object)]
pub struct DomainHandle {
    domain: String,
    inner: Mutex<Inner>,
}

/// Open (or create, on a fresh install) the encrypted file for `domain`.
#[uniffi::export]
pub fn open_domain(
    domain: String,
    key_provider: Arc<dyn KeyProvider>,
    data_dir: String,
) -> Result<Arc<DomainHandle>, DomainError> {
    let migrations = match domain.as_str() {
        finance::DOMAIN => finance::migrations(),
        other => {
            return Err(DomainError::validation("domain", format!("domain {other:?} is not available in this build")));
        }
    };
    let store = Store::open(&domain, Path::new(&data_dir), key_provider.as_ref(), &migrations)?;
    Ok(Arc::new(DomainHandle { domain, inner: Mutex::new(Inner { store }) }))
}

/// The kernel version string, for diagnostics.
#[uniffi::export]
pub fn kernel_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

impl DomainHandle {
    fn lock(&self) -> MutexGuard<'_, Inner> {
        // A poisoned lock means a panic mid-transaction; the transaction was rolled back
        // on drop, so continuing is safe.
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub(crate) fn with_conn<T>(&self, f: impl FnOnce(&rusqlite::Connection) -> DomainResult<T>) -> DomainResult<T> {
        let guard = self.lock();
        f(&guard.store.conn)
    }

    pub(crate) fn domain_name(&self) -> &str {
        &self.domain
    }
}

#[uniffi::export]
impl DomainHandle {
    pub fn domain(&self) -> String {
        self.domain.clone()
    }

    pub fn device_id(&self) -> String {
        self.lock().store.device_id.clone()
    }

    pub fn schema_version(&self) -> Result<i64, DomainError> {
        self.lock().store.schema_version()
    }

    /// Names of every command this domain accepts (the registry the absence tests inspect).
    pub fn command_names(&self) -> Vec<String> {
        commands::COMMANDS.iter().map(|s| s.to_string()).collect()
    }

    pub fn command(&self, kind: String, payload_json: String) -> Result<CommitResult, DomainError> {
        let payload: Value = serde_json::from_str(&payload_json)
            .map_err(|e| DomainError::validation("payload", format!("not valid JSON: {e}")))?;
        let mut guard = self.lock();
        let store = &mut guard.store;
        let (device_id, tag_key) = (store.device_id.clone(), store.tag_key().to_vec());
        let ctx = EventCtx { domain: &self.domain, device_id: &device_id, tag_key: &tag_key };
        let tx = store.conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let drafts = commands::handle(&tx, &kind, &payload)?;
        let mut primary: Option<Event> = None;
        for draft in drafts {
            let event = events::append_local(&tx, &ctx, draft)?;
            project::apply(&tx, &event)?;
            if primary.is_none() {
                primary = Some(event);
            }
        }
        tx.commit()?;
        let event = primary.ok_or_else(|| DomainError::internal("command produced no event"))?;
        Ok(CommitResult { event_id: event.event_id, aggregate_id: event.aggregate_id, version: event.version })
    }

    pub fn query(&self, name: String, params_json: String) -> Result<QueryResult, DomainError> {
        let params: Value = if params_json.trim().is_empty() {
            json!({})
        } else {
            serde_json::from_str(&params_json)
                .map_err(|e| DomainError::validation("params", format!("not valid JSON: {e}")))?
        };
        let guard = self.lock();
        let out = queries::run(&guard.store.conn, &name, &params)?;
        Ok(QueryResult { rows_json: serde_json::to_string(&out.rows)?, source_ids: out.source_ids })
    }

    pub fn export(&self, format: String) -> Result<Vec<u8>, DomainError> {
        let guard = self.lock();
        export::export(&guard.store.conn, &format)
    }

    /// Import `data`. `options_json` is `{"account_id": "...", "dry_run": false, "mapping": {...}}`.
    /// A dry run runs the same code in a transaction that is rolled back.
    pub fn import_data(
        &self,
        format: String,
        data: Vec<u8>,
        options_json: String,
    ) -> Result<ImportReport, DomainError> {
        let options = import::parse_options(&options_json)?;
        let mut guard = self.lock();
        let store = &mut guard.store;
        let (device_id, tag_key) = (store.device_id.clone(), store.tag_key().to_vec());
        let ctx = EventCtx { domain: &self.domain, device_id: &device_id, tag_key: &tag_key };
        let tx = store.conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = civil::now_iso();
        let report = match format.as_str() {
            "json" => json_format::run(&tx, &ctx, &data, &options, &now)?,
            _ => import::run_statement(&tx, &ctx, &format, &data, &options, &now)?,
        };
        if options.dry_run {
            tx.rollback()?;
        } else {
            tx.commit()?;
        }
        Ok(ImportReport {
            accepted: report.accepted,
            duplicates: report.duplicates,
            rejected: report
                .rejected
                .iter()
                .map(|r| RejectedRow { row: r.row, reason: r.reason.clone().unwrap_or_default(), raw: r.raw.clone() })
                .collect(),
            rows_json: import::rows_json(&report.rows),
            dry_run: report.dry_run,
            batch_id: report.batch_id,
        })
    }

    pub fn pending_events(&self, limit: u32) -> Result<EventBatch, DomainError> {
        let guard = self.lock();
        let (events, cursor) = events::pending(&guard.store.conn, limit.clamp(1, 5000))?;
        Ok(EventBatch { count: events.len() as u64, events_json: serde_json::to_string(&events)?, cursor })
    }

    pub fn ack(&self, cursor: i64) -> Result<(), DomainError> {
        let guard = self.lock();
        events::ack(&guard.store.conn, cursor)?;
        Ok(())
    }

    /// Apply events from another device. Duplicates are no-ops; concurrent edits that
    /// disagree on an amount are recorded as conflicts and returned (AR-DOM-008).
    pub fn apply_events(&self, batch: EventBatch) -> Result<ApplyReport, DomainError> {
        let mut incoming: Vec<Event> = serde_json::from_str(&batch.events_json)
            .map_err(|e| DomainError::validation("events_json", e.to_string()))?;
        for event in &incoming {
            events::validate_remote(event, &self.domain)?;
        }
        incoming.sort_by(|a, b| (a.lamport, &a.origin_device_id).cmp(&(b.lamport, &b.origin_device_id)));

        let mut guard = self.lock();
        let tx = guard.store.conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut report = ApplyReport { applied: 0, duplicates: 0, conflicts: Vec::new() };
        for event in &incoming {
            match events::insert_remote(&tx, event)? {
                InsertOutcome::Duplicate => report.duplicates += 1,
                InsertOutcome::Inserted => {
                    report.applied += 1;
                    detect_conflicts(&tx, event, &mut report.conflicts)?;
                    if events::is_aggregate_head(&tx, event)? {
                        project::apply(&tx, event)?;
                    }
                }
            }
        }
        tx.commit()?;
        Ok(report)
    }

    pub fn backup(&self) -> Result<String, DomainError> {
        let guard = self.lock();
        Ok(guard.store.backup_now()?.to_string_lossy().to_string())
    }

    /// Drop every projection and rebuild it from the event log. Returns events replayed.
    pub fn rebuild_projections(&self) -> Result<u64, DomainError> {
        let mut guard = self.lock();
        let tx = guard.store.conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let n = project::rebuild(&tx)?;
        tx.commit()?;
        Ok(n)
    }

    /// SHA-256 over every projection row in a canonical order. Equal digests mean equal state.
    pub fn projection_digest(&self) -> Result<String, DomainError> {
        let guard = self.lock();
        let mut hasher = Sha256::new();
        for table in finance::schema::TABLES {
            let rows = finance::schema::select(&guard.store.conn, table.aggregate_type, "ORDER BY id", vec![])?;
            hasher.update(table.name.as_bytes());
            for row in rows {
                hasher.update(events::canonical(&Value::Object(row)).as_bytes());
            }
        }
        let aliases: Vec<(String, String)> = {
            let mut stmt = guard
                .store
                .conn
                .prepare("SELECT category_id, alias FROM category_aliases ORDER BY category_id, alias")?;
            let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
            rows.collect::<Result<_, _>>()?
        };
        for (c, a) in aliases {
            hasher.update(format!("{c}={a};").as_bytes());
        }
        Ok(hex::encode(hasher.finalize()))
    }

    pub fn event_count(&self) -> Result<i64, DomainError> {
        let guard = self.lock();
        events::count(&guard.store.conn)
    }

    pub fn integrity_check(&self) -> Result<String, DomainError> {
        let guard = self.lock();
        Ok(guard.store.conn.query_row("PRAGMA integrity_check", [], |r| r.get::<_, String>(0))?)
    }
}

/// Amount fields where two devices editing the same version concurrently must be shown to the user.
const CONFLICT_FIELDS: &[(&str, &str)] = &[
    ("transaction", "amount_minor"),
    ("bill", "amount_minor"),
    ("budget", "amount_minor"),
    ("account", "opening_balance_minor"),
];

fn detect_conflicts(conn: &rusqlite::Connection, event: &Event, out: &mut Vec<ConflictInfo>) -> DomainResult<()> {
    let Some((_, field)) = CONFLICT_FIELDS.iter().find(|(t, _)| *t == event.aggregate_type) else {
        return Ok(());
    };
    if event.tombstone {
        return Ok(());
    }
    let mut stmt = conn.prepare(
        "SELECT event_id FROM events
          WHERE aggregate_type = ?1 AND aggregate_id = ?2 AND version = ?3
            AND event_id != ?4 AND origin_device_id != ?5 AND tombstone = 0",
    )?;
    let others: Vec<String> = stmt
        .query_map(
            rusqlite::params![
                event.aggregate_type,
                event.aggregate_id,
                event.version,
                event.event_id,
                event.origin_device_id
            ],
            |r| r.get(0),
        )?
        .collect::<Result<_, _>>()?;
    for other_id in others {
        let Some(other) = events::get(conn, &other_id)? else { continue };
        let (mine, theirs) = (event.payload.get(*field), other.payload.get(*field));
        if mine.is_some() && theirs.is_some() && mine != theirs {
            let info = ConflictInfo {
                aggregate_type: event.aggregate_type.clone(),
                aggregate_id: event.aggregate_id.clone(),
                field: (*field).to_string(),
                local_value: theirs.map(|v| v.to_string()).unwrap_or_default(),
                remote_value: mine.map(|v| v.to_string()).unwrap_or_default(),
                local_event_id: other.event_id.clone(),
                remote_event_id: event.event_id.clone(),
            };
            conn.execute(
                "INSERT INTO conflicts (aggregate_type, aggregate_id, field, local_event_id, remote_event_id,
                                        local_value, remote_value, detected_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                rusqlite::params![
                    info.aggregate_type,
                    info.aggregate_id,
                    info.field,
                    info.local_event_id,
                    info.remote_event_id,
                    info.local_value,
                    info.remote_value,
                    civil::now_iso()
                ],
            )?;
            out.push(info);
        }
    }
    Ok(())
}
