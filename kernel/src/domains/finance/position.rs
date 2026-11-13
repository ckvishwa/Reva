//! FIN-4: money between the owner and other people, earnings, and the owner's whole position.
//!
//! A *personal debt* records money lent to someone (they owe the owner) or borrowed from someone (the owner
//! owes them), and each settlement of it. Like FIN-3 this only records what already happened: nothing here
//! moves money, contacts anyone or converts currency.
//!
//! Accounting rules:
//! - Lending money is not spending, and getting it back is not income. Borrowing is not income, and paying
//!   it back is not spending. When the owner names the account the money moved through, the leg carries a
//!   neutral link role (`debt_open`, `debt_settle`) so no report counts it.
//! - Net position adds what people owe the owner and subtracts what the owner owes (cards, loans, people),
//!   per currency. Nothing is converted.

use std::collections::BTreeMap;

use rusqlite::Connection;
use serde_json::{json, Map, Value};

use super::accounting::NEUTRAL_ROLES;
use super::commands::{self as c, NewTransaction};
use super::queries::{self, QueryOut};
use super::schema;
use crate::civil::Date;
use crate::error::{DomainError, DomainResult};
use crate::events::EventDraft;

type Obj = Map<String, Value>;

pub const COMMANDS: &[&str] =
    &["personal_debt.record", "personal_debt.update", "personal_debt.settle", "personal_debt.delete"];

/// Link roles of personal-debt legs. Both are neutral (see [`NEUTRAL_ROLES`]).
pub const DEBT_ROLES: &[&str] = &["debt_open", "debt_settle"];

const DIRECTIONS: &[&str] = &["lent", "borrowed"];

// ---------------------------------------------------------------------------------------------
// Commands

pub fn handle(conn: &Connection, kind: &str, payload: &Value, now: &str) -> Option<DomainResult<Vec<EventDraft>>> {
    Some(match kind {
        "personal_debt.record" => record(conn, payload, now),
        "personal_debt.update" => update(conn, payload, now),
        "personal_debt.settle" => settle(conn, payload, now),
        "personal_debt.delete" => delete(conn, payload),
        _ => return None,
    })
}

fn debt_id(map: &Obj) -> DomainResult<String> {
    let id = match c::text_field(map, "id", 40, false)? {
        Some(id) => id,
        None => uuid::Uuid::new_v4().simple().to_string(),
    };
    if !c::valid_id(&id) || id.len() > 40 {
        return Err(DomainError::validation("id", "must be 8-40 characters of letters, digits, '_' or '-'"));
    }
    Ok(id)
}

fn positive(map: &Obj, key: &str) -> DomainResult<i64> {
    let amount = c::int_field(map, key, true)?.unwrap_or(0);
    if amount <= 0 {
        return Err(DomainError::validation(key, "must be greater than zero"));
    }
    c::amount_ok(key, amount, false)?;
    Ok(amount)
}

/// The account the money moved through, checked against the debt's currency.
fn through_account(conn: &Connection, map: &Obj, currency: Option<&str>) -> DomainResult<Option<Obj>> {
    let Some(id) = c::text_field(map, "account_id", 64, false)? else { return Ok(None) };
    let account = c::require_live(conn, "account", &id)?;
    if account["archived"].as_bool().unwrap_or(false) {
        return Err(DomainError::conflict("account is archived"));
    }
    if let Some(cur) = currency {
        if account["currency"].as_str() != Some(cur) {
            return Err(DomainError::validation(
                "account_id",
                "account uses a different currency; REVA never converts currencies automatically",
            ));
        }
    }
    Ok(Some(account))
}

#[allow(clippy::too_many_arguments)]
fn debt_leg(
    conn: &Connection,
    leg_id: String,
    account_id: &str,
    date: Date,
    amount: i64,
    description: String,
    debt: &str,
    role: &'static str,
    external_ref: Option<String>,
    now: &str,
) -> DomainResult<EventDraft> {
    let nt = NewTransaction {
        id: Some(leg_id),
        account_id: account_id.to_string(),
        date,
        amount_minor: amount,
        currency: None,
        description,
        merchant: None,
        category_id: None,
        notes: None,
        import_batch_id: None,
        fingerprint: None,
        source: Some("manual".to_string()),
    };
    let (id, mut s) = c::build_transaction(conn, nt, now)?;
    c::set(&mut s, "link_id", debt);
    c::set(&mut s, "link_role", role);
    c::set(&mut s, "external_ref", external_ref.map(Value::from).unwrap_or(Value::Null));
    Ok(c::draft("transaction", &id, "created", s))
}

