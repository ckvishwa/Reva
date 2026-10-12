//! Finance commands: validate input against the current projections and decide which
//! events to write. Nothing here writes; the handle appends the returned drafts and
//! applies them to the projections in one transaction.
//!
//! There is deliberately no command that moves money, pays a bill at a bank, or touches
//! credentials. `bill.mark_paid` only *records* that a bill was paid.

use std::collections::BTreeSet;

use rusqlite::Connection;
use serde_json::{Map, Value};

use super::{money, queries, schema};
use crate::civil::{self, Date};
use crate::error::{DomainError, DomainResult};
use crate::events::{self, EventDraft};

type Obj = Map<String, Value>;

pub const COMMANDS: &[&str] = &[
    "account.create",
    "account.update",
    "account.archive",
    "account.unarchive",
    "account.delete",
    "category.create",
    "category.update",
    "category.delete",
    "transaction.create",
    "transaction.update",
    "transaction.delete",
    "budget.set",
    "budget.delete",
    "bill.create",
    "bill.update",
    "bill.mark_paid",
    "bill.delete",
    "networth_snapshot.create",
    "networth_snapshot.delete",
];

const ACCOUNT_KINDS: &[&str] = &["checking", "savings", "credit", "cash", "investment", "loan", "other"];
const CATEGORY_KINDS: &[&str] = &["expense", "income", "transfer"];
const RECURRENCES: &[&str] = &["once", "weekly", "biweekly", "monthly", "quarterly", "yearly"];
const BILL_KINDS: &[&str] = &["bill", "subscription", "income"];

// ---------------------------------------------------------------------------------------------
// Input helpers

fn object(payload: &Value) -> DomainResult<&Obj> {
    payload.as_object().ok_or_else(|| DomainError::validation("payload", "must be a JSON object"))
}

fn reject_unknown(map: &Obj, allowed: &[&str]) -> DomainResult<()> {
    for key in map.keys() {
        if !allowed.contains(&key.as_str()) {
            return Err(DomainError::validation(key.clone(), "unknown field"));
        }
    }
    Ok(())
}

fn text_field(map: &Obj, key: &str, max: usize, required: bool) -> DomainResult<Option<String>> {
    match map.get(key) {
        None | Some(Value::Null) => {
            if required {
                Err(DomainError::validation(key, "required"))
            } else {
                Ok(None)
            }
        }
        Some(Value::String(s)) => {
            let trimmed = s.trim();
            if trimmed.is_empty() {
                return if required { Err(DomainError::validation(key, "must not be empty")) } else { Ok(None) };
            }
            if trimmed.chars().count() > max {
                return Err(DomainError::validation(key, format!("longer than {max} characters")));
            }
            if trimmed.chars().any(|c| c.is_control() && c != '\n' && c != '\t') {
                return Err(DomainError::validation(key, "contains control characters"));
            }
            Ok(Some(trimmed.to_string()))
        }
        Some(_) => Err(DomainError::validation(key, "must be a string")),
    }
}

fn int_field(map: &Obj, key: &str, required: bool) -> DomainResult<Option<i64>> {
    match map.get(key) {
        None | Some(Value::Null) => {
            if required {
                Err(DomainError::validation(key, "required"))
            } else {
                Ok(None)
            }
        }
        Some(v) => v.as_i64().map(Some).ok_or_else(|| DomainError::validation(key, "must be an integer")),
    }
}

fn date_field(map: &Obj, key: &str, required: bool) -> DomainResult<Option<Date>> {
    match text_field(map, key, 10, required)? {
        None => Ok(None),
        Some(s) => {
            Date::parse(&s).map(Some).ok_or_else(|| DomainError::validation(key, "must be a valid YYYY-MM-DD date"))
        }
    }
}

fn enum_field(map: &Obj, key: &str, allowed: &[&str]) -> DomainResult<Option<String>> {
    match text_field(map, key, 32, false)? {
        None => Ok(None),
        Some(s) => {
            if allowed.contains(&s.as_str()) {
                Ok(Some(s))
            } else {
                Err(DomainError::validation(key, format!("must be one of {}", allowed.join(", "))))
            }
        }
    }
}

