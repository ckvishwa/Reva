//! Read-only Finance queries. All of them are pure functions of the projection tables and
//! explicit parameters; "today" is only used when the caller omits `as_of`.

use std::collections::BTreeMap;

use rusqlite::types::Value as SqlValue;
use rusqlite::Connection;
use serde_json::{json, Map, Value};

use super::schema;
use crate::civil::{self, Date};
use crate::error::{DomainError, DomainResult};
use crate::events;

pub struct QueryOut {
    pub rows: Value,
    pub source_ids: Vec<String>,
}

fn opt_str<'a>(params: &'a Value, key: &str) -> Option<&'a str> {
    params.get(key).and_then(Value::as_str).filter(|s| !s.is_empty())
}

fn opt_i64(params: &Value, key: &str) -> DomainResult<Option<i64>> {
    match params.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => v.as_i64().map(Some).ok_or_else(|| DomainError::validation(key, "must be an integer")),
    }
}

pub fn as_of(params: &Value) -> DomainResult<Date> {
    match opt_str(params, "as_of") {
        None => Ok(civil::today()),
        Some(text) => Date::parse(text).ok_or_else(|| DomainError::validation("as_of", "must be YYYY-MM-DD")),
    }
}

/// Resolve a period spec to an inclusive `(from, to)` date range.
pub fn resolve_period(spec: &str, as_of: Date) -> DomainResult<(Date, Date)> {
    let bad = || DomainError::validation("period", format!("unrecognised period {spec:?}"));
    match spec {
        "this_month" => return Ok((as_of.first_of_month(), as_of.last_of_month())),
        "last_month" => {
            let prev = as_of.first_of_month().add_months(-1);
            return Ok((prev, prev.last_of_month()));
        }
        "this_year" => {
            return Ok((Date::new(as_of.year, 1, 1).ok_or_else(bad)?, Date::new(as_of.year, 12, 31).ok_or_else(bad)?))
        }
        "last_year" => {
            return Ok((
                Date::new(as_of.year - 1, 1, 1).ok_or_else(bad)?,
                Date::new(as_of.year - 1, 12, 31).ok_or_else(bad)?,
            ))
        }
        "last_7_days" => return Ok((as_of.add_days(-6), as_of)),
        "last_30_days" => return Ok((as_of.add_days(-29), as_of)),
        _ => {}
    }
    if let Some((from, to)) = spec.split_once("..") {
        let from = Date::parse(from).ok_or_else(bad)?;
        let to = Date::parse(to).ok_or_else(bad)?;
        if to < from {
            return Err(DomainError::validation("period", "end is before start"));
        }
        return Ok((from, to));
    }
    if let Some(day) = Date::parse(spec) {
        return Ok((day, day));
    }
    let parts: Vec<&str> = spec.split('-').collect();
    match parts.as_slice() {
        [y] if y.len() == 4 => {
            let year: i32 = y.parse().map_err(|_| bad())?;
            Ok((Date::new(year, 1, 1).ok_or_else(bad)?, Date::new(year, 12, 31).ok_or_else(bad)?))
        }
        [y, m] if y.len() == 4 && m.len() == 2 => {
            let year: i32 = y.parse().map_err(|_| bad())?;
            let month: u32 = m.parse().map_err(|_| bad())?;
            let first = Date::new(year, month, 1).ok_or_else(bad)?;
            Ok((first, first.last_of_month()))
        }
        _ => Err(bad()),
    }
}

fn text(v: &str) -> SqlValue {
    SqlValue::Text(v.to_string())
}

pub fn run(conn: &Connection, name: &str, params: &Value) -> DomainResult<QueryOut> {
    match name {
        "spend_by_category" => spend_by_category(conn, params),
        "cashflow" => cashflow(conn, params),
        "budget_status" => budget_status(conn, params),
        "upcoming_bills" => upcoming_bills(conn, params),
        "list_transactions" => list_transactions(conn, params),
        "account_balances" => account_balances(conn, params),
        "list_accounts" => list_all(conn, "account", "ORDER BY name COLLATE NOCASE, id"),
        "list_categories" => list_all(conn, "category", "ORDER BY name COLLATE NOCASE, id"),
        "list_budgets" => list_all(conn, "budget", "ORDER BY category_id, id"),
        "list_bills" => list_all(conn, "bill", "ORDER BY due_date, name COLLATE NOCASE, id"),
        "list_networth_snapshots" => list_all(conn, "networth_snapshot", "ORDER BY as_of, id"),
        "get" => get(conn, params),
        "resolve_category" => resolve_category_query(conn, params),
        "conflicts" => conflicts(conn),
        other => Err(DomainError::validation("query", format!("unknown finance query {other:?}"))),
    }
}