/// Sign of the account leg: lending takes money out of the owner's account, borrowing puts it in, and a
/// settlement goes the other way.
fn signed(direction: &str, amount: i64, settling: bool) -> i64 {
    let out = (direction == "lent") != settling;
    if out {
        -amount
    } else {
        amount
    }
}

/// `personal_debt.record`: money lent to or borrowed from someone.
fn record(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(
        map,
        &["id", "counterparty", "direction", "amount_minor", "currency", "date", "due_date", "account_id", "notes"],
    )?;
    let id = debt_id(map)?;
    c::ensure_new(conn, "personal_debt", &id)?;
    let counterparty = c::text_field(map, "counterparty", 200, true)?.unwrap_or_default();
    let direction = c::enum_field(map, "direction", DIRECTIONS)?
        .ok_or_else(|| DomainError::validation("direction", "required: lent or borrowed"))?;
    let amount = positive(map, "amount_minor")?;
    let date = c::date_field(map, "date", true)?.ok_or_else(|| DomainError::validation("date", "required"))?;
    let due = c::date_field(map, "due_date", false)?;
    if due.map(|d| d < date).unwrap_or(false) {
        return Err(DomainError::validation("due_date", "before the date the debt started"));
    }
    let given_currency = c::currency_field(map, "currency")?;
    let account = through_account(conn, map, given_currency.as_deref())?;
    let currency = match (given_currency, &account) {
        (Some(cur), _) => cur,
        (None, Some(a)) => a["currency"].as_str().unwrap_or_default().to_string(),
        (None, None) => return Err(DomainError::validation("currency", "required when no account_id is given")),
    };
    let mut s = Obj::new();
    c::set(&mut s, "id", id.clone());
    c::set(&mut s, "counterparty", counterparty.clone());
    c::set(&mut s, "direction", direction.clone());
    c::set(&mut s, "principal_minor", amount);
    c::set(&mut s, "currency", currency);
    c::set(&mut s, "date", date.to_iso());
    c::set(&mut s, "due_date", due.map(|d| Value::from(d.to_iso())).unwrap_or(Value::Null));
    c::set(&mut s, "account_id", account.as_ref().map(|a| a["id"].clone()).unwrap_or(Value::Null));
    c::set(&mut s, "notes", c::text_field(map, "notes", 2000, false)?.map(Value::from).unwrap_or(Value::Null));
    c::set(&mut s, "settlements", json!([]));
    c::set(&mut s, "created_at", now);
    c::set(&mut s, "updated_at", now);
    let mut drafts = vec![c::draft("personal_debt", &id, "recorded", s)];
    if let Some(a) = account {
        let text = if direction == "lent" {
            format!("Lent to {counterparty}")
        } else {
            format!("Borrowed from {counterparty}")
        };
        drafts.push(debt_leg(
            conn,
            format!("{id}-open"),
            a["id"].as_str().unwrap_or_default(),
            date,
            signed(&direction, amount, false),
            text,
            &id,
            "debt_open",
            None,
            now,
        )?);
    }
    Ok(drafts)
}

/// `personal_debt.update`: who, when it is due, and notes. Amounts are fixed once recorded; delete the debt
/// and record it again to change them.
fn update(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(map, &["id", "counterparty", "due_date", "notes"])?;
    let id = c::id_of(map, "id")?;
    let mut s = c::require_live(conn, "personal_debt", &id)?;
    if let Some(name) = c::text_field(map, "counterparty", 200, false)? {
        c::set(&mut s, "counterparty", name);
    }
    if map.contains_key("due_date") {
        let due = c::date_field(map, "due_date", false)?;
        let start = s["date"].as_str().and_then(Date::parse);
        if let (Some(d), Some(start)) = (due, start) {
            if d < start {
                return Err(DomainError::validation("due_date", "before the date the debt started"));
            }
        }
        c::set(&mut s, "due_date", due.map(|d| Value::from(d.to_iso())).unwrap_or(Value::Null));
    }
    if map.contains_key("notes") {
        c::set(&mut s, "notes", c::text_field(map, "notes", 2000, false)?.map(Value::from).unwrap_or(Value::Null));
    }
    c::set(&mut s, "updated_at", now);
    Ok(vec![c::draft("personal_debt", &id, "updated", s)])
}