fn currency_field(map: &Obj, key: &str) -> DomainResult<Option<String>> {
    match text_field(map, key, 3, false)? {
        None => Ok(None),
        Some(c) => {
            if money::valid_currency(&c) {
                Ok(Some(c))
            } else {
                Err(DomainError::validation(key, "must be a 3-letter uppercase ISO 4217 code"))
            }
        }
    }
}

fn amount_ok(key: &str, amount: i64, allow_zero: bool) -> DomainResult<()> {
    if amount == 0 && !allow_zero {
        return Err(DomainError::validation(key, "must not be zero"));
    }
    if amount.abs() > money::MAX_ABS_MINOR {
        return Err(DomainError::validation(key, "amount too large"));
    }
    Ok(())
}

pub fn valid_id(id: &str) -> bool {
    (8..=64).contains(&id.len()) && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn id_for_new(map: &Obj) -> DomainResult<String> {
    match text_field(map, "id", 64, false)? {
        None => Ok(uuid::Uuid::new_v4().to_string()),
        Some(id) if valid_id(&id) => Ok(id),
        Some(_) => Err(DomainError::validation("id", "must be 8-64 characters of letters, digits, '_' or '-'")),
    }
}

fn id_of(map: &Obj, key: &str) -> DomainResult<String> {
    text_field(map, key, 64, true)?.ok_or_else(|| DomainError::validation(key, "required"))
}

fn norm(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

/// A live aggregate, or the precise typed error for a missing or deleted one.
fn require_live(conn: &Connection, aggregate_type: &str, id: &str) -> DomainResult<Obj> {
    if events::is_tombstoned(conn, aggregate_type, id)? {
        return Err(DomainError::Deleted { detail: format!("{aggregate_type} {id}") });
    }
    schema::load(conn, aggregate_type, id)?.ok_or_else(|| DomainError::not_found(format!("{aggregate_type} {id}")))
}

fn ensure_new(conn: &Connection, aggregate_type: &str, id: &str) -> DomainResult<()> {
    if events::is_tombstoned(conn, aggregate_type, id)? || schema::load(conn, aggregate_type, id)?.is_some() {
        return Err(DomainError::conflict(format!("{aggregate_type} {id} already exists")));
    }
    Ok(())
}

fn draft(aggregate_type: &str, id: &str, action: &str, state: Obj) -> EventDraft {
    EventDraft {
        aggregate_type: aggregate_type.to_string(),
        aggregate_id: id.to_string(),
        kind: format!("{aggregate_type}.{action}"),
        tombstone: action == "deleted",
        payload: if action == "deleted" { Value::Object(Map::new()) } else { Value::Object(state) },
    }
}

fn set(state: &mut Obj, key: &str, value: impl Into<Value>) {
    state.insert(key.to_string(), value.into());
}

// ---------------------------------------------------------------------------------------------
// Dispatch

pub fn handle(conn: &Connection, kind: &str, payload: &Value) -> DomainResult<Vec<EventDraft>> {
    let now = civil::now_iso();
    match kind {
        "account.create" => account_create(conn, payload, &now),
        "account.update" => account_update(conn, payload, &now, None),
        "account.archive" => account_update(conn, payload, &now, Some(true)),
        "account.unarchive" => account_update(conn, payload, &now, Some(false)),
        "account.delete" => account_delete(conn, payload),
        "category.create" => category_create(conn, payload, &now),
        "category.update" => category_update(conn, payload, &now),
        "category.delete" => category_delete(conn, payload),
        "transaction.create" => transaction_create(conn, payload, &now),
        "transaction.update" => transaction_update(conn, payload, &now),
        "transaction.delete" => simple_delete(conn, "transaction", payload),
        "budget.set" => budget_set(conn, payload, &now),
        "budget.delete" => simple_delete(conn, "budget", payload),
        "bill.create" => bill_create(conn, payload, &now),
        "bill.update" => bill_update(conn, payload, &now),
        "bill.mark_paid" => bill_mark_paid(conn, payload, &now),
        "bill.delete" => simple_delete(conn, "bill", payload),
        "networth_snapshot.create" => networth_create(conn, payload, &now),
        "networth_snapshot.delete" => simple_delete(conn, "networth_snapshot", payload),
        other => Err(DomainError::validation("kind", format!("unknown finance command {other:?}"))),
    }
}

fn simple_delete(conn: &Connection, aggregate_type: &str, payload: &Value) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id"])?;
    let id = id_of(map, "id")?;
    require_live(conn, aggregate_type, &id)?;
    Ok(vec![draft(aggregate_type, &id, "deleted", Map::new())])
}

// ---------------------------------------------------------------------------------------------
// Accounts

fn account_create(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id", "name", "kind", "currency", "opening_balance_minor"])?;
    let id = id_for_new(map)?;
    ensure_new(conn, "account", &id)?;
    let name = text_field(map, "name", 200, true)?.unwrap_or_default();
    let kind = enum_field(map, "kind", ACCOUNT_KINDS)?.unwrap_or_else(|| "checking".to_string());
    let currency = currency_field(map, "currency")?.ok_or_else(|| DomainError::validation("currency", "required"))?;
    let opening = int_field(map, "opening_balance_minor", false)?.unwrap_or(0);
    amount_ok("opening_balance_minor", opening, true)?;
    ensure_account_name_free(conn, &name, None)?;

    let mut s = Obj::new();
    set(&mut s, "id", id.clone());
    set(&mut s, "name", name);
    set(&mut s, "kind", kind);
    set(&mut s, "currency", currency);
    set(&mut s, "opening_balance_minor", opening);
    set(&mut s, "archived", false);
    set(&mut s, "created_at", now);
    set(&mut s, "updated_at", now);
    Ok(vec![draft("account", &id, "created", s)])
}

fn ensure_account_name_free(conn: &Connection, name: &str, except: Option<&str>) -> DomainResult<()> {
    for a in schema::select(conn, "account", "", vec![])? {
        if a["id"].as_str() != except && norm(a["name"].as_str().unwrap_or("")) == norm(name) {
            return Err(DomainError::conflict(format!("an account named {name:?} already exists")));
        }
    }
    Ok(())
}

fn account_update(
    conn: &Connection,
    payload: &Value,
    now: &str,
    archive: Option<bool>,
) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    if archive.is_some() {
        reject_unknown(map, &["id"])?;
    } else {
        reject_unknown(map, &["id", "name", "kind", "opening_balance_minor"])?;
    }
    let id = id_of(map, "id")?;
    let mut s = require_live(conn, "account", &id)?;
    if let Some(flag) = archive {
        set(&mut s, "archived", flag);
    } else {
        if let Some(name) = text_field(map, "name", 200, false)? {
            ensure_account_name_free(conn, &name, Some(&id))?;
            set(&mut s, "name", name);
        }
        if let Some(kind) = enum_field(map, "kind", ACCOUNT_KINDS)? {
            set(&mut s, "kind", kind);
        }
        if let Some(opening) = int_field(map, "opening_balance_minor", false)? {
            amount_ok("opening_balance_minor", opening, true)?;
            set(&mut s, "opening_balance_minor", opening);
        }
    }
    set(&mut s, "updated_at", now);
    Ok(vec![draft("account", &id, "updated", s)])
}

