//! FIN-3: credit cards, loans, internal moves, refunds, duplicate-safe ingestion and reconciliation.
//! Every scenario uses synthetic accounts and amounts.

mod common;

use common::{cmd, code, open, rows, MemKeys};
use reva_kernel::DomainHandle;
use serde_json::{json, Value};

fn setup() -> (tempfile::TempDir, std::sync::Arc<DomainHandle>, std::sync::Arc<MemKeys>) {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let h = open(dir.path(), &keys).unwrap();
    cmd(
        &h,
        "account.create",
        json!({"id":"acct-chk-001","name":"Checking","kind":"checking","currency":"USD","opening_balance_minor":500_000}),
    );
    cmd(
        &h,
        "account.create",
        json!({"id":"acct-sav-001","name":"Savings","kind":"savings","currency":"USD","opening_balance_minor":0}),
    );
    cmd(
        &h,
        "account.create",
        json!({
            "id":"acct-card-01","name":"Card","kind":"credit","currency":"USD","opening_balance_minor":0,
            "credit_limit_minor":200_000,"statement_day":5,"due_day":28,"apr_bp":2_499
        }),
    );
    cmd(&h, "category.create", json!({"id":"cat-food-001","name":"Food","kind":"expense"}));
    cmd(&h, "category.create", json!({"id":"cat-pay-0001","name":"Salary","kind":"income"}));
    (dir, h, keys)
}

fn err(h: &DomainHandle, kind: &str, payload: Value) -> &'static str {
    let e = h.command(kind.to_string(), payload.to_string()).unwrap_err();
    code(&e)
}

fn summary(h: &DomainHandle, from: &str, to: &str) -> Value {
    rows(h, "period_summary", json!({"from": from, "to": to})).into_iter().next().unwrap()
}

fn balance(h: &DomainHandle, id: &str) -> i64 {
    rows(h, "account_balances", json!({"as_of":"2026-12-31","include_archived":true}))
        .into_iter()
        .find(|b| b["account_id"] == id)
        .unwrap()["balance_minor"]
        .as_i64()
        .unwrap()
}

#[test]
fn a_card_purchase_is_spending_once_and_repaying_it_is_not_spending_again() {
    let (_d, h, _k) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-card-buy1","account_id":"acct-card-01","date":"2026-10-10","amount_minor":-12_499,"description":"Groceries","category_id":"cat-food-001"}),
    );
    cmd(
        &h,
        "internal_move.record",
        json!({"id":"mv-cardpay-01","from_account_id":"acct-chk-001","to_account_id":"acct-card-01","date":"2026-10-25","amount_minor":12_499}),
    );

    let s = summary(&h, "2026-10-01", "2026-10-31");
    assert_eq!(s["purchases_minor"], 12_499);
    assert_eq!(s["net_spending_minor"], 12_499, "the repayment adds no spending");
    assert_eq!(s["income_minor"], 0, "the repayment is not income on the card");
    assert_eq!(s["excluded_moves"], 2);

    // The legacy reports agree: one outflow, no income.
    let flow = &rows(&h, "cashflow", json!({"period":"this_month","as_of":"2026-10-31"}))[0];
    assert_eq!(flow["expense_minor"], 12_499);
    assert_eq!(flow["income_minor"], 0);
    let spend: i64 = rows(&h, "spend_by_category", json!({"period":"this_month","as_of":"2026-10-31"}))
        .iter()
        .map(|r| r["spent_minor"].as_i64().unwrap())
        .sum();
    assert_eq!(spend, 12_499);

    assert_eq!(balance(&h, "acct-card-01"), 0, "card fully repaid");
    assert_eq!(balance(&h, "acct-chk-001"), 500_000 - 12_499);
}

