//! FIN-3: accounting records on top of the Finance aggregates.
//!
//! Everything here *records* what already happened between the owner's own accounts (ARD-700 §3): an
//! internal move between two accounts, a loan installment split into principal and interest, a transaction
//! confirmed from an outside source with a provenance key, and a statement reconciliation. Nothing moves
//! money, talks to a bank or converts currency.
//!
//! Accounting rules the reports below rely on:
//! - A card purchase is spending once, on the card account. Repaying the card is an internal move
//!   (checking -> card) and is never spending or income.
//! - An internal move is never income or spending.
//! - A loan installment is a principal move (not spending) plus an interest leg (spending).
//! - A refund (money in with an expense category, or uncategorized money in on a credit account) reduces
//!   spending; it is not income.

use std::collections::BTreeMap;

use rusqlite::{Connection, OptionalExtension};
use serde_json::{json, Map, Value};

use super::commands::{self as c, NewTransaction};
use super::queries::{self, QueryOut};
use super::schema;
use crate::civil::Date;
use crate::error::{DomainError, DomainResult};
use crate::events::EventDraft;

type Obj = Map<String, Value>;

pub const COMMANDS: &[&str] =
    &["internal_move.record", "loan_installment.record", "transaction.ingest", "reconciliation.record"];

/// Link roles of transaction legs that move value between the owner's accounts and are therefore never
/// spending or income. The `interest` leg of a loan installment is spending and is not listed.
pub const NEUTRAL_ROLES: &[&str] = &["move_out", "move_in", "principal_out", "principal_in"];

/// SQL condition (over alias `t`) that keeps only legs that can count as spending or income.
pub const COUNTED_LEG: &str = "(t.link_role IS NULL OR t.link_role = 'interest')";

const INGEST_SOURCES: &[&str] = &["email", "import"];

// ---------------------------------------------------------------------------------------------
// Account terms (credit cards and loans)

pub const TERM_FIELDS: &[&str] = &[
    "credit_limit_minor",
    "statement_day",
    "due_day",
    "apr_bp",
    "loan_principal_minor",
    "loan_term_months",
    "loan_first_due",
];

/// Copy any term fields present in `map` into `s`. An explicit null clears a term.
pub fn apply_terms(map: &Obj, s: &mut Obj) -> DomainResult<()> {
    for (key, lo, hi) in [
        ("credit_limit_minor", 0, super::money::MAX_ABS_MINOR),
        ("loan_principal_minor", 1, super::money::MAX_ABS_MINOR),
        ("statement_day", 1, 31),
        ("due_day", 1, 31),
        ("apr_bp", 0, 100_000),
        ("loan_term_months", 1, 600),
    ] {
        if !map.contains_key(key) {
            continue;
        }
        match c::int_field(map, key, false)? {
            None => c::set(s, key, Value::Null),
            Some(v) if v < lo || v > hi => {
                return Err(DomainError::validation(key, format!("must be between {lo} and {hi}")));
            }
            Some(v) => c::set(s, key, v),
        }
    }
    if map.contains_key("loan_first_due") {
        let value =
            c::date_field(map, "loan_first_due", false)?.map(|d| Value::from(d.to_iso())).unwrap_or(Value::Null);
        c::set(s, "loan_first_due", value);
    }
    Ok(())
}