fn account_delete(conn: &Connection, payload: &Value) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id"])?;
    let id = id_of(map, "id")?;
    require_live(conn, "account", &id)?;
    let used: i64 = conn.query_row("SELECT COUNT(*) FROM transactions WHERE account_id = ?1", [&id], |r| r.get(0))?;
    let billed: i64 = conn.query_row("SELECT COUNT(*) FROM bills WHERE account_id = ?1", [&id], |r| r.get(0))?;
    if used > 0 || billed > 0 {
        return Err(DomainError::conflict(format!(
            "account has {used} transactions and {billed} bills; archive it instead of deleting"
        )));
    }
    Ok(vec![draft("account", &id, "deleted", Map::new())])
}

// ---------------------------------------------------------------------------------------------
// Categories

fn aliases_field(map: &Obj) -> DomainResult<Option<Vec<String>>> {
    match map.get("aliases") {
        None => Ok(None),
        Some(Value::Array(items)) => {
            let mut out: BTreeSet<String> = BTreeSet::new();
            for item in items {
                let s = item.as_str().ok_or_else(|| DomainError::validation("aliases", "must be strings"))?;
                let a = norm(s);
                if a.is_empty() || a.chars().count() > 60 {
                    return Err(DomainError::validation("aliases", "each alias must be 1-60 characters"));
                }
                out.insert(a);
            }
            Ok(Some(out.into_iter().collect()))
        }
        Some(_) => Err(DomainError::validation("aliases", "must be an array of strings")),
    }
}