#[test]
fn an_internal_move_is_never_income_and_keeps_total_money_unchanged() {
    let (_d, h, _k) = setup();
    cmd(
        &h,
        "internal_move.record",
        json!({"id":"mv-save-0001","from_account_id":"acct-chk-001","to_account_id":"acct-sav-001","date":"2026-10-03","amount_minor":100_000}),
    );
    let s = summary(&h, "2026-10-01", "2026-10-31");
    assert_eq!(s["income_minor"], 0);
    assert_eq!(s["net_spending_minor"], 0);
    assert_eq!(balance(&h, "acct-chk-001") + balance(&h, "acct-sav-001"), 500_000);
    let budget_free = rows(&h, "cashflow", json!({"period":"this_month","as_of":"2026-10-31"}));
    assert!(budget_free.is_empty(), "nothing counted: {budget_free:?}");
}

#[test]
fn salary_is_income_and_a_refund_reduces_spending_instead_of_counting_as_income() {
    let (_d, h, _k) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-salary-01","account_id":"acct-chk-001","date":"2026-10-01","amount_minor":300_000,"description":"Salary","category_id":"cat-pay-0001"}),
    );
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-card-buy2","account_id":"acct-card-01","date":"2026-10-11","amount_minor":-12_499,"description":"TECHSTORE ONLINE"}),
    );
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-refund-01","account_id":"acct-card-01","date":"2026-10-12","amount_minor":2_450,"description":"TECHSTORE refund"}),
    );
    let s = summary(&h, "2026-10-01", "2026-10-31");
    assert_eq!(s["income_minor"], 300_000);
    assert_eq!(s["purchases_minor"], 12_499);
    assert_eq!(s["refunds_minor"], 2_450, "uncategorized money in on a card is a refund");
    assert_eq!(s["net_spending_minor"], 10_049);
    assert_eq!(s["net_minor"], 300_000 - 10_049);
}

#[test]
fn card_status_reports_owed_available_credit_and_the_next_due_date() {
    let (_d, h, _k) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-card-buy3","account_id":"acct-card-01","date":"2026-10-07","amount_minor":-50_000,"description":"Flight"}),
    );
    cmd(
        &h,
        "internal_move.record",
        json!({"id":"mv-cardpay-02","from_account_id":"acct-chk-001","to_account_id":"acct-card-01","date":"2026-10-09","amount_minor":20_000}),
    );
    let st = &rows(&h, "credit_card_status", json!({"account_id":"acct-card-01","as_of":"2026-10-10"}))[0];
    assert_eq!(st["owed_minor"], 30_000);
    assert_eq!(st["available_credit_minor"], 170_000);
    assert_eq!(st["utilization_bp"], 1_500);
    assert_eq!(st["last_statement_date"], "2026-10-05");
    assert_eq!(st["next_due_date"], "2026-10-28");
    assert_eq!(st["cycle_purchases_minor"], 50_000);
    assert_eq!(st["cycle_repayments_minor"], 20_000);
    assert_eq!(st["complete"], true);
    // After the due day it rolls to next month.
    let later = &rows(&h, "credit_card_status", json!({"account_id":"acct-card-01","as_of":"2026-10-29"}))[0];
    assert_eq!(later["next_due_date"], "2026-11-28");
}

#[test]
fn a_card_without_a_limit_reports_unknown_instead_of_inventing_one() {
    let (_d, h, _k) = setup();
    cmd(&h, "account.create", json!({"id":"acct-card-02","name":"Store card","kind":"credit","currency":"USD"}));
    let st = &rows(&h, "credit_card_status", json!({"account_id":"acct-card-02","as_of":"2026-10-10"}))[0];
    assert_eq!(st["complete"], false);
    assert_eq!(st["available_credit_minor"], Value::Null);
    assert_eq!(st["next_due_date"], Value::Null);
    assert_eq!(st["unknown"], json!(["credit_limit_minor", "statement_day", "due_day"]));
}

#[test]
fn account_terms_must_match_the_account_kind() {
    let (_d, h, _k) = setup();
    assert_eq!(
        err(&h, "account.create", json!({"name":"Bad","kind":"checking","currency":"USD","credit_limit_minor":1})),
        "validation"
    );
    assert_eq!(
        err(&h, "account.create", json!({"name":"Bad2","kind":"credit","currency":"USD","loan_term_months":12})),
        "validation"
    );
    assert_eq!(err(&h, "account.update", json!({"id":"acct-card-01","due_day":32})), "validation");
    cmd(&h, "account.update", json!({"id":"acct-card-01","credit_limit_minor":null}));
    let st = &rows(&h, "credit_card_status", json!({"account_id":"acct-card-01","as_of":"2026-10-10"}))[0];
    assert_eq!(st["credit_limit_minor"], Value::Null, "an explicit null clears a term");
}