fn list_all(conn: &Connection, aggregate_type: &str, tail: &str) -> DomainResult<QueryOut> {
    let rows = schema::select(conn, aggregate_type, tail, vec![])?;
    let ids = rows.iter().filter_map(|r| r.get("id").and_then(Value::as_str).map(str::to_string)).collect();
    Ok(QueryOut { rows: Value::Array(rows.into_iter().map(Value::Object).collect()), source_ids: ids })
}

fn get(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let aggregate_type =
        opt_str(params, "aggregate_type").ok_or_else(|| DomainError::validation("aggregate_type", "required"))?;
    let id = opt_str(params, "id").ok_or_else(|| DomainError::validation("id", "required"))?;
    if events::is_tombstoned(conn, aggregate_type, id)? {
        return Err(DomainError::Deleted { detail: format!("{aggregate_type} {id}") });
    }
    match schema::load(conn, aggregate_type, id)? {
        Some(row) => Ok(QueryOut { rows: json!([row]), source_ids: vec![id.to_string()] }),
        None => Err(DomainError::not_found(format!("{aggregate_type} {id}"))),
    }
}

/// Category id for a name, alias or id. Names win over aliases; ties go to the smallest id.
pub fn resolve_category(conn: &Connection, text_in: &str) -> DomainResult<Option<String>> {
    let wanted = text_in.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase();
    if wanted.is_empty() {
        return Ok(None);
    }
    let by_id = schema::select(conn, "category", "WHERE id = ?1", vec![text(text_in.trim())])?;
    if let Some(row) = by_id.first() {
        return Ok(row.get("id").and_then(Value::as_str).map(str::to_string));
    }
    let by_name = schema::select(conn, "category", "WHERE lower(name) = ?1 ORDER BY id LIMIT 1", vec![text(&wanted)])?;
    if let Some(row) = by_name.first() {
        return Ok(row.get("id").and_then(Value::as_str).map(str::to_string));
    }
    let id: Option<String> = conn
        .query_row(
            "SELECT category_id FROM category_aliases WHERE alias = ?1 ORDER BY category_id LIMIT 1",
            [&wanted],
            |r| r.get(0),
        )
        .ok();
    Ok(id)
}

fn resolve_category_query(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let q = opt_str(params, "text").ok_or_else(|| DomainError::validation("text", "required"))?;
    let id = resolve_category(conn, q)?;
    Ok(QueryOut { rows: json!([{ "text": q, "category_id": id }]), source_ids: id.into_iter().collect() })
}

fn conflicts(conn: &Connection) -> DomainResult<QueryOut> {
    let mut stmt = conn.prepare(
        "SELECT id, aggregate_type, aggregate_id, field, local_event_id, remote_event_id, local_value, remote_value, detected_at, resolved
           FROM conflicts ORDER BY id",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(json!({
            "id": r.get::<_, i64>(0)?, "aggregate_type": r.get::<_, String>(1)?, "aggregate_id": r.get::<_, String>(2)?,
            "field": r.get::<_, String>(3)?, "local_event_id": r.get::<_, String>(4)?, "remote_event_id": r.get::<_, String>(5)?,
            "local_value": r.get::<_, String>(6)?, "remote_value": r.get::<_, String>(7)?,
            "detected_at": r.get::<_, String>(8)?, "resolved": r.get::<_, i64>(9)? != 0,
        }))
    })?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row?);
    }
    let ids = out.iter().filter_map(|v| v.get("aggregate_id").and_then(Value::as_str).map(str::to_string)).collect();
    Ok(QueryOut { rows: Value::Array(out), source_ids: ids })
}

// ---------------------------------------------------------------------------------------------
// Spending