/// Names and aliases of live categories must not collide (case-insensitive).
fn ensure_category_terms_free(
    conn: &Connection,
    name: &str,
    aliases: &[String],
    except: Option<&str>,
) -> DomainResult<()> {
    let mine: BTreeSet<String> = std::iter::once(norm(name)).chain(aliases.iter().cloned()).collect();
    for c in schema::select(conn, "category", "", vec![])? {
        if c["id"].as_str() == except {
            continue;
        }
        let mut theirs: BTreeSet<String> = BTreeSet::new();
        theirs.insert(norm(c["name"].as_str().unwrap_or("")));
        if let Some(Value::Array(items)) = c.get("aliases") {
            theirs.extend(items.iter().filter_map(Value::as_str).map(norm));
        }
        if let Some(term) = mine.intersection(&theirs).next() {
            return Err(DomainError::conflict(format!(
                "{term:?} is already used by category {:?}",
                c["name"].as_str().unwrap_or("")
            )));
        }
    }
    Ok(())
}

fn category_create(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id", "name", "kind", "parent_id", "aliases"])?;
    let id = id_for_new(map)?;
    ensure_new(conn, "category", &id)?;
    let name = text_field(map, "name", 100, true)?.unwrap_or_default();
    let kind = enum_field(map, "kind", CATEGORY_KINDS)?.unwrap_or_else(|| "expense".to_string());
    let aliases = aliases_field(map)?.unwrap_or_default();
    let parent = text_field(map, "parent_id", 64, false)?;
    if let Some(p) = &parent {
        require_live(conn, "category", p)?;
    }
    ensure_category_terms_free(conn, &name, &aliases, None)?;
    let mut s = Obj::new();
    set(&mut s, "id", id.clone());
    set(&mut s, "name", name);
    set(&mut s, "kind", kind);
    set(&mut s, "parent_id", parent.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "aliases", Value::from(aliases));
    set(&mut s, "created_at", now);
    set(&mut s, "updated_at", now);
    Ok(vec![draft("category", &id, "created", s)])
}

fn category_update(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id", "name", "kind", "parent_id", "aliases"])?;
    let id = id_of(map, "id")?;
    let mut s = require_live(conn, "category", &id)?;
    if let Some(name) = text_field(map, "name", 100, false)? {
        set(&mut s, "name", name);
    }
    if let Some(kind) = enum_field(map, "kind", CATEGORY_KINDS)? {
        set(&mut s, "kind", kind);
    }
    if map.contains_key("parent_id") {
        let parent = text_field(map, "parent_id", 64, false)?;
        if let Some(p) = &parent {
            if p == &id {
                return Err(DomainError::validation("parent_id", "a category cannot be its own parent"));
            }
            require_live(conn, "category", p)?;
        }
        set(&mut s, "parent_id", parent.map(Value::from).unwrap_or(Value::Null));
    }
    if let Some(aliases) = aliases_field(map)? {
        set(&mut s, "aliases", Value::from(aliases));
    }
    let name = s["name"].as_str().unwrap_or("").to_string();
    let aliases: Vec<String> = s["aliases"]
        .as_array()
        .map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect())
        .unwrap_or_default();
    ensure_category_terms_free(conn, &name, &aliases, Some(&id))?;
    set(&mut s, "updated_at", now);
    Ok(vec![draft("category", &id, "updated", s)])
}