/// Terms must match the account kind: card terms on credit accounts, loan terms on loans, a rate on either.
pub fn check_terms(s: &Obj) -> DomainResult<()> {
    let kind = s.get("kind").and_then(Value::as_str).unwrap_or("");
    let has = |k: &str| s.get(k).map(|v| !v.is_null()).unwrap_or(false);
    for key in ["credit_limit_minor", "statement_day", "due_day"] {
        if has(key) && kind != "credit" {
            return Err(DomainError::validation(key, "only credit accounts have this term"));
        }
    }
    for key in ["loan_principal_minor", "loan_term_months", "loan_first_due"] {
        if has(key) && kind != "loan" {
            return Err(DomainError::validation(key, "only loan accounts have this term"));
        }
    }
    if has("apr_bp") && kind != "credit" && kind != "loan" {
        return Err(DomainError::validation("apr_bp", "only credit and loan accounts have a rate"));
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------------
// Commands

pub fn handle(conn: &Connection, kind: &str, payload: &Value, now: &str) -> Option<DomainResult<Vec<EventDraft>>> {
    Some(match kind {
        "internal_move.record" => internal_move(conn, payload, now),
        "loan_installment.record" => loan_installment(conn, payload, now),
        "transaction.ingest" => ingest(conn, payload, now),
        "reconciliation.record" => reconciliation(conn, payload, now),
        _ => return None,
    })
}

fn link_id_field(map: &Obj) -> DomainResult<String> {
    let id = c::id_of(map, "id")?;
    if id.len() > 56 {
        return Err(DomainError::validation("id", "at most 56 characters (legs add a suffix)"));
    }
    Ok(id)
}

fn external_ref_field(map: &Obj, required: bool) -> DomainResult<Option<String>> {
    c::text_field(map, "external_ref", 200, required)
}

fn positive_amount(map: &Obj) -> DomainResult<i64> {
    let amount = c::int_field(map, "amount_minor", true)?.unwrap_or(0);
    if amount <= 0 {
        return Err(DomainError::validation("amount_minor", "must be greater than zero"));
    }
    c::amount_ok("amount_minor", amount, false)?;
    Ok(amount)
}

fn live_account(conn: &Connection, id: &str) -> DomainResult<Obj> {
    let account = c::require_live(conn, "account", id)?;
    if account["archived"].as_bool().unwrap_or(false) {
        return Err(DomainError::conflict("account is archived"));
    }
    Ok(account)
}

fn same_currency(a: &Obj, b: &Obj, field: &str) -> DomainResult<()> {
    if a["currency"] != b["currency"] {
        return Err(DomainError::validation(
            field,
            format!(
                "accounts use different currencies ({} and {}); REVA never converts currencies automatically",
                a["currency"].as_str().unwrap_or("?"),
                b["currency"].as_str().unwrap_or("?")
            ),
        ));
    }
    Ok(())
}

struct Leg<'a> {
    id: String,
    account_id: &'a str,
    date: Date,
    amount: i64,
    description: String,
    category_id: Option<String>,
    notes: Option<String>,
    link_id: &'a str,
    role: &'static str,
    external_ref: Option<String>,
}

fn leg(conn: &Connection, l: Leg, now: &str) -> DomainResult<EventDraft> {
    let nt = NewTransaction {
        id: Some(l.id),
        account_id: l.account_id.to_string(),
        date: l.date,
        amount_minor: l.amount,
        currency: None,
        description: l.description,
        merchant: None,
        category_id: l.category_id,
        notes: l.notes,
        import_batch_id: None,
        fingerprint: None,
        source: Some("manual".to_string()),
    };
    let (id, mut s) = c::build_transaction(conn, nt, now)?;
    c::set(&mut s, "link_id", l.link_id);
    c::set(&mut s, "link_role", l.role);
    c::set(&mut s, "external_ref", l.external_ref.map(Value::from).unwrap_or(Value::Null));
    Ok(c::draft("transaction", &id, "created", s))
}

/// `internal_move.record`: money moved between two of the owner's accounts (savings, a card repayment,
/// cash withdrawn). Two linked legs; neither is income or spending.
fn internal_move(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(
        map,
        &["id", "from_account_id", "to_account_id", "date", "amount_minor", "description", "notes", "external_ref"],
    )?;
    let id = link_id_field(map)?;
    let from_id = c::id_of(map, "from_account_id")?;
    let to_id = c::id_of(map, "to_account_id")?;
    if from_id == to_id {
        return Err(DomainError::validation("to_account_id", "must differ from from_account_id"));
    }
    let date = c::date_field(map, "date", true)?.ok_or_else(|| DomainError::validation("date", "required"))?;
    let amount = positive_amount(map)?;
    let from = live_account(conn, &from_id)?;
    let to = live_account(conn, &to_id)?;
    same_currency(&from, &to, "to_account_id")?;
    let description = c::text_field(map, "description", 500, false)?;
    let notes = c::text_field(map, "notes", 2000, false)?;
    let external_ref = external_ref_field(map, false)?;
    let name = |a: &Obj| a["name"].as_str().unwrap_or("account").to_string();
    Ok(vec![
        leg(
            conn,
            Leg {
                id: format!("{id}-out"),
                account_id: &from_id,
                date,
                amount: -amount,
                description: description.clone().unwrap_or_else(|| format!("Moved to {}", name(&to))),
                category_id: None,
                notes: notes.clone(),
                link_id: &id,
                role: "move_out",
                external_ref: external_ref.clone(),
            },
            now,
        )?,
        leg(
            conn,
            Leg {
                id: format!("{id}-in"),
                account_id: &to_id,
                date,
                amount,
                description: description.unwrap_or_else(|| format!("Moved from {}", name(&from))),
                category_id: None,
                notes,
                link_id: &id,
                role: "move_in",
                external_ref,
            },
            now,
        )?,
    ])
}

/// Round `numerator / denominator` half away from zero (denominator > 0).
fn round_div(numerator: i128, denominator: i128) -> i128 {
    if numerator >= 0 {
        (numerator + denominator / 2) / denominator
    } else {
        -((-numerator + denominator / 2) / denominator)
    }
}

/// One month of interest on `principal` at `apr_bp` basis points a year (rate / 12), to the minor unit.
fn monthly_interest(principal: i64, apr_bp: i64) -> i64 {
    round_div(i128::from(principal) * i128::from(apr_bp), 120_000) as i64
}

fn balance_of(conn: &Connection, account_id: &str, as_of: Option<Date>) -> DomainResult<i64> {
    Ok(queries::balances(conn, as_of, true)?
        .into_iter()
        .find(|b| b.account["id"].as_str() == Some(account_id))
        .map(|b| b.balance_minor)
        .unwrap_or(0))
}

/// `loan_installment.record`: an installment paid from `from_account_id` toward a loan account. The
/// principal part is a move (lowers the loan, not spending); the interest part is spending.
fn loan_installment(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(
        map,
        &[
            "id",
            "loan_account_id",
            "from_account_id",
            "date",
            "amount_minor",
            "interest_minor",
            "interest_category_id",
            "notes",
            "external_ref",
        ],
    )?;
    let id = link_id_field(map)?;
    let loan_id = c::id_of(map, "loan_account_id")?;
    let from_id = c::id_of(map, "from_account_id")?;
    let date = c::date_field(map, "date", true)?.ok_or_else(|| DomainError::validation("date", "required"))?;
    let amount = positive_amount(map)?;
    let loan = live_account(conn, &loan_id)?;
    if loan["kind"].as_str() != Some("loan") {
        return Err(DomainError::validation("loan_account_id", "must be a loan account"));
    }
    let from = live_account(conn, &from_id)?;
    same_currency(&from, &loan, "from_account_id")?;
    let outstanding = (-balance_of(conn, &loan_id, Some(date.add_days(-1)))?).max(0);
    let interest = match c::int_field(map, "interest_minor", false)? {
        Some(v) => v,
        None => match loan.get("apr_bp").and_then(Value::as_i64) {
            Some(apr) => monthly_interest(outstanding, apr),
            None => {
                return Err(DomainError::validation(
                    "interest_minor",
                    "required: the loan has no recorded rate, and REVA does not guess interest",
                ))
            }
        },
    };
    if interest < 0 || interest > amount {
        return Err(DomainError::validation("interest_minor", "must be between 0 and amount_minor"));
    }
    let principal = amount - interest;
    if principal > outstanding {
        return Err(DomainError::validation(
            "amount_minor",
            format!("principal part {principal} is more than the outstanding {outstanding}"),
        ));
    }
    let interest_category = match c::text_field(map, "interest_category_id", 64, false)? {
        None => None,
        Some(cat) => {
            let category = c::require_live(conn, "category", &cat)?;
            if category["kind"].as_str() != Some("expense") {
                return Err(DomainError::validation("interest_category_id", "must be an expense category"));
            }
            Some(cat)
        }
    };
    let notes = c::text_field(map, "notes", 2000, false)?;
    let external_ref = external_ref_field(map, false)?;
    let loan_name = loan["name"].as_str().unwrap_or("loan").to_string();
    let mut drafts = Vec::new();
    if principal > 0 {
        for (suffix, account, signed, role, text) in [
            ("out", from_id.as_str(), -principal, "principal_out", format!("{loan_name} principal")),
            ("in", loan_id.as_str(), principal, "principal_in", format!("{loan_name} principal")),
        ] {
            drafts.push(leg(
                conn,
                Leg {
                    id: format!("{id}-{suffix}"),
                    account_id: account,
                    date,
                    amount: signed,
                    description: text,
                    category_id: None,
                    notes: notes.clone(),
                    link_id: &id,
                    role,
                    external_ref: external_ref.clone(),
                },
                now,
            )?);
        }
    }
    if interest > 0 {
        drafts.push(leg(
            conn,
            Leg {
                id: format!("{id}-int"),
                account_id: &from_id,
                date,
                amount: -interest,
                description: format!("{loan_name} interest"),
                category_id: interest_category,
                notes,
                link_id: &id,
                role: "interest",
                external_ref,
            },
            now,
        )?);
    }
    Ok(drafts)
}

/// `transaction.ingest`: a transaction the owner confirmed from an outside source (a Gmail alert on the
/// phone, a file). `external_ref` is its provenance key: the same ref with the same facts is a no-op, the
/// same ref with different facts is refused (see [`replay_of`]).
fn ingest(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(
        map,
        &[
            "id",
            "account_id",
            "date",
            "amount_minor",
            "currency",
            "description",
            "merchant",
            "category_id",
            "notes",
            "external_ref",
            "source",
        ],
    )?;
    let external_ref = external_ref_field(map, true)?.unwrap_or_default();
    let source = c::enum_field(map, "source", INGEST_SOURCES)?.unwrap_or_else(|| "email".to_string());
    let nt = NewTransaction {
        id: c::text_field(map, "id", 64, false)?,
        account_id: c::id_of(map, "account_id")?,
        date: c::date_field(map, "date", true)?.ok_or_else(|| DomainError::validation("date", "required"))?,
        amount_minor: c::int_field(map, "amount_minor", true)?.unwrap_or(0),
        currency: c::currency_field(map, "currency")?,
        description: c::text_field(map, "description", 500, true)?.unwrap_or_default(),
        merchant: c::text_field(map, "merchant", 200, false)?,
        category_id: c::text_field(map, "category_id", 64, false)?,
        notes: c::text_field(map, "notes", 2000, false)?,
        import_batch_id: None,
        fingerprint: None,
        source: Some(source),
    };
    let (id, mut s) = c::build_transaction(conn, nt, now)?;
    c::set(&mut s, "external_ref", external_ref);
    Ok(vec![c::draft("transaction", &id, "created", s)])
}

/// `reconciliation.record`: the owner compared an account with a statement. Records the statement
/// balance, REVA's ledger balance on that date and the difference; it never edits transactions.
fn reconciliation(conn: &Connection, payload: &Value, now: &str) -> DomainResult<Vec<EventDraft>> {
    let map = c::object(payload)?;
    c::reject_unknown(map, &["id", "account_id", "statement_date", "statement_balance_minor", "notes"])?;
    let id = match c::text_field(map, "id", 64, false)? {
        Some(id) if c::valid_id(&id) => id,
        Some(_) => return Err(DomainError::validation("id", "must be 8-64 characters of letters, digits, '_' or '-'")),
        None => uuid::Uuid::new_v4().to_string(),
    };
    c::ensure_new(conn, "reconciliation", &id)?;
    let account_id = c::id_of(map, "account_id")?;
    let account = c::require_live(conn, "account", &account_id)?;
    let date = c::date_field(map, "statement_date", true)?
        .ok_or_else(|| DomainError::validation("statement_date", "required"))?;
    let statement = c::int_field(map, "statement_balance_minor", true)?.unwrap_or(0);
    c::amount_ok("statement_balance_minor", statement, true)?;
    let ledger = balance_of(conn, &account_id, Some(date))?;
    let mut s = Obj::new();
    c::set(&mut s, "id", id.clone());
    c::set(&mut s, "account_id", account_id);
    c::set(&mut s, "statement_date", date.to_iso());
    c::set(&mut s, "statement_balance_minor", statement);
    c::set(&mut s, "ledger_balance_minor", ledger);
    c::set(&mut s, "difference_minor", statement - ledger);
    c::set(&mut s, "currency", account["currency"].clone());
    c::set(&mut s, "notes", c::text_field(map, "notes", 2000, false)?.map(Value::from).unwrap_or(Value::Null));
    c::set(&mut s, "created_at", now);
    c::set(&mut s, "updated_at", now);
    Ok(vec![c::draft("reconciliation", &id, "recorded", s)])
}

// ---------------------------------------------------------------------------------------------
// Duplicate-safe replays

fn tx_rows(conn: &Connection, condition: &str, arg: &str) -> DomainResult<Vec<Obj>> {
    schema::select(conn, "transaction", &format!("WHERE {condition} ORDER BY id"), vec![arg.to_string().into()])
}

fn differs(what: &str) -> DomainError {
    DomainError::conflict(format!("{what} is already recorded with different facts; nothing was changed"))
}

/// When a command repeats something already recorded with the same facts, return the aggregate to report
/// instead of writing again (`None` means: not recorded yet, run the command). Same key with different facts
/// is refused, so an alert seen twice can never become two transactions or silently overwrite one.
pub fn replay_of(conn: &Connection, kind: &str, payload: &Value) -> DomainResult<Option<(String, String)>> {
    let Some(map) = payload.as_object() else { return Ok(None) };
    let text = |k: &str| map.get(k).and_then(Value::as_str).map(str::trim).unwrap_or("");
    let int = |k: &str| map.get(k).and_then(Value::as_i64);
    match kind {
        "internal_move.record" | "loan_installment.record" => {
            let id = text("id");
            if id.is_empty() {
                return Ok(None);
            }
            let legs = tx_rows(conn, "link_id = ?1", id)?;
            if legs.is_empty() {
                return Ok(None);
            }
            let out_total: i64 = legs
                .iter()
                .filter(|l| l["account_id"].as_str() == Some(text("from_account_id")))
                .map(|l| -l["amount_minor"].as_i64().unwrap_or(0))
                .sum();
            let to_key = if kind == "internal_move.record" { "to_account_id" } else { "loan_account_id" };
            let to_seen = legs.iter().any(|l| l["account_id"].as_str() == Some(text(to_key)))
                || (kind == "loan_installment.record" && legs.iter().all(|l| l["link_role"] == "interest"));
            let same_date = legs.iter().all(|l| l["date"].as_str() == Some(text("date")));
            if Some(out_total) == int("amount_minor") && to_seen && same_date {
                // Report the leg the first write reported: the outgoing one, or the interest leg alone.
                let head = legs
                    .iter()
                    .find(|l| matches!(l["link_role"].as_str(), Some("move_out" | "principal_out")))
                    .or_else(|| legs.first())
                    .and_then(|l| l["id"].as_str())
                    .unwrap_or_default()
                    .to_string();
                return Ok(Some(("transaction".to_string(), head)));
            }
            Err(differs(&format!("record {id}")))
        }
        "transaction.ingest" => {
            let reference = text("external_ref");
            if reference.is_empty() {
                return Ok(None);
            }
            let Some(existing) = tx_rows(conn, "external_ref = ?1", reference)?.into_iter().next() else {
                return Ok(None);
            };
            let same = existing["account_id"].as_str() == Some(text("account_id"))
                && existing["date"].as_str() == Some(text("date"))
                && existing["amount_minor"].as_i64() == int("amount_minor")
                && (text("currency").is_empty() || existing["currency"].as_str() == Some(text("currency")));
            if same {
                return Ok(Some(("transaction".to_string(), existing["id"].as_str().unwrap_or_default().to_string())));
            }
            Err(differs(&format!("external reference {reference:?}")))
        }
        _ => Ok(None),
    }
}

/// Every leg that shares `link_id` with transaction `id` (just `id` itself when it is not linked).
pub fn linked_legs(conn: &Connection, id: &str) -> DomainResult<Vec<String>> {
    let link: Option<Option<String>> =
        conn.query_row("SELECT link_id FROM transactions WHERE id = ?1", [id], |r| r.get(0)).optional()?;
    match link.flatten() {
        None => Ok(vec![id.to_string()]),
        Some(link_id) => {
            let mut stmt = conn.prepare("SELECT id FROM transactions WHERE link_id = ?1 ORDER BY id")?;
            let ids = stmt.query_map([link_id], |r| r.get::<_, String>(0))?.collect::<Result<Vec<_>, _>>()?;
            Ok(ids)
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Queries

pub fn query(conn: &Connection, name: &str, params: &Value) -> Option<DomainResult<QueryOut>> {
    Some(match name {
        "period_summary" => period_summary(conn, params),
        "credit_card_status" => credit_card_status(conn, params),
        "loan_status" => loan_status(conn, params),
        "liabilities" => liabilities(conn, params),
        "list_reconciliations" => list_reconciliations(conn, params),
        _ => return None,
    })
}

fn param_str<'a>(params: &'a Value, key: &str) -> Option<&'a str> {
    params.get(key).and_then(Value::as_str)
}

fn account_param(conn: &Connection, params: &Value, kind: &str) -> DomainResult<Obj> {
    let id = param_str(params, "account_id").ok_or_else(|| DomainError::validation("account_id", "required"))?;
    let account = c::require_live(conn, "account", id)?;
    if account["kind"].as_str() != Some(kind) {
        return Err(DomainError::validation("account_id", format!("must be a {kind} account")));
    }
    Ok(account)
}

fn missing(account: &Obj, keys: &[&str]) -> Vec<String> {
    keys.iter().filter(|k| account.get(**k).map(Value::is_null).unwrap_or(true)).map(|k| k.to_string()).collect()
}

/// The date in `month` with day `day`, clamped to the month's last day.
fn day_in_month(month: Date, day: i64) -> Date {
    let last = month.last_of_month();
    let wanted = month.first_of_month().add_days(day - 1);
    if wanted > last {
        last
    } else {
        wanted
    }
}

/// Income, spending, refunds and interest for a period, per currency, with the accounting rules at the top
/// of this file applied. Moves between the owner's accounts are listed as excluded, never counted.
fn period_summary(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let (from, to) = match (param_str(params, "from"), param_str(params, "to")) {
        (Some(f), Some(t)) => (
            Date::parse(f).ok_or_else(|| DomainError::validation("from", "must be YYYY-MM-DD"))?,
            Date::parse(t).ok_or_else(|| DomainError::validation("to", "must be YYYY-MM-DD"))?,
        ),
        _ => {
            let period = param_str(params, "period").unwrap_or("this_month");
            queries::resolve_period(period, queries::as_of(params)?)?
        }
    };
    if from > to {
        return Err(DomainError::validation("from", "after to"));
    }
    let mut stmt = conn.prepare(
        "SELECT t.id, t.currency, t.amount_minor, t.link_role, c.kind, a.kind
           FROM transactions t
           LEFT JOIN categories c ON c.id = t.category_id
           LEFT JOIN accounts a ON a.id = t.account_id
          WHERE t.date >= ?1 AND t.date <= ?2
          ORDER BY t.date, t.id",
    )?;
    let mut rows = stmt.query([from.to_iso(), to.to_iso()])?;
    #[derive(Default)]
    struct Totals {
        purchases: i64,
        refunds: i64,
        interest: i64,
        income: i64,
        excluded_moves: i64,
    }
    let mut by_currency: BTreeMap<String, Totals> = BTreeMap::new();
    let mut source_ids = Vec::new();
    while let Some(r) = rows.next()? {
        let id: String = r.get(0)?;
        let currency: String = r.get(1)?;
        let amount: i64 = r.get(2)?;
        let role: Option<String> = r.get(3)?;
        let category_kind: Option<String> = r.get(4)?;
        let account_kind: Option<String> = r.get(5)?;
        let t = by_currency.entry(currency).or_default();
        match (role.as_deref(), category_kind.as_deref()) {
            (Some(r), _) if NEUTRAL_ROLES.contains(&r) => {
                t.excluded_moves += 1;
                continue;
            }
            (_, Some("transfer")) => {
                t.excluded_moves += 1;
                continue;
            }
            (Some("interest"), _) => t.interest += -amount,
            _ if amount < 0 => t.purchases += -amount,
            (_, Some("expense")) => t.refunds += amount,
            (_, None) if account_kind.as_deref() == Some("credit") => t.refunds += amount,
            _ => t.income += amount,
        }
        source_ids.push(id);
    }
    let out: Vec<Value> = by_currency
        .into_iter()
        .map(|(currency, t)| {
            let spending = t.purchases - t.refunds + t.interest;
            json!({
                "currency": currency, "from": from.to_iso(), "to": to.to_iso(),
                "purchases_minor": t.purchases, "refunds_minor": t.refunds, "interest_minor": t.interest,
                "net_spending_minor": spending, "income_minor": t.income, "net_minor": t.income - spending,
                "excluded_moves": t.excluded_moves,
                "assumptions": [
                    "moves between your own accounts, card repayments and loan principal are neither income nor spending",
                    "money in with an expense category, or uncategorized money in on a credit account, is a refund",
                    "each currency is totalled separately; nothing is converted",
                ],
            })
        })
        .collect();
    Ok(QueryOut { rows: Value::Array(out), source_ids })
}

fn credit_card_status(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let account = account_param(conn, params, "credit")?;
    let as_of = queries::as_of(params)?;
    let id = account["id"].as_str().unwrap_or_default().to_string();
    let balance = balance_of(conn, &id, Some(as_of))?;
    let owed = (-balance).max(0);
    let limit = account.get("credit_limit_minor").and_then(Value::as_i64);
    let statement_day = account.get("statement_day").and_then(Value::as_i64);
    let due_day = account.get("due_day").and_then(Value::as_i64);
    let next_due = due_day.map(|d| {
        let this_month = day_in_month(as_of, d);
        if this_month >= as_of {
            this_month
        } else {
            day_in_month(as_of.first_of_month().add_months(1), d)
        }
    });
    let last_statement = statement_day.map(|d| {
        let this_month = day_in_month(as_of, d);
        if this_month <= as_of {
            this_month
        } else {
            day_in_month(as_of.first_of_month().add_months(-1), d)
        }
    });
    let mut source_ids = vec![id.clone()];
    let (mut cycle_purchases, mut cycle_repayments) = (0_i64, 0_i64);
    if let Some(start) = last_statement {
        let mut stmt = conn.prepare(
            "SELECT id, amount_minor, link_role FROM transactions
              WHERE account_id = ?1 AND date > ?2 AND date <= ?3 ORDER BY date, id",
        )?;
        let mut rows = stmt.query([id.clone(), start.to_iso(), as_of.to_iso()])?;
        while let Some(r) = rows.next()? {
            let amount: i64 = r.get(1)?;
            let role: Option<String> = r.get(2)?;
            match role.as_deref() {
                Some("move_in") => cycle_repayments += amount,
                None if amount < 0 => cycle_purchases += -amount,
                _ => continue,
            }
            source_ids.push(r.get(0)?);
        }
    }
    let unknown = missing(&account, &["credit_limit_minor", "statement_day", "due_day"]);
    let row = json!({
        "account_id": id, "name": account["name"], "currency": account["currency"], "as_of": as_of.to_iso(),
        "balance_minor": balance, "owed_minor": owed, "credit_balance_minor": balance.max(0),
        "credit_limit_minor": limit,
        "available_credit_minor": limit.map(|l| l - owed),
        "utilization_bp": limit.filter(|l| *l > 0).map(|l| owed * 10_000 / l),
        "apr_bp": account.get("apr_bp").cloned().unwrap_or(Value::Null),
        "last_statement_date": last_statement.map(Date::to_iso),
        "next_due_date": next_due.map(Date::to_iso),
        "cycle_purchases_minor": last_statement.map(|_| cycle_purchases),
        "cycle_repayments_minor": last_statement.map(|_| cycle_repayments),
        "complete": unknown.is_empty(), "unknown": unknown,
    });
    Ok(QueryOut { rows: json!([row]), source_ids })
}

/// Fixed installment that repays `principal` over `months` at `apr_bp`, rounded up to the minor unit.
fn installment(principal: i64, apr_bp: i64, months: i64) -> i64 {
    if principal <= 0 {
        return 0;
    }
    if apr_bp == 0 {
        return (principal + months - 1) / months;
    }
    let r = apr_bp as f64 / 120_000.0;
    let payment = principal as f64 * r / (1.0 - (1.0 + r).powi(-(months as i32)));
    payment.ceil() as i64
}

fn loan_status(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let account = account_param(conn, params, "loan")?;
    let as_of = queries::as_of(params)?;
    let id = account["id"].as_str().unwrap_or_default().to_string();
    let outstanding = (-balance_of(conn, &id, Some(as_of))?).max(0);
    let mut source_ids = vec![id.clone()];
    {
        let mut stmt =
            conn.prepare("SELECT id FROM transactions WHERE account_id = ?1 AND date <= ?2 ORDER BY date, id")?;
        let ids = stmt.query_map([id.clone(), as_of.to_iso()], |r| r.get::<_, String>(0))?;
        for tx in ids {
            source_ids.push(tx?);
        }
    }
    let apr = account.get("apr_bp").and_then(Value::as_i64);
    let term = account.get("loan_term_months").and_then(Value::as_i64);
    let first_due = account.get("loan_first_due").and_then(Value::as_str).and_then(Date::parse);
    let unknown = missing(&account, &["apr_bp", "loan_term_months", "loan_first_due"]);
    let mut row = json!({
        "account_id": id, "name": account["name"], "currency": account["currency"], "as_of": as_of.to_iso(),
        "outstanding_principal_minor": outstanding,
        "original_principal_minor": account.get("loan_principal_minor").cloned().unwrap_or(Value::Null),
        "apr_bp": apr, "term_months": term, "first_due": first_due.map(Date::to_iso),
        "complete": unknown.is_empty(), "unknown": unknown,
        "installment_minor": Value::Null, "next_due_date": Value::Null, "remaining_installments": Value::Null,
        "remaining_interest_minor": Value::Null, "schedule": [],
        "assumptions": [
            "monthly interest is the yearly rate divided by 12, on the outstanding principal",
            "a fixed installment repays the recorded outstanding principal over the remaining term",
            "amounts are rounded to the minor unit; the last installment absorbs rounding",
        ],
    });
    if let (Some(apr), Some(term), Some(first)) = (apr, term, first_due) {
        let mut elapsed = 0_i64;
        while elapsed < term && first.add_months(elapsed as i32) <= as_of {
            elapsed += 1;
        }
        let remaining = (term - elapsed).max(if outstanding > 0 { 1 } else { 0 });
        let payment = installment(outstanding, apr, remaining.max(1));
        let mut balance = outstanding;
        let mut schedule = Vec::new();
        let mut total_interest = 0_i64;
        for k in 0..remaining {
            if balance <= 0 {
                break;
            }
            let interest = monthly_interest(balance, apr);
            let mut principal = (payment - interest).max(0).min(balance);
            if k == remaining - 1 {
                principal = balance;
            }
            balance -= principal;
            total_interest += interest;
            schedule.push(json!({
                "date": first.add_months((elapsed + k) as i32).to_iso(),
                "installment_minor": principal + interest, "interest_minor": interest,
                "principal_minor": principal, "remaining_minor": balance,
            }));
        }
        row["installment_minor"] = json!(if outstanding > 0 { Some(payment) } else { None });
        row["next_due_date"] = json!(schedule.first().map(|s| s["date"].clone()));
        row["remaining_installments"] = json!(schedule.len());
        row["remaining_interest_minor"] = json!(total_interest);
        row["schedule"] = Value::Array(schedule);
    }
    Ok(QueryOut { rows: json!([row]), source_ids })
}

/// What the owner owes on credit and loan accounts, per account and per currency.
fn liabilities(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let as_of = queries::as_of(params)?;
    let mut accounts = Vec::new();
    let mut totals: BTreeMap<String, i64> = BTreeMap::new();
    let mut source_ids = Vec::new();
    for b in queries::balances(conn, Some(as_of), false)? {
        let kind = b.account["kind"].as_str().unwrap_or("");
        if kind != "credit" && kind != "loan" {
            continue;
        }
        let owed = (-b.balance_minor).max(0);
        let currency = b.account["currency"].as_str().unwrap_or("").to_string();
        *totals.entry(currency.clone()).or_default() += owed;
        source_ids.push(b.account["id"].as_str().unwrap_or_default().to_string());
        accounts.push(json!({
            "account_id": b.account["id"], "name": b.account["name"], "kind": kind, "currency": currency,
            "owed_minor": owed, "due_day": b.account.get("due_day").cloned().unwrap_or(Value::Null),
        }));
    }
    let totals: Vec<Value> =
        totals.into_iter().map(|(currency, owed)| json!({"currency": currency, "owed_minor": owed})).collect();
    Ok(QueryOut { rows: json!([{ "as_of": as_of.to_iso(), "accounts": accounts, "totals": totals }]), source_ids })
}

fn list_reconciliations(conn: &Connection, params: &Value) -> DomainResult<QueryOut> {
    let rows = match param_str(params, "account_id") {
        Some(id) => schema::select(
            conn,
            "reconciliation",
            "WHERE account_id = ?1 ORDER BY statement_date DESC, id",
            vec![id.to_string().into()],
        )?,
        None => schema::select(conn, "reconciliation", "ORDER BY statement_date DESC, id", vec![])?,
    };
    let ids = rows.iter().filter_map(|r| r["id"].as_str().map(str::to_string)).collect();
    Ok(QueryOut { rows: Value::Array(rows.into_iter().map(Value::Object).collect()), source_ids: ids })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interest_rounds_half_away_from_zero_to_the_minor_unit() {
        // 1,000.00 at 6.00 % a year: 5.00 a month exactly.
        assert_eq!(monthly_interest(100_000, 600), 500);
        // 1,234.56 at 7.99 %: 123456 * 799 / 120000 = 822.0... -> 822
        assert_eq!(monthly_interest(123_456, 799), 822);
        assert_eq!(round_div(5, 10), 1);
        assert_eq!(round_div(-5, 10), -1);
    }

    #[test]
    fn installment_repays_the_principal_and_zero_rate_splits_evenly() {
        assert_eq!(installment(120_000, 0, 12), 10_000);
        assert_eq!(installment(100_001, 0, 2), 50_001);
        // 10,000.00 over 12 months at 12 %: textbook 888.49 per month.
        assert_eq!(installment(1_000_000, 1_200, 12), 88_849);
        assert_eq!(installment(0, 1_200, 12), 0);
    }

    #[test]
    fn day_in_month_clamps_to_the_last_day() {
        let feb = Date::parse("2026-02-10").unwrap();
        assert_eq!(day_in_month(feb, 31).to_iso(), "2026-02-28");
        assert_eq!(day_in_month(feb, 5).to_iso(), "2026-02-05");
    }
}