fn loan(h: &DomainHandle) {
    // 10,000.00 borrowed at 12 % over 12 months, first installment 2026-11-01. Opening balance is the debt.
    cmd(
        h,
        "account.create",
        json!({
            "id":"acct-loan-01","name":"Car loan","kind":"loan","currency":"USD","opening_balance_minor":-1_000_000,
            "loan_principal_minor":1_000_000,"apr_bp":1_200,"loan_term_months":12,"loan_first_due":"2026-11-01"
        }),
    );
}

#[test]
fn a_loan_schedule_amortises_exactly_to_zero_with_stated_assumptions() {
    let (_d, h, _k) = setup();
    loan(&h);
    let st = &rows(&h, "loan_status", json!({"account_id":"acct-loan-01","as_of":"2026-10-15"}))[0];
    assert_eq!(st["complete"], true);
    assert_eq!(st["outstanding_principal_minor"], 1_000_000);
    assert_eq!(st["installment_minor"], 88_849);
    assert_eq!(st["next_due_date"], "2026-11-01");
    let schedule = st["schedule"].as_array().unwrap();
    assert_eq!(schedule.len(), 12);
    assert_eq!(schedule[0]["interest_minor"], 10_000, "1 % of 10,000.00");
    assert_eq!(schedule[0]["principal_minor"], 78_849);
    assert_eq!(schedule.last().unwrap()["remaining_minor"], 0);
    let principal: i64 = schedule.iter().map(|r| r["principal_minor"].as_i64().unwrap()).sum();
    assert_eq!(principal, 1_000_000, "the schedule repays exactly the principal");
    assert!(st["assumptions"].as_array().unwrap().len() >= 3);
}

#[test]
fn a_loan_installment_splits_principal_from_interest_and_only_interest_is_spending() {
    let (_d, h, _k) = setup();
    loan(&h);
    // Interest omitted: computed from the recorded rate on the outstanding principal (10,000.00 * 1 %).
    cmd(
        &h,
        "loan_installment.record",
        json!({"id":"inst-2026-11","loan_account_id":"acct-loan-01","from_account_id":"acct-chk-001","date":"2026-11-01","amount_minor":88_849}),
    );
    assert_eq!(balance(&h, "acct-loan-01"), -1_000_000 + 78_849);
    assert_eq!(balance(&h, "acct-chk-001"), 500_000 - 88_849);
    let s = summary(&h, "2026-11-01", "2026-11-30");
    assert_eq!(s["interest_minor"], 10_000);
    assert_eq!(s["net_spending_minor"], 10_000, "principal is not spending");
    assert_eq!(s["income_minor"], 0, "principal arriving on the loan is not income");
    let st = &rows(&h, "loan_status", json!({"account_id":"acct-loan-01","as_of":"2026-11-02"}))[0];
    assert_eq!(st["outstanding_principal_minor"], 921_151);
    assert_eq!(st["schedule"].as_array().unwrap().len(), 11);
    let liab = &rows(&h, "liabilities", json!({"as_of":"2026-11-02"}))[0];
    assert_eq!(liab["totals"][0]["owed_minor"], 921_151);
}