fn category_delete(conn: &Connection, payload: &Value) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id"])?;
    let id = id_of(map, "id")?;
    require_live(conn, "category", &id)?;
    let tx: i64 = conn.query_row("SELECT COUNT(*) FROM transactions WHERE category_id = ?1", [&id], |r| r.get(0))?;
    let budgets: i64 = conn.query_row("SELECT COUNT(*) FROM budgets WHERE category_id = ?1", [&id], |r| r.get(0))?;
    let bills: i64 = conn.query_row("SELECT COUNT(*) FROM bills WHERE category_id = ?1", [&id], |r| r.get(0))?;
    let children: i64 = conn.query_row("SELECT COUNT(*) FROM categories WHERE parent_id = ?1", [&id], |r| r.get(0))?;
    if tx + budgets + bills + children > 0 {
        return Err(DomainError::conflict(format!(
            "category is used by {tx} transactions, {budgets} budgets, {bills} bills and {children} sub-categories"
        )));
    }
    Ok(vec![draft("category", &id, "deleted", Map::new())])
}

// ---------------------------------------------------------------------------------------------
// Transactions

pub struct NewTransaction {
    pub id: Option<String>,
    pub account_id: String,
    pub date: Date,
    pub amount_minor: i64,
    pub currency: Option<String>,
    pub description: String,
    pub merchant: Option<String>,
    pub category_id: Option<String>,
    pub notes: Option<String>,
    pub import_batch_id: Option<String>,
    pub fingerprint: Option<String>,
}

/// Validate and build the full state of a new transaction. Also used by import.
pub fn build_transaction(conn: &Connection, nt: NewTransaction, now: &str) -> DomainResult<(String, Obj)> {
    let id = match nt.id {
        Some(id) if valid_id(&id) => id,
        Some(_) => return Err(DomainError::validation("id", "must be 8-64 characters of letters, digits, '_' or '-'")),
        None => uuid::Uuid::new_v4().to_string(),
    };
    ensure_new(conn, "transaction", &id)?;
    let account = require_live(conn, "account", &nt.account_id)?;
    if account["archived"].as_bool().unwrap_or(false) {
        return Err(DomainError::conflict("account is archived"));
    }
    let account_currency = account["currency"].as_str().unwrap_or("").to_string();
    let currency = nt.currency.unwrap_or_else(|| account_currency.clone());
    if currency != account_currency {
        return Err(DomainError::validation("currency", format!("account uses {account_currency}")));
    }
    amount_ok("amount_minor", nt.amount_minor, false)?;
    if let Some(cat) = &nt.category_id {
        require_live(conn, "category", cat)?;
    }
    let mut s = Obj::new();
    set(&mut s, "id", id.clone());
    set(&mut s, "account_id", nt.account_id);
    set(&mut s, "date", nt.date.to_iso());
    set(&mut s, "amount_minor", nt.amount_minor);
    set(&mut s, "currency", currency);
    set(&mut s, "description", nt.description);
    set(&mut s, "merchant", nt.merchant.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "category_id", nt.category_id.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "notes", nt.notes.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "import_batch_id", nt.import_batch_id.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "fingerprint", nt.fingerprint.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "created_at", now);
    set(&mut s, "updated_at", now);
    Ok((id, s))
}

fn category_from_input(conn: &Connection, map: &Obj) -> DomainResult<Option<Option<String>>> {
    // Some(None) = explicitly clear, Some(Some(id)) = set, None = not provided.
    if map.contains_key("category_id") {
        return match text_field(map, "category_id", 64, false)? {
            None => Ok(Some(None)),
            Some(id) => {
                require_live(conn, "category", &id)?;
                Ok(Some(Some(id)))
            }
        };
    }
    if map.contains_key("category") {
        return match text_field(map, "category", 100, false)? {
            None => Ok(Some(None)),
            Some(name) => match queries::resolve_category(conn, &name)? {
                Some(id) => Ok(Some(Some(id))),
                None => Err(DomainError::validation("category", format!("no category or alias named {name:?}"))),
            },
        };
    }
    Ok(None)
}

fn transaction_create(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(
        map,
        &[
            "id",
            "account_id",
            "date",
            "amount_minor",
            "currency",
            "description",
            "merchant",
            "category",
            "category_id",
            "notes",
        ],
    )?;
    let category_id = category_from_input(conn, map)?.flatten();
    let nt = NewTransaction {
        id: text_field(map, "id", 64, false)?,
        account_id: id_of(map, "account_id")?,
        date: date_field(map, "date", true)?.ok_or_else(|| DomainError::validation("date", "required"))?,
        amount_minor: int_field(map, "amount_minor", true)?.unwrap_or(0),
        currency: currency_field(map, "currency")?,
        description: text_field(map, "description", 500, true)?.unwrap_or_default(),
        merchant: text_field(map, "merchant", 200, false)?,
        category_id,
        notes: text_field(map, "notes", 2000, false)?,
        import_batch_id: None,
        fingerprint: None,
    };
    let (id, state) = build_transaction(conn, nt, now)?;
    Ok(vec![draft("transaction", &id, "created", state)])
}