fn settled_total(s: &Obj) -> i64 {
    s.get("settlements")
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(|i| i["amount_minor"].as_i64()).sum())
        .unwrap_or(0)
}

fn outstanding(s: &Obj) -> i64 {
    s["principal_minor"].as_i64().unwrap_or(0) - settled_total(s)
}

/// `personal_debt.settle`: part or all of a debt was settled (money came back, or the owner paid someone
/// back). `external_ref` is an optional provenance key: the same ref with the same facts is a no-op.
fn settle(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(map, &["id", "amount_minor", "date", "account_id", "notes", "external_ref"])?;
    let id = c::id_of(map, "id")?;
    let mut s = c::require_live(conn, "personal_debt", &id)?;
    let amount = positive(map, "amount_minor")?;
    let date = c::date_field(map, "date", true)?.ok_or_else(|| DomainError::validation("date", "required"))?;
    if s["date"].as_str().and_then(Date::parse).map(|start| date < start).unwrap_or(false) {
        return Err(DomainError::validation("date", "before the date the debt started"));
    }
    let left = outstanding(&s);
    if amount > left {
        return Err(DomainError::validation(
            "amount_minor",
            format!("settles {amount}, but only {left} is outstanding"),
        ));
    }
    let currency = s["currency"].as_str().unwrap_or_default().to_string();
    let account = through_account(conn, map, Some(&currency))?;
    let external_ref = c::text_field(map, "external_ref", 200, false)?;
    let mut items = s.get("settlements").and_then(Value::as_array).cloned().unwrap_or_default();
    let number = items.len() + 1;
    let leg_id = format!("{id}-s{number}");
    items.push(json!({
        "n": number,
        "date": date.to_iso(),
        "amount_minor": amount,
        "account_id": account.as_ref().map(|a| a["id"].clone()).unwrap_or(Value::Null),
        "transaction_id": if account.is_some() { Value::from(leg_id.clone()) } else { Value::Null },
        "notes": c::text_field(map, "notes", 2000, false)?,
        "external_ref": external_ref.clone(),
    }));
    c::set(&mut s, "settlements", Value::Array(items));
    c::set(&mut s, "updated_at", now);
    let direction = s["direction"].as_str().unwrap_or("lent").to_string();
    let counterparty = s["counterparty"].as_str().unwrap_or("someone").to_string();
    let mut drafts = vec![c::draft("personal_debt", &id, "settled", s)];
    if let Some(a) = account {
        let text = if direction == "lent" {
            format!("Settled by {counterparty}")
        } else {
            format!("Settled with {counterparty}")
        };
        drafts.push(debt_leg(
            conn,
            leg_id,
            a["id"].as_str().unwrap_or_default(),
            date,
            signed(&direction, amount, true),
            text,
            &id,
            "debt_settle",
            external_ref,
            now,
        )?);
    }
    Ok(drafts)
}

/// `personal_debt.delete`: removes the debt and every account leg it recorded.
fn delete(conn: &Connection, payload: &Value) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(map, &["id"])?;
    let id = c::id_of(map, "id")?;
    c::require_live(conn, "personal_debt", &id)?;
    let mut drafts = vec![c::draft("personal_debt", &id, "deleted", Map::new())];
    for leg in schema::select(conn, "transaction", "WHERE link_id = ?1 ORDER BY id", vec![id.clone().into()])? {
        if DEBT_ROLES.contains(&leg["link_role"].as_str().unwrap_or("")) {
            drafts.push(c::draft("transaction", leg["id"].as_str().unwrap_or_default(), "deleted", Map::new()));
        }
    }
    Ok(drafts)
}

/// A debt leg can only be removed through its debt, so the debt and the ledger never disagree.
pub fn guard_leg_delete(leg: &Obj) -> DomainResult<()> {
    if DEBT_ROLES.contains(&leg.get("link_role").and_then(Value::as_str).unwrap_or("")) {
        return Err(DomainError::conflict(
            "this transaction belongs to a personal debt; delete or correct the debt instead",
        ));
    }
    Ok(())
}