#[test]
fn an_installment_with_no_known_rate_or_more_than_owed_is_refused() {
    let (_d, h, _k) = setup();
    cmd(
        &h,
        "account.create",
        json!({"id":"acct-loan-02","name":"Family loan","kind":"loan","currency":"USD","opening_balance_minor":-50_000}),
    );
    assert_eq!(
        err(
            &h,
            "loan_installment.record",
            json!({"id":"inst-fam-001","loan_account_id":"acct-loan-02","from_account_id":"acct-chk-001","date":"2026-11-01","amount_minor":10_000})
        ),
        "validation",
        "no rate recorded and no interest given: REVA does not guess"
    );
    assert_eq!(
        err(
            &h,
            "loan_installment.record",
            json!({"id":"inst-fam-002","loan_account_id":"acct-loan-02","from_account_id":"acct-chk-001","date":"2026-11-01","amount_minor":60_000,"interest_minor":0})
        ),
        "validation"
    );
    cmd(
        &h,
        "loan_installment.record",
        json!({"id":"inst-fam-003","loan_account_id":"acct-loan-02","from_account_id":"acct-chk-001","date":"2026-11-01","amount_minor":10_000,"interest_minor":0}),
    );
    assert_eq!(balance(&h, "acct-loan-02"), -40_000);
    let st = &rows(&h, "loan_status", json!({"account_id":"acct-loan-02","as_of":"2026-11-02"}))[0];
    assert_eq!(st["complete"], false);
    assert_eq!(st["installment_minor"], Value::Null, "no schedule without rate, term and first due date");
}

#[test]
fn ingesting_the_same_alert_twice_records_one_transaction_and_different_facts_are_refused() {
    let (_d, h, _k) = setup();
    let alert = json!({"account_id":"acct-chk-001","date":"2026-11-11","amount_minor":-4_680,"currency":"USD","description":"FRESH MARKET","merchant":"FRESH MARKET","external_ref":"email:HB-TXN-1001"});
    let first = cmd(&h, "transaction.ingest", alert.clone());
    let events = h.event_count().unwrap();
    let again = cmd(&h, "transaction.ingest", alert.clone());
    assert_eq!(again.aggregate_id, first.aggregate_id);
    assert_eq!(again.event_id, first.event_id);
    assert_eq!(h.event_count().unwrap(), events, "a repeat writes nothing");
    let tx = rows(&h, "list_transactions", json!({"account_id":"acct-chk-001"}));
    assert_eq!(tx.iter().filter(|t| t["external_ref"] == "email:HB-TXN-1001").count(), 1);
    assert_eq!(tx.iter().find(|t| t["external_ref"] == "email:HB-TXN-1001").unwrap()["source"], "email");

    let mut forged = alert.clone();
    forged["amount_minor"] = json!(-9_999);
    assert_eq!(err(&h, "transaction.ingest", forged), "conflict");
    assert_eq!(h.event_count().unwrap(), events);
    assert_eq!(
        err(
            &h,
            "transaction.ingest",
            json!({"account_id":"acct-chk-001","date":"2026-11-11","amount_minor":-1,"description":"x"})
        ),
        "validation",
        "a provenance key is required"
    );
    assert_eq!(
        err(
            &h,
            "transaction.ingest",
            json!({"account_id":"acct-chk-001","date":"2026-11-11","amount_minor":-1,"description":"x","external_ref":"r-1","currency":"EUR"})
        ),
        "validation",
        "no automatic currency conversion"
    );
}

#[test]
fn repeating_a_move_is_a_no_op_and_changing_it_is_refused() {
    let (_d, h, _k) = setup();
    let mv = json!({"id":"mv-repeat-01","from_account_id":"acct-chk-001","to_account_id":"acct-sav-001","date":"2026-10-03","amount_minor":5_000});
    cmd(&h, "internal_move.record", mv.clone());
    let n = h.event_count().unwrap();
    cmd(&h, "internal_move.record", mv.clone());
    assert_eq!(h.event_count().unwrap(), n);
    let mut changed = mv.clone();
    changed["amount_minor"] = json!(6_000);
    assert_eq!(err(&h, "internal_move.record", changed), "conflict");
    assert_eq!(balance(&h, "acct-sav-001"), 5_000);
}

#[test]
fn moves_between_currencies_are_refused_rather_than_converted() {
    let (_d, h, _k) = setup();
    cmd(&h, "account.create", json!({"id":"acct-eur-001","name":"Euro","kind":"checking","currency":"EUR"}));
    assert_eq!(
        err(
            &h,
            "internal_move.record",
            json!({"id":"mv-fx-00001","from_account_id":"acct-chk-001","to_account_id":"acct-eur-001","date":"2026-10-03","amount_minor":5_000})
        ),
        "validation"
    );
    assert_eq!(h.event_count().unwrap(), 6);
}