fn transaction_update(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(
        map,
        &["id", "account_id", "date", "amount_minor", "description", "merchant", "category", "category_id", "notes"],
    )?;
    let id = id_of(map, "id")?;
    let mut s = require_live(conn, "transaction", &id)?;
    if let Some(account_id) = text_field(map, "account_id", 64, false)? {
        let account = require_live(conn, "account", &account_id)?;
        if account["currency"] != s["currency"] {
            return Err(DomainError::validation("account_id", "target account uses a different currency"));
        }
        if account["archived"].as_bool().unwrap_or(false) {
            return Err(DomainError::conflict("account is archived"));
        }
        set(&mut s, "account_id", account_id);
    }
    if let Some(date) = date_field(map, "date", false)? {
        set(&mut s, "date", date.to_iso());
    }
    if let Some(amount) = int_field(map, "amount_minor", false)? {
        amount_ok("amount_minor", amount, false)?;
        set(&mut s, "amount_minor", amount);
    }
    if let Some(d) = text_field(map, "description", 500, false)? {
        set(&mut s, "description", d);
    }
    for key in ["merchant", "notes"] {
        if map.contains_key(key) {
            let max = if key == "merchant" { 200 } else { 2000 };
            set(&mut s, key, text_field(map, key, max, false)?.map(Value::from).unwrap_or(Value::Null));
        }
    }
    if let Some(cat) = category_from_input(conn, map)? {
        set(&mut s, "category_id", cat.map(Value::from).unwrap_or(Value::Null));
    }
    set(&mut s, "updated_at", now);
    Ok(vec![draft("transaction", &id, "updated", s)])
}

// ---------------------------------------------------------------------------------------------
// Budgets

fn budget_set(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id", "category_id", "category", "amount_minor", "currency", "start_month"])?;
    let category_id = match category_from_input(conn, map)? {
        Some(Some(id)) => id,
        _ => return Err(DomainError::validation("category_id", "required")),
    };
    let amount = int_field(map, "amount_minor", true)?.unwrap_or(0);
    if amount <= 0 {
        return Err(DomainError::validation("amount_minor", "must be greater than zero"));
    }
    amount_ok("amount_minor", amount, false)?;
    let currency = currency_field(map, "currency")?.ok_or_else(|| DomainError::validation("currency", "required"))?;
    let start_month = match text_field(map, "start_month", 7, false)? {
        None => {
            let today = civil::today();
            format!("{:04}-{:02}", today.year, today.month)
        }
        Some(m) => {
            Date::parse(&format!("{m}-01")).ok_or_else(|| DomainError::validation("start_month", "must be YYYY-MM"))?;
            m
        }
    };
    let existing = schema::select(
        conn,
        "budget",
        "WHERE category_id = ?1 AND currency = ?2",
        vec![rusqlite::types::Value::Text(category_id.clone()), rusqlite::types::Value::Text(currency.clone())],
    )?;
    if let Some(mut s) = existing.into_iter().next() {
        let id = s["id"].as_str().unwrap_or("").to_string();
        set(&mut s, "amount_minor", amount);
        set(&mut s, "start_month", start_month);
        set(&mut s, "updated_at", now);
        return Ok(vec![draft("budget", &id, "updated", s)]);
    }
    let id = id_for_new(map)?;
    ensure_new(conn, "budget", &id)?;
    let mut s = Obj::new();
    set(&mut s, "id", id.clone());
    set(&mut s, "category_id", category_id);
    set(&mut s, "period", "monthly");
    set(&mut s, "amount_minor", amount);
    set(&mut s, "currency", currency);
    set(&mut s, "start_month", start_month);
    set(&mut s, "created_at", now);
    set(&mut s, "updated_at", now);
    Ok(vec![draft("budget", &id, "created", s)])
}