/// Duplicate-safe repeats (see `accounting::replay_of`).
pub fn replay_of(conn: &Connection, kind: &str, payload: &Value) -> DomainResult<Option<(String, String)>> {
    let Some(map) = payload.as_object() else { return Ok(None) };
    let text = |k: &str| map.get(k).and_then(Value::as_str).map(str::trim).unwrap_or("");
    let int = |k: &str| map.get(k).and_then(Value::as_i64);
    let differs = |what: String| {
        DomainError::conflict(format!("{what} is already recorded with different facts; nothing was changed"))
    };
    match kind {
        "personal_debt.record" => {
            let id = text("id");
            if id.is_empty() {
                return Ok(None);
            }
            let Some(existing) = schema::load(conn, "personal_debt", id)? else { return Ok(None) };
            let same = existing["counterparty"].as_str() == Some(text("counterparty"))
                && existing["direction"].as_str() == Some(text("direction"))
                && existing["principal_minor"].as_i64() == int("amount_minor")
                && existing["date"].as_str() == Some(text("date"));
            if same {
                return Ok(Some(("personal_debt".to_string(), id.to_string())));
            }
            Err(differs(format!("personal debt {id}")))
        }
        "personal_debt.settle" => {
            let (id, reference) = (text("id"), text("external_ref"));
            if id.is_empty() || reference.is_empty() {
                return Ok(None);
            }
            let Some(existing) = schema::load(conn, "personal_debt", id)? else { return Ok(None) };
            let items = existing.get("settlements").and_then(Value::as_array).cloned().unwrap_or_default();
            let Some(seen) = items.iter().find(|i| i["external_ref"].as_str() == Some(reference)) else {
                return Ok(None);
            };
            if seen["amount_minor"].as_i64() == int("amount_minor") && seen["date"].as_str() == Some(text("date")) {
                return Ok(Some(("personal_debt".to_string(), id.to_string())));
            }
            Err(differs(format!("settlement {reference:?}")))
        }
        _ => Ok(None),
    }
}

// ---------------------------------------------------------------------------------------------
// Queries

pub fn query(conn: &Connection, name: &str, params: &Value) -> Option<DomainResult<QueryOut>> {
    Some(match name {
        "list_personal_debts" => list_personal_debts(conn, params),
        "earnings_summary" => earnings_summary(conn, params),
        "net_position" => net_position(conn, params),
        _ => return None,
    })
}

fn param_str<'a>(params: &'a Value, key: &str) -> Option<&'a str> {
    params.get(key).and_then(Value::as_str).filter(|s| !s.is_empty())
}

fn debt_view(s: &Obj, as_of: Date) -> Value {
    let left = outstanding(s);
    let overdue =
        left > 0 && s.get("due_date").and_then(Value::as_str).and_then(Date::parse).map(|d| d < as_of).unwrap_or(false);
    json!({
        "id": s["id"], "counterparty": s["counterparty"], "direction": s["direction"],
        "currency": s["currency"], "date": s["date"], "due_date": s["due_date"], "account_id": s["account_id"],
        "principal_minor": s["principal_minor"], "settled_minor": settled_total(s), "outstanding_minor": left,
        "status": if left == 0 { "settled" } else { "open" }, "overdue": overdue,
        "settlements": s["settlements"], "notes": s["notes"],
    })
}

/// Debts with people, newest first. `direction` filters to `lent` or `borrowed`; settled debts are left out
/// unless `include_settled` is true.
fn list_personal_debts(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let as_of = queries::as_of(params)?;
    let direction = param_str(params, "direction");
    if let Some(d) = direction {
        if !DIRECTIONS.contains(&d) {
            return Err(DomainError::validation("direction", "must be lent or borrowed"));
        }
    }
    let include_settled = params.get("include_settled").and_then(Value::as_bool).unwrap_or(false);
    let mut rows = Vec::new();
    let mut ids = Vec::new();
    for s in schema::select(conn, "personal_debt", "ORDER BY date DESC, id", vec![])? {
        if direction.map(|d| s["direction"].as_str() != Some(d)).unwrap_or(false) {
            continue;
        }
        if !include_settled && outstanding(&s) == 0 {
            continue;
        }
        ids.push(s["id"].as_str().unwrap_or_default().to_string());
        rows.push(debt_view(&s, as_of));
    }
    Ok(QueryOut { rows: Value::Array(rows), source_ids: ids })
}