fn spend_by_category(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let period = opt_str(params, "period").ok_or_else(|| DomainError::validation("period", "required"))?;
    let (from, to) = resolve_period(period, as_of(params)?)?;
    let currency = opt_str(params, "currency");

    let mut sql = String::from(
        "SELECT t.id, t.category_id, COALESCE(c.name, 'Uncategorized'), t.currency, -t.amount_minor
           FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
          WHERE t.date >= ?1 AND t.date <= ?2 AND t.amount_minor < 0
            AND (c.id IS NULL OR c.kind = 'expense')",
    );
    let mut args = vec![text(&from.to_iso()), text(&to.to_iso())];
    if let Some(code) = currency {
        sql.push_str(" AND t.currency = ?3");
        args.push(text(code));
    }
    sql.push_str(" ORDER BY t.date, t.id");
    let mut stmt = conn.prepare(&sql)?;
    let mut rows = stmt.query(rusqlite::params_from_iter(args))?;

    // (currency, category_id) -> (name, spent, count)
    let mut groups: BTreeMap<(String, Option<String>), (String, i64, i64)> = BTreeMap::new();
    let mut source_ids = Vec::new();
    while let Some(r) = rows.next()? {
        let id: String = r.get(0)?;
        let category_id: Option<String> = r.get(1)?;
        let name: String = r.get(2)?;
        let cur: String = r.get(3)?;
        let spent: i64 = r.get(4)?;
        let entry = groups.entry((cur, category_id)).or_insert((name, 0, 0));
        entry.1 += spent;
        entry.2 += 1;
        source_ids.push(id);
    }
    let mut out: Vec<Value> = groups
        .into_iter()
        .map(|((cur, category_id), (name, spent, count))| {
            json!({ "category_id": category_id, "category": name, "currency": cur, "spent_minor": spent, "transactions": count })
        })
        .collect();
    out.sort_by(|a, b| {
        let key =
            |v: &Value| (v["currency"].as_str().unwrap_or("").to_string(), -v["spent_minor"].as_i64().unwrap_or(0));
        key(a).cmp(&key(b)).then_with(|| a["category"].as_str().cmp(&b["category"].as_str()))
    });
    Ok(QueryOut { rows: Value::Array(out), source_ids })
}

fn cashflow(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let period = opt_str(params, "period").ok_or_else(|| DomainError::validation("period", "required"))?;
    let (from, to) = resolve_period(period, as_of(params)?)?;
    let mut stmt = conn.prepare(
        "SELECT t.id, t.currency, t.amount_minor
           FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
          WHERE t.date >= ?1 AND t.date <= ?2 AND (c.id IS NULL OR c.kind != 'transfer')
          ORDER BY t.date, t.id",
    )?;
    let mut rows = stmt.query([from.to_iso(), to.to_iso()])?;
    let mut totals: BTreeMap<String, (i64, i64)> = BTreeMap::new();
    let mut source_ids = Vec::new();
    while let Some(r) = rows.next()? {
        let id: String = r.get(0)?;
        let cur: String = r.get(1)?;
        let amount: i64 = r.get(2)?;
        let entry = totals.entry(cur).or_insert((0, 0));
        if amount >= 0 {
            entry.0 += amount;
        } else {
            entry.1 += -amount;
        }
        source_ids.push(id);
    }
    let out: Vec<Value> = totals
        .into_iter()
        .map(|(cur, (income, expense))| {
            json!({ "currency": cur, "income_minor": income, "expense_minor": expense, "net_minor": income - expense,
                    "from": from.to_iso(), "to": to.to_iso() })
        })
        .collect();
    Ok(QueryOut { rows: Value::Array(out), source_ids })
}

// ---------------------------------------------------------------------------------------------
// Budgets