// ---------------------------------------------------------------------------------------------
// Bills

pub fn next_due(due: Date, anchor_day: u32, recurrence: &str) -> Option<Date> {
    let with_anchor = |d: Date| {
        let day = anchor_day.min(civil::days_in_month(d.year, d.month));
        Date { year: d.year, month: d.month, day }
    };
    match recurrence {
        "weekly" => Some(due.add_days(7)),
        "biweekly" => Some(due.add_days(14)),
        "monthly" => Some(with_anchor(due.first_of_month().add_months(1))),
        "quarterly" => Some(with_anchor(due.first_of_month().add_months(3))),
        "yearly" => Some(with_anchor(due.first_of_month().add_months(12))),
        _ => None,
    }
}

fn bill_create(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(
        map,
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
            "category",
            "notes",
        ],
    )?;
    let id = id_for_new(map)?;
    ensure_new(conn, "bill", &id)?;
    let name = text_field(map, "name", 200, true)?.unwrap_or_default();
    let kind = enum_field(map, "kind", BILL_KINDS)?.unwrap_or_else(|| "bill".to_string());
    let amount = int_field(map, "amount_minor", true)?.unwrap_or(0);
    if amount <= 0 {
        return Err(DomainError::validation("amount_minor", "must be greater than zero (the amount due)"));
    }
    amount_ok("amount_minor", amount, false)?;
    let currency = currency_field(map, "currency")?.ok_or_else(|| DomainError::validation("currency", "required"))?;
    let recurrence = enum_field(map, "recurrence", RECURRENCES)?.unwrap_or_else(|| "monthly".to_string());
    let due = date_field(map, "due_date", true)?.ok_or_else(|| DomainError::validation("due_date", "required"))?;
    let account_id = text_field(map, "account_id", 64, false)?;
    if let Some(a) = &account_id {
        let account = require_live(conn, "account", a)?;
        if account["currency"].as_str() != Some(currency.as_str()) {
            return Err(DomainError::validation("account_id", "account uses a different currency"));
        }
    }
    let category_id = category_from_input(conn, map)?.flatten();
    let mut s = Obj::new();
    set(&mut s, "id", id.clone());
    set(&mut s, "name", name);
    set(&mut s, "kind", kind);
    set(&mut s, "amount_minor", amount);
    set(&mut s, "currency", currency);
    set(&mut s, "recurrence", recurrence);
    set(&mut s, "due_date", due.to_iso());
    set(&mut s, "anchor_day", i64::from(due.day));
    set(&mut s, "account_id", account_id.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "category_id", category_id.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "notes", text_field(map, "notes", 2000, false)?.map(Value::from).unwrap_or(Value::Null));
    set(&mut s, "last_paid_date", Value::Null);
    set(&mut s, "active", true);
    set(&mut s, "created_at", now);
    set(&mut s, "updated_at", now);
    Ok(vec![draft("bill", &id, "created", s)])
}

fn bill_update(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(
        map,
        &[
            "id",
            "name",
            "kind",
            "amount_minor",
            "recurrence",
            "due_date",
            "account_id",
            "category_id",
            "category",
            "notes",
            "active",
        ],
    )?;
    let id = id_of(map, "id")?;
    let mut s = require_live(conn, "bill", &id)?;
    if let Some(name) = text_field(map, "name", 200, false)? {
        set(&mut s, "name", name);
    }
    if let Some(kind) = enum_field(map, "kind", BILL_KINDS)? {
        set(&mut s, "kind", kind);
    }
    if let Some(amount) = int_field(map, "amount_minor", false)? {
        if amount <= 0 {
            return Err(DomainError::validation("amount_minor", "must be greater than zero"));
        }
        amount_ok("amount_minor", amount, false)?;
        set(&mut s, "amount_minor", amount);
    }
    if let Some(r) = enum_field(map, "recurrence", RECURRENCES)? {
        set(&mut s, "recurrence", r);
    }
    if let Some(due) = date_field(map, "due_date", false)? {
        set(&mut s, "due_date", due.to_iso());
        set(&mut s, "anchor_day", i64::from(due.day));
    }
    if map.contains_key("account_id") {
        let a = text_field(map, "account_id", 64, false)?;
        if let Some(a) = &a {
            let account = require_live(conn, "account", a)?;
            if account["currency"] != s["currency"] {
                return Err(DomainError::validation("account_id", "account uses a different currency"));
            }
        }
        set(&mut s, "account_id", a.map(Value::from).unwrap_or(Value::Null));
    }
    if let Some(cat) = category_from_input(conn, map)? {
        set(&mut s, "category_id", cat.map(Value::from).unwrap_or(Value::Null));
    }
    if map.contains_key("notes") {
        set(&mut s, "notes", text_field(map, "notes", 2000, false)?.map(Value::from).unwrap_or(Value::Null));
    }
    if let Some(active) = map.get("active") {
        set(&mut s, "active", active.as_bool().ok_or_else(|| DomainError::validation("active", "must be a boolean"))?);
    }
    set(&mut s, "updated_at", now);
    Ok(vec![draft("bill", &id, "updated", s)])
}