fn range(params: &Value) -> DomainResult<(Date, Date)> {
    let (from, to) = match (param_str(params, "from"), param_str(params, "to")) {
        (Some(f), Some(t)) => (
            Date::parse(f).ok_or_else(|| DomainError::validation("from", "must be YYYY-MM-DD"))?,
            Date::parse(t).ok_or_else(|| DomainError::validation("to", "must be YYYY-MM-DD"))?,
        ),
        _ => queries::resolve_period(param_str(params, "period").unwrap_or("this_month"), queries::as_of(params)?)?,
    };
    if from > to {
        return Err(DomainError::validation("from", "after to"));
    }
    Ok((from, to))
}

/// Income actually received in a period, per currency and category, using the same rules as
/// `period_summary` (moves, debt legs and refunds are not income), plus income still expected before the
/// period ends from active recurring income (`bill` with kind `income`).
fn earnings_summary(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let (from, to) = range(params)?;
    let as_of = queries::as_of(params)?;
    let mut stmt = conn.prepare(
        "SELECT t.id, t.currency, t.amount_minor, t.link_role, c.kind, c.name, a.kind
           FROM transactions t
           LEFT JOIN categories c ON c.id = t.category_id
           LEFT JOIN accounts a ON a.id = t.account_id
          WHERE t.date >= ?1 AND t.date <= ?2 AND t.amount_minor > 0
          ORDER BY t.date, t.id",
    )?;
    let mut rows = stmt.query([from.to_iso(), to.to_iso()])?;
    #[derive(Default)]
    struct Earned {
        total: i64,
        by_category: BTreeMap<String, i64>,
        expected: i64,
        expected_items: Vec<Value>,
    }
    let mut by: BTreeMap<String, Earned> = BTreeMap::new();
    let mut source_ids = Vec::new();
    while let Some(r) = rows.next()? {
        let role: Option<String> = r.get(3)?;
        let category_kind: Option<String> = r.get(4)?;
        let account_kind: Option<String> = r.get(6)?;
        let neutral = role.as_deref().map(|x| NEUTRAL_ROLES.contains(&x)).unwrap_or(false);
        let refund = matches!(category_kind.as_deref(), Some("expense"))
            || (category_kind.is_none() && account_kind.as_deref() == Some("credit"));
        if neutral || refund || category_kind.as_deref() == Some("transfer") {
            continue;
        }
        let currency: String = r.get(1)?;
        let amount: i64 = r.get(2)?;
        let category: Option<String> = r.get(5)?;
        let e = by.entry(currency).or_default();
        e.total += amount;
        *e.by_category.entry(category.unwrap_or_else(|| "Uncategorized".to_string())).or_default() += amount;
        source_ids.push(r.get(0)?);
    }
    drop(rows);
    drop(stmt);
    // Recurring income still to come in the period (from today, or the period start if that is later).
    let start = if as_of > from { as_of } else { from };
    for bill in schema::select(conn, "bill", "WHERE active = 1 AND kind = 'income' ORDER BY due_date, id", vec![])? {
        let Some(mut due) = bill["due_date"].as_str().and_then(Date::parse) else { continue };
        let anchor = bill["anchor_day"].as_i64().unwrap_or(i64::from(due.day)) as u32;
        let recurrence = bill["recurrence"].as_str().unwrap_or("once").to_string();
        let amount = bill["amount_minor"].as_i64().unwrap_or(0);
        let currency = bill["currency"].as_str().unwrap_or_default().to_string();
        let mut guard = 0;
        while due <= to && guard < 400 {
            if due >= start {
                let e = by.entry(currency.clone()).or_default();
                e.expected += amount;
                e.expected_items.push(json!({"bill_id": bill["id"], "name": bill["name"], "date": due.to_iso(),
                    "amount_minor": amount}));
            }
            match c::next_due(due, anchor, &recurrence) {
                Some(next) => due = next,
                None => break,
            }
            guard += 1;
        }
        source_ids.push(bill["id"].as_str().unwrap_or_default().to_string());
    }
    let out: Vec<Value> = by
        .into_iter()
        .map(|(currency, e)| {
            let categories: Vec<Value> = e
                .by_category
                .into_iter()
                .map(|(name, amount)| json!({"category": name, "amount_minor": amount}))
                .collect();
            json!({
                "currency": currency, "from": from.to_iso(), "to": to.to_iso(), "as_of": as_of.to_iso(),
                "received_minor": e.total, "by_category": categories,
                "expected_minor": e.expected, "expected": e.expected_items,
                "assumptions": [
                    "money moved between your own accounts, loans and money from people settling debts is not income",
                    "money in with an expense category, or uncategorized money in on a credit account, is a refund",
                    "expected income comes only from active recurring income you entered; nothing is estimated",
                    "each currency is totalled separately; nothing is converted",
                ],
            })
        })
        .collect();
    Ok(QueryOut { rows: Value::Array(out), source_ids })
}