fn budget_status(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let today = as_of(params)?;
    let month_first = match opt_str(params, "month") {
        None => today.first_of_month(),
        Some(m) => resolve_period(m, today)?.0.first_of_month(),
    };
    let month_last = month_first.last_of_month();
    let month_key = format!("{:04}-{:02}", month_first.year, month_first.month);
    let days_left =
        if today >= month_first && today <= month_last { i64::from(month_last.day - today.day) + 1 } else { 0 };

    let budgets =
        schema::select(conn, "budget", "WHERE start_month <= ?1 ORDER BY category_id, id", vec![text(&month_key)])?;
    let mut out = Vec::new();
    let mut source_ids = Vec::new();
    for budget in budgets {
        let category_id = budget["category_id"].as_str().unwrap_or("").to_string();
        let currency = budget["currency"].as_str().unwrap_or("").to_string();
        let amount = budget["amount_minor"].as_i64().unwrap_or(0);
        let name: Option<String> =
            conn.query_row("SELECT name FROM categories WHERE id = ?1", [&category_id], |r| r.get(0)).ok();

        let mut stmt = conn.prepare(
            "SELECT t.id, -t.amount_minor FROM transactions t
              WHERE t.date >= ?1 AND t.date <= ?2 AND t.amount_minor < 0 AND t.currency = ?3
                AND (t.category_id = ?4 OR t.category_id IN (SELECT id FROM categories WHERE parent_id = ?4))
              ORDER BY t.date, t.id",
        )?;
        let mut rows =
            stmt.query([month_first.to_iso(), month_last.to_iso(), currency.clone(), category_id.clone()])?;
        let mut spent = 0_i64;
        while let Some(r) = rows.next()? {
            source_ids.push(r.get::<_, String>(0)?);
            spent += r.get::<_, i64>(1)?;
        }
        let remaining = amount - spent;
        let used_bp = if amount > 0 { (i128::from(spent) * 10_000 / i128::from(amount)) as i64 } else { 0 };
        let allowance = if remaining > 0 && days_left > 0 { remaining / days_left } else { 0 };
        source_ids.push(budget["id"].as_str().unwrap_or("").to_string());
        out.push(json!({
            "budget_id": budget["id"], "category_id": category_id, "category": name, "currency": currency,
            "month": month_key, "budget_minor": amount, "spent_minor": spent, "remaining_minor": remaining,
            "used_basis_points": used_bp, "over_budget": spent > amount, "days_left": days_left,
            "daily_allowance_minor": allowance,
        }));
    }
    Ok(QueryOut { rows: Value::Array(out), source_ids })
}

// ---------------------------------------------------------------------------------------------
// Bills

fn upcoming_bills(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let today = as_of(params)?;
    let days = opt_i64(params, "days")?.unwrap_or(30);
    if !(0..=3660).contains(&days) {
        return Err(DomainError::validation("days", "must be between 0 and 3660"));
    }
    let horizon = today.add_days(days);
    let bills = schema::select(
        conn,
        "bill",
        "WHERE active = 1 AND due_date <= ?1 ORDER BY due_date, name COLLATE NOCASE, id",
        vec![text(&horizon.to_iso())],
    )?;
    let mut out = Vec::new();
    let mut ids = Vec::new();
    for bill in bills {
        let due = Date::parse(bill["due_date"].as_str().unwrap_or("")).unwrap_or(today);
        let until = due.to_days() - today.to_days();
        ids.push(bill["id"].as_str().unwrap_or("").to_string());
        let mut row = bill.clone();
        row.insert("days_until".to_string(), Value::from(until));
        row.insert("overdue".to_string(), Value::Bool(until < 0));
        out.push(Value::Object(row));
    }
    Ok(QueryOut { rows: Value::Array(out), source_ids: ids })
}

// ---------------------------------------------------------------------------------------------
// Transactions and balances

fn like_escape(s: &str) -> String {
    s.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_")
}