#[test]
fn linked_legs_are_edited_and_deleted_together() {
    let (_d, h, _k) = setup();
    cmd(
        &h,
        "internal_move.record",
        json!({"id":"mv-linked-01","from_account_id":"acct-chk-001","to_account_id":"acct-sav-001","date":"2026-10-03","amount_minor":5_000}),
    );
    assert_eq!(err(&h, "transaction.update", json!({"id":"mv-linked-01-out","amount_minor":-1})), "conflict");
    cmd(&h, "transaction.update", json!({"id":"mv-linked-01-out","notes":"monthly saving"}));
    cmd(&h, "transaction.delete", json!({"id":"mv-linked-01-in"}));
    assert_eq!(balance(&h, "acct-chk-001"), 500_000);
    assert_eq!(balance(&h, "acct-sav-001"), 0);
    assert_eq!(rows(&h, "list_transactions", json!({})).len(), 0, "both legs went");
}

#[test]
fn a_reconciliation_records_the_difference_and_changes_no_transaction() {
    let (_d, h, _k) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-rec-00001","account_id":"acct-chk-001","date":"2026-10-04","amount_minor":-1_000,"description":"Coffee"}),
    );
    let before = h.event_count().unwrap();
    cmd(
        &h,
        "reconciliation.record",
        json!({"id":"rec-oct-0001","account_id":"acct-chk-001","statement_date":"2026-10-31","statement_balance_minor":498_500}),
    );
    assert_eq!(h.event_count().unwrap(), before + 1);
    let r = &rows(&h, "list_reconciliations", json!({"account_id":"acct-chk-001"}))[0];
    assert_eq!(r["ledger_balance_minor"], 499_000);
    assert_eq!(r["difference_minor"], -500, "the statement shows 5.00 less than REVA knows about");
    assert_eq!(balance(&h, "acct-chk-001"), 499_000);
}

#[test]
fn every_fin3_total_survives_a_projection_rebuild_from_the_event_log() {
    let (_d, h, _k) = setup();
    loan(&h);
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-card-buy4","account_id":"acct-card-01","date":"2026-11-02","amount_minor":-7_000,"description":"Books"}),
    );
    cmd(
        &h,
        "internal_move.record",
        json!({"id":"mv-cardpay-03","from_account_id":"acct-chk-001","to_account_id":"acct-card-01","date":"2026-11-20","amount_minor":7_000}),
    );
    cmd(
        &h,
        "loan_installment.record",
        json!({"id":"inst-2026-11b","loan_account_id":"acct-loan-01","from_account_id":"acct-chk-001","date":"2026-11-01","amount_minor":88_849}),
    );
    cmd(
        &h,
        "transaction.ingest",
        json!({"account_id":"acct-card-01","date":"2026-11-03","amount_minor":-2_000,"description":"Alert","external_ref":"email:AC-2002"}),
    );
    cmd(
        &h,
        "reconciliation.record",
        json!({"id":"rec-nov-0001","account_id":"acct-card-01","statement_date":"2026-11-30","statement_balance_minor":-2_000}),
    );
    let snapshot = |h: &DomainHandle| {
        json!({
            "summary": summary(h, "2026-11-01", "2026-11-30"),
            "card": rows(h, "credit_card_status", json!({"account_id":"acct-card-01","as_of":"2026-11-30"})),
            "loan": rows(h, "loan_status", json!({"account_id":"acct-loan-01","as_of":"2026-11-30"})),
            "liabilities": rows(h, "liabilities", json!({"as_of":"2026-11-30"})),
            "recs": rows(h, "list_reconciliations", json!({})),
            "balances": rows(h, "account_balances", json!({"as_of":"2026-11-30"})),
        })
    };
    let before = snapshot(&h);
    h.rebuild_projections().unwrap();
    assert_eq!(snapshot(&h), before);
}