/// Records that a bill was paid. It does not pay anything: it advances the due date and,
/// if asked, writes the matching expense transaction into the ledger.
fn bill_mark_paid(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id", "paid_date", "record_transaction", "account_id"])?;
    let id = id_of(map, "id")?;
    let mut s = require_live(conn, "bill", &id)?;
    if !s["active"].as_bool().unwrap_or(false) {
        return Err(DomainError::conflict("bill is no longer active"));
    }
    let paid = date_field(map, "paid_date", true)?.ok_or_else(|| DomainError::validation("paid_date", "required"))?;
    let due = Date::parse(s["due_date"].as_str().unwrap_or(""))
        .ok_or_else(|| DomainError::internal("bill has a bad due date"))?;
    let anchor = s["anchor_day"].as_i64().unwrap_or(i64::from(due.day)) as u32;
    let recurrence = s["recurrence"].as_str().unwrap_or("once").to_string();
    set(&mut s, "last_paid_date", paid.to_iso());
    match next_due(due, anchor, &recurrence) {
        Some(next) => set(&mut s, "due_date", next.to_iso()),
        None => set(&mut s, "active", false),
    }
    set(&mut s, "updated_at", now);
    let mut drafts = vec![draft("bill", &id, "updated", s.clone())];

    if map.get("record_transaction").and_then(Value::as_bool).unwrap_or(false) {
        let account_id = match text_field(map, "account_id", 64, false)? {
            Some(a) => a,
            None => s["account_id"]
                .as_str()
                .map(str::to_string)
                .ok_or_else(|| DomainError::validation("account_id", "required to record the transaction"))?,
        };
        let amount = s["amount_minor"].as_i64().unwrap_or(0);
        let signed = if s["kind"].as_str() == Some("income") { amount } else { -amount };
        let nt = NewTransaction {
            id: None,
            account_id,
            date: paid,
            amount_minor: signed,
            currency: s["currency"].as_str().map(str::to_string),
            description: s["name"].as_str().unwrap_or("Bill").to_string(),
            merchant: None,
            category_id: s["category_id"].as_str().map(str::to_string),
            notes: Some(format!("Recorded from bill {id}")),
            import_batch_id: None,
            fingerprint: None,
        };
        let (tid, state) = build_transaction(conn, nt, now)?;
        drafts.push(draft("transaction", &tid, "created", state));
    }
    Ok(drafts)
}

// ---------------------------------------------------------------------------------------------
// Net worth

fn networth_create(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = object(payload)?;
    reject_unknown(map, &["id", "as_of"])?;
    let id = id_for_new(map)?;
    ensure_new(conn, "networth_snapshot", &id)?;
    let as_of = date_field(map, "as_of", false)?.unwrap_or_else(civil::today);
    let by_currency = queries::networth_by_currency(conn, as_of)?;
    let mut s = Obj::new();
    set(&mut s, "id", id.clone());
    set(&mut s, "as_of", as_of.to_iso());
    set(&mut s, "by_currency", by_currency);
    set(&mut s, "created_at", now);
    set(&mut s, "updated_at", now);
    Ok(vec![draft("networth_snapshot", &id, "created", s)])
}