fn list_transactions(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let mut clauses: Vec<String> = Vec::new();
    let mut args: Vec<SqlValue> = Vec::new();
    if let Some(v) = opt_str(params, "account_id") {
        args.push(text(v));
        clauses.push(format!("account_id = ?{}", args.len()));
    }
    if let Some(v) = opt_str(params, "category_id") {
        args.push(text(v));
        clauses.push(format!("category_id = ?{}", args.len()));
    }
    if let Some(v) = opt_str(params, "from") {
        let d = Date::parse(v).ok_or_else(|| DomainError::validation("from", "must be YYYY-MM-DD"))?;
        args.push(text(&d.to_iso()));
        clauses.push(format!("date >= ?{}", args.len()));
    }
    if let Some(v) = opt_str(params, "to") {
        let d = Date::parse(v).ok_or_else(|| DomainError::validation("to", "must be YYYY-MM-DD"))?;
        args.push(text(&d.to_iso()));
        clauses.push(format!("date <= ?{}", args.len()));
    }
    if let Some(v) = opt_str(params, "q") {
        let pattern = format!("%{}%", like_escape(&v.to_lowercase()));
        args.push(text(&pattern));
        let n = args.len();
        clauses.push(format!(
            "(lower(description) LIKE ?{n} ESCAPE '\\' OR lower(COALESCE(merchant, '')) LIKE ?{n} ESCAPE '\\' OR lower(COALESCE(notes, '')) LIKE ?{n} ESCAPE '\\')"
        ));
    }
    if let Some(v) = opt_i64(params, "min_amount_minor")? {
        args.push(SqlValue::Integer(v));
        clauses.push(format!("amount_minor >= ?{}", args.len()));
    }
    if let Some(v) = opt_i64(params, "max_amount_minor")? {
        args.push(SqlValue::Integer(v));
        clauses.push(format!("amount_minor <= ?{}", args.len()));
    }
    let limit = opt_i64(params, "limit")?.unwrap_or(100).clamp(1, 1000);
    let offset = opt_i64(params, "offset")?.unwrap_or(0).max(0);
    let mut tail = String::new();
    if !clauses.is_empty() {
        tail.push_str(&format!("WHERE {} ", clauses.join(" AND ")));
    }
    tail.push_str(&format!("ORDER BY date DESC, created_at DESC, id LIMIT {limit} OFFSET {offset}"));
    let rows = schema::select(conn, "transaction", &tail, args)?;
    let ids = rows.iter().filter_map(|r| r["id"].as_str().map(str::to_string)).collect();
    Ok(QueryOut { rows: Value::Array(rows.into_iter().map(Value::Object).collect()), source_ids: ids })
}

pub struct Balance {
    pub account: Map<String, Value>,
    pub balance_minor: i64,
}

pub fn balances(conn: &Connection, as_of: Option<Date>, include_archived: bool) -> DomainResult<Vec<Balance>> {
    let tail = if include_archived {
        "ORDER BY name COLLATE NOCASE, id"
    } else {
        "WHERE archived = 0 ORDER BY name COLLATE NOCASE, id"
    };
    let accounts = schema::select(conn, "account", tail, vec![])?;
    let mut out = Vec::new();
    for account in accounts {
        let id = account["id"].as_str().unwrap_or("").to_string();
        let opening = account["opening_balance_minor"].as_i64().unwrap_or(0);
        let sum: i64 = match as_of {
            Some(d) => conn.query_row(
                "SELECT COALESCE(SUM(amount_minor), 0) FROM transactions WHERE account_id = ?1 AND date <= ?2",
                [id.clone(), d.to_iso()],
                |r| r.get(0),
            )?,
            None => conn.query_row(
                "SELECT COALESCE(SUM(amount_minor), 0) FROM transactions WHERE account_id = ?1",
                [id.clone()],
                |r| r.get(0),
            )?,
        };
        out.push(Balance { account, balance_minor: opening + sum });
    }
    Ok(out)
}

fn account_balances(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let date = match opt_str(params, "as_of") {
        None => None,
        Some(_) => Some(as_of(params)?),
    };
    let include_archived = params.get("include_archived").and_then(Value::as_bool).unwrap_or(false);
    let list = balances(conn, date, include_archived)?;
    let ids = list.iter().filter_map(|b| b.account["id"].as_str().map(str::to_string)).collect();
    let rows = list
        .into_iter()
        .map(|b| {
            json!({
                "account_id": b.account["id"], "name": b.account["name"], "kind": b.account["kind"],
                "currency": b.account["currency"], "archived": b.account["archived"],
                "balance_minor": b.balance_minor, "as_of": date.map(Date::to_iso),
            })
        })
        .collect();
    Ok(QueryOut { rows: Value::Array(rows), source_ids: ids })
}

/// Net worth per currency from current balances of non-archived accounts.
pub fn networth_by_currency(conn: &Connection, as_of: Date) -> DomainResult<Value> {
    let mut by: BTreeMap<String, (i64, i64)> = BTreeMap::new();
    for b in balances(conn, Some(as_of), false)? {
        let cur = b.account["currency"].as_str().unwrap_or("").to_string();
        let entry = by.entry(cur).or_insert((0, 0));
        if b.balance_minor >= 0 {
            entry.0 += b.balance_minor;
        } else {
            entry.1 += -b.balance_minor;
        }
    }
    let mut map = Map::new();
    for (cur, (assets, liabilities)) in by {
        map.insert(
            cur,
            json!({ "assets_minor": assets, "liabilities_minor": liabilities, "net_minor": assets - liabilities }),
        );
    }
    Ok(Value::Object(map))
}