/// Everything the owner has and owes, per currency: account balances, card and loan balances, and money
/// between the owner and other people.
fn net_position(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let as_of = queries::as_of(params)?;
    #[derive(Default)]
    struct Pos {
        accounts: i64,
        cards_owed: i64,
        loans_owed: i64,
        owed_to_me: i64,
        i_owe: i64,
        debts: Vec<Value>,
        receivables: Vec<Value>,
    }
    let mut by: BTreeMap<String, Pos> = BTreeMap::new();
    let mut source_ids = Vec::new();
    for b in queries::balances(conn, Some(as_of), false)? {
        let kind = b.account["kind"].as_str().unwrap_or("");
        let currency = b.account["currency"].as_str().unwrap_or_default().to_string();
        let p = by.entry(currency.clone()).or_default();
        let owed = (-b.balance_minor).max(0);
        match kind {
            "credit" | "loan" => {
                if kind == "credit" {
                    p.cards_owed += owed;
                    p.accounts += b.balance_minor.max(0);
                } else {
                    p.loans_owed += owed;
                }
                if owed > 0 {
                    p.debts.push(json!({"type": kind, "id": b.account["id"], "name": b.account["name"],
                        "owed_minor": owed, "due_day": b.account.get("due_day").cloned().unwrap_or(Value::Null)}));
                }
            }
            _ => p.accounts += b.balance_minor,
        }
        source_ids.push(b.account["id"].as_str().unwrap_or_default().to_string());
    }
    for s in schema::select(conn, "personal_debt", "WHERE date <= ?1 ORDER BY date, id", vec![as_of.to_iso().into()])? {
        // Only settlements made by `as_of` count.
        let settled: i64 = s
            .get("settlements")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter(|i| i["date"].as_str().map(|d| d <= as_of.to_iso().as_str()).unwrap_or(false))
                    .filter_map(|i| i["amount_minor"].as_i64())
                    .sum()
            })
            .unwrap_or(0);
        let left = s["principal_minor"].as_i64().unwrap_or(0) - settled;
        if left <= 0 {
            continue;
        }
        let p = by.entry(s["currency"].as_str().unwrap_or_default().to_string()).or_default();
        let item = json!({"type": "person", "id": s["id"], "name": s["counterparty"], "owed_minor": left,
            "due_date": s["due_date"]});
        if s["direction"].as_str() == Some("lent") {
            p.owed_to_me += left;
            p.receivables.push(item);
        } else {
            p.i_owe += left;
            p.debts.push(item);
        }
        source_ids.push(s["id"].as_str().unwrap_or_default().to_string());
    }
    let out: Vec<Value> = by
        .into_iter()
        .map(|(currency, p)| {
            let total_debt = p.cards_owed + p.loans_owed + p.i_owe;
            json!({
                "currency": currency, "as_of": as_of.to_iso(),
                "accounts_minor": p.accounts, "owed_to_me_minor": p.owed_to_me,
                "cards_owed_minor": p.cards_owed, "loans_owed_minor": p.loans_owed, "i_owe_people_minor": p.i_owe,
                "total_debt_minor": total_debt,
                "net_minor": p.accounts + p.owed_to_me - total_debt,
                "debts": p.debts, "receivables": p.receivables,
                "assumptions": [
                    "balances are what REVA has recorded; check them against statements with reconciliation",
                    "loan amounts are outstanding principal; future interest is not included",
                    "each currency is totalled separately; nothing is converted",
                ],
            })
        })
        .collect();
    Ok(QueryOut { rows: Value::Array(out), source_ids })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lending_takes_money_out_and_its_settlement_brings_it_back() {
        assert_eq!(signed("lent", 500, false), -500);
        assert_eq!(signed("lent", 500, true), 500);
        assert_eq!(signed("borrowed", 500, false), 500);
        assert_eq!(signed("borrowed", 500, true), -500);
    }

    #[test]
    fn debt_roles_are_neutral() {
        for role in DEBT_ROLES {
            assert!(NEUTRAL_ROLES.contains(role), "{role}");
        }
    }
}
