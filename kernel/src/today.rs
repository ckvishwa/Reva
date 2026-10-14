//! Cross-domain "Today" summary, computed only from the domains the caller passes in
//! (AR-DOM-013). Read-only.

use std::sync::Arc;

use serde_json::{json, Map, Value};

use crate::civil;
use crate::domains::finance::{self, queries};
use crate::error::DomainError;
use crate::handle::DomainHandle;

fn finance_today(handle: &DomainHandle, as_of: civil::Date) -> Result<Value, DomainError> {
    handle.with_conn(|conn| {
        let params = json!({ "as_of": as_of.to_iso() });
        let budgets = queries::run(conn, "budget_status", &params)?;
        let bills = queries::run(conn, "upcoming_bills", &json!({ "as_of": as_of.to_iso(), "days": 7 }))?;

        let mut left: std::collections::BTreeMap<String, (i64, i64, i64)> = std::collections::BTreeMap::new();
        let mut over: Vec<Value> = Vec::new();
        for row in budgets.rows.as_array().cloned().unwrap_or_default() {
            let cur = row["currency"].as_str().unwrap_or("").to_string();
            let entry = left.entry(cur).or_insert((0, 0, 0));
            entry.0 += row["budget_minor"].as_i64().unwrap_or(0);
            entry.1 += row["spent_minor"].as_i64().unwrap_or(0);
            entry.2 += row["remaining_minor"].as_i64().unwrap_or(0);
            if row["over_budget"].as_bool().unwrap_or(false) {
                over.push(json!({ "category": row["category"], "currency": row["currency"], "over_by_minor": -row["remaining_minor"].as_i64().unwrap_or(0) }));
            }
        }
        let budget_left: Vec<Value> = left
            .into_iter()
            .map(|(cur, (b, s, r))| json!({ "currency": cur, "budget_minor": b, "spent_minor": s, "remaining_minor": r }))
            .collect();

        let mut sources = budgets.source_ids;
        sources.extend(bills.source_ids);
        Ok(json!({
            "budget_left_this_month": budget_left,
            "over_budget": over,
            "bills_due_7_days": bills.rows,
            "source_ids": sources,
        }))
    })
}

/// Summary across the enabled domains in `handles`. `as_of` defaults to today (UTC).
#[uniffi::export]
pub fn today(handles: Vec<Arc<DomainHandle>>, as_of: Option<String>) -> Result<String, DomainError> {
    let date = match as_of.as_deref() {
        None | Some("") => civil::today(),
        Some(text) => civil::Date::parse(text).ok_or_else(|| DomainError::validation("as_of", "must be YYYY-MM-DD"))?,
    };
    let mut domains = Map::new();
    for handle in &handles {
        match handle.domain_name() {
            finance::DOMAIN => {
                domains.insert("finance".to_string(), finance_today(handle, date)?);
            }
            other => {
                return Err(DomainError::validation("handles", format!("no Today section for domain {other:?}")));
            }
        }
    }
    Ok(serde_json::to_string(&json!({ "as_of": date.to_iso(), "domains": Value::Object(domains) }))?)
}
