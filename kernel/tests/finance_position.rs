//! FIN-4: money lent to and borrowed from people, earnings, and net position. Synthetic data only.

mod common;

use common::{cmd, code, open, rows, MemKeys};
use reva_kernel::DomainHandle;
use serde_json::{json, Value};

fn setup() -> (tempfile::TempDir, std::sync::Arc<DomainHandle>) {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    cmd(
        &h,
        "account.create",
        json!({"id":"acct-chk-001","name":"Checking","kind":"checking","currency":"INR","opening_balance_minor":1_000_000}),
    );
    cmd(
        &h,
        "account.create",
        json!({"id":"acct-card-01","name":"Card","kind":"credit","currency":"INR","opening_balance_minor":0,
               "credit_limit_minor":500_000}),
    );
    cmd(
        &h,
        "account.create",
        json!({"id":"acct-loan-01","name":"Bike loan","kind":"loan","currency":"INR","opening_balance_minor":-300_000,
               "loan_principal_minor":300_000,"apr_bp":1_200,"loan_term_months":12,"loan_first_due":"2026-11-05"}),
    );
    cmd(&h, "category.create", json!({"id":"cat-food-001","name":"Food","kind":"expense"}));
    cmd(&h, "category.create", json!({"id":"cat-sal-0001","name":"Salary","kind":"income"}));
    (dir, h)
}

fn err(h: &DomainHandle, kind: &str, payload: Value) -> &'static str {
    code(&h.command(kind.to_string(), payload.to_string()).unwrap_err())
}

fn balance(h: &DomainHandle, id: &str) -> i64 {
    rows(h, "account_balances", json!({"as_of":"2026-12-31"})).into_iter().find(|b| b["account_id"] == id).unwrap()
        ["balance_minor"]
        .as_i64()
        .unwrap()
}

fn summary(h: &DomainHandle) -> Value {
    rows(h, "period_summary", json!({"from":"2026-11-01","to":"2026-11-30"})).into_iter().next().unwrap()
}

#[test]
fn lending_and_getting_it_back_is_neither_spending_nor_income() {
    let (_d, h) = setup();
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-ravi-01","counterparty":"Ravi","direction":"lent","amount_minor":50_000,
               "date":"2026-11-02","due_date":"2026-11-20","account_id":"acct-chk-001"}),
    );
    assert_eq!(balance(&h, "acct-chk-001"), 950_000, "the money left the account");
    cmd(
        &h,
        "personal_debt.settle",
        json!({"id":"debt-ravi-01","amount_minor":20_000,"date":"2026-11-10","account_id":"acct-chk-001"}),
    );
    assert_eq!(balance(&h, "acct-chk-001"), 970_000);
    let s = summary(&h);
    assert_eq!(s["net_spending_minor"], 0);
    assert_eq!(s["income_minor"], 0);
    assert_eq!(s["excluded_moves"], 2);
    let earned = rows(&h, "earnings_summary", json!({"from":"2026-11-01","to":"2026-11-30","as_of":"2026-11-30"}));
    assert!(earned.is_empty(), "getting money back is not earning: {earned:?}");
    let debts = rows(&h, "list_personal_debts", json!({"as_of":"2026-11-25"}));
    assert_eq!(debts.len(), 1);
    assert_eq!(debts[0]["outstanding_minor"], 30_000);
    assert_eq!(debts[0]["settled_minor"], 20_000);
    assert_eq!(debts[0]["status"], "open");
    assert_eq!(debts[0]["overdue"], true, "due 2026-11-20 and still open on 2026-11-25");
}

#[test]
fn borrowing_and_settling_moves_the_account_the_other_way() {
    let (_d, h) = setup();
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-asha-01","counterparty":"Asha","direction":"borrowed","amount_minor":40_000,
               "date":"2026-11-03","account_id":"acct-chk-001"}),
    );
    assert_eq!(balance(&h, "acct-chk-001"), 1_040_000);
    cmd(
        &h,
        "personal_debt.settle",
        json!({"id":"debt-asha-01","amount_minor":40_000,"date":"2026-11-15","account_id":"acct-chk-001"}),
    );
    assert_eq!(balance(&h, "acct-chk-001"), 1_000_000);
    assert!(rows(&h, "list_personal_debts", json!({})).is_empty(), "settled debts are hidden by default");
    let all = rows(&h, "list_personal_debts", json!({"include_settled": true}));
    assert_eq!(all[0]["status"], "settled");
    let s = summary(&h);
    assert_eq!((s["income_minor"].as_i64(), s["net_spending_minor"].as_i64()), (Some(0), Some(0)));
}

#[test]
fn a_debt_without_an_account_only_changes_what_is_owed() {
    let (_d, h) = setup();
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-dinr-01","counterparty":"Kiran","direction":"lent","amount_minor":1_500,
               "currency":"INR","date":"2026-11-04"}),
    );
    assert_eq!(balance(&h, "acct-chk-001"), 1_000_000);
    assert_eq!(
        err(
            &h,
            "personal_debt.record",
            json!({"id":"debt-nocur-1","counterparty":"X","direction":"lent",
        "amount_minor":100,"date":"2026-11-04"})
        ),
        "validation",
        "currency is needed without an account"
    );
}

#[test]
fn settling_more_than_is_outstanding_is_refused_and_writes_nothing() {
    let (_d, h) = setup();
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-over-01","counterparty":"Ravi","direction":"lent","amount_minor":10_000,
               "currency":"INR","date":"2026-11-02"}),
    );
    let n = h.event_count().unwrap();
    assert_eq!(
        err(&h, "personal_debt.settle", json!({"id":"debt-over-01","amount_minor":10_001,"date":"2026-11-03"})),
        "validation"
    );
    assert_eq!(
        err(&h, "personal_debt.settle", json!({"id":"debt-over-01","amount_minor":0,"date":"2026-11-03"})),
        "validation"
    );
    assert_eq!(
        err(&h, "personal_debt.settle", json!({"id":"debt-over-01","amount_minor":100,"date":"2026-11-01"})),
        "validation",
        "a settlement cannot predate the debt"
    );
    assert_eq!(h.event_count().unwrap(), n);
}

#[test]
fn a_debt_in_another_currency_never_uses_an_account_in_this_one() {
    let (_d, h) = setup();
    assert_eq!(
        err(
            &h,
            "personal_debt.record",
            json!({"id":"debt-usd-001","counterparty":"Sam","direction":"lent","amount_minor":1_000,
                   "currency":"USD","date":"2026-11-02","account_id":"acct-chk-001"})
        ),
        "validation"
    );
}

#[test]
fn a_debt_leg_cannot_be_deleted_alone_but_deleting_the_debt_removes_its_legs() {
    let (_d, h) = setup();
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-del-001","counterparty":"Ravi","direction":"lent","amount_minor":5_000,
               "date":"2026-11-02","account_id":"acct-chk-001"}),
    );
    cmd(
        &h,
        "personal_debt.settle",
        json!({"id":"debt-del-001","amount_minor":1_000,"date":"2026-11-05","account_id":"acct-chk-001"}),
    );
    assert_eq!(err(&h, "transaction.delete", json!({"id":"debt-del-001-open"})), "conflict");
    assert_eq!(err(&h, "transaction.update", json!({"id":"debt-del-001-s1","amount_minor":2_000})), "conflict");
    cmd(&h, "personal_debt.delete", json!({"id":"debt-del-001"}));
    assert_eq!(balance(&h, "acct-chk-001"), 1_000_000, "both legs are gone");
    assert!(rows(&h, "list_personal_debts", json!({"include_settled": true})).is_empty());
}

#[test]
fn repeating_a_debt_or_a_referenced_settlement_writes_nothing_and_different_facts_are_refused() {
    let (_d, h) = setup();
    let debt = json!({"id":"debt-rep-001","counterparty":"Ravi","direction":"lent","amount_minor":9_000,
                      "date":"2026-11-02","account_id":"acct-chk-001"});
    let first = cmd(&h, "personal_debt.record", debt.clone());
    let n = h.event_count().unwrap();
    let again = cmd(&h, "personal_debt.record", debt);
    assert_eq!((again.aggregate_id, again.event_id), (first.aggregate_id, first.event_id));
    assert_eq!(h.event_count().unwrap(), n);
    let settle = json!({"id":"debt-rep-001","amount_minor":3_000,"date":"2026-11-06",
                        "account_id":"acct-chk-001","external_ref":"sms:hdfc:ref-7731"});
    cmd(&h, "personal_debt.settle", settle.clone());
    let n = h.event_count().unwrap();
    cmd(&h, "personal_debt.settle", settle);
    assert_eq!(h.event_count().unwrap(), n, "the same alert seen twice settles once");
    assert_eq!(balance(&h, "acct-chk-001"), 994_000);
    assert_eq!(
        err(
            &h,
            "personal_debt.settle",
            json!({"id":"debt-rep-001","amount_minor":3_500,"date":"2026-11-06",
            "external_ref":"sms:hdfc:ref-7731"})
        ),
        "conflict"
    );
    assert_eq!(
        err(
            &h,
            "personal_debt.record",
            json!({"id":"debt-rep-001","counterparty":"Ravi","direction":"lent",
            "amount_minor":9_999,"date":"2026-11-02"})
        ),
        "conflict"
    );
}

#[test]
fn earnings_count_salary_but_not_moves_refunds_or_debts_and_list_expected_income() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-sal-nov-01","account_id":"acct-chk-001","date":"2026-11-01","amount_minor":250_000,
               "description":"Salary","category_id":"cat-sal-0001"}),
    );
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-refund-001","account_id":"acct-chk-001","date":"2026-11-08","amount_minor":1_200,
               "description":"Food refund","category_id":"cat-food-001"}),
    );
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-gift-0001","account_id":"acct-chk-001","date":"2026-11-09","amount_minor":5_000,
               "description":"Gift"}),
    );
    cmd(
        &h,
        "internal_move.record",
        json!({"id":"move-card-001","from_account_id":"acct-chk-001","to_account_id":"acct-card-01",
               "date":"2026-11-10","amount_minor":10_000}),
    );
    cmd(
        &h,
        "bill.create",
        json!({"id":"bill-salary-1","name":"Salary","kind":"income","amount_minor":250_000,"currency":"INR",
               "recurrence":"monthly","due_date":"2026-12-01","account_id":"acct-chk-001"}),
    );
    let e = rows(&h, "earnings_summary", json!({"from":"2026-11-01","to":"2026-12-31","as_of":"2026-11-15"}));
    assert_eq!(e.len(), 1);
    let e = &e[0];
    assert_eq!(e["received_minor"], 255_000, "salary and the uncategorized gift; not the refund or the move");
    assert_eq!(
        e["by_category"],
        json!([{"category":"Salary","amount_minor":250_000},
                                         {"category":"Uncategorized","amount_minor":5_000}])
    );
    assert_eq!(e["expected_minor"], 250_000, "one more salary before 2026-12-31");
    assert_eq!(e["expected"][0]["date"], "2026-12-01");
}

#[test]
fn net_position_lists_every_debt_and_receivable_per_currency() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id":"tx-card-food1","account_id":"acct-card-01","date":"2026-11-05","amount_minor":-20_000,
               "description":"Dinner","category_id":"cat-food-001"}),
    );
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-net-lent","counterparty":"Ravi","direction":"lent","amount_minor":30_000,
               "date":"2026-11-02","account_id":"acct-chk-001"}),
    );
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-net-borr","counterparty":"Asha","direction":"borrowed","amount_minor":7_000,
               "currency":"INR","date":"2026-11-03"}),
    );
    cmd(
        &h,
        "account.create",
        json!({"id":"acct-usd-001","name":"USD wallet","kind":"cash","currency":"USD","opening_balance_minor":4_000}),
    );
    let p = rows(&h, "net_position", json!({"as_of":"2026-11-30"}));
    assert_eq!(p.len(), 2, "INR and USD are never added together");
    let inr = p.iter().find(|r| r["currency"] == "INR").unwrap();
    assert_eq!(inr["accounts_minor"], 970_000);
    assert_eq!(inr["owed_to_me_minor"], 30_000);
    assert_eq!(inr["cards_owed_minor"], 20_000);
    assert_eq!(inr["loans_owed_minor"], 300_000);
    assert_eq!(inr["i_owe_people_minor"], 7_000);
    assert_eq!(inr["total_debt_minor"], 327_000);
    assert_eq!(inr["net_minor"], 970_000 + 30_000 - 327_000);
    let names: Vec<&str> = inr["debts"].as_array().unwrap().iter().map(|d| d["name"].as_str().unwrap()).collect();
    assert_eq!(names, ["Bike loan", "Card", "Asha"]);
    assert_eq!(inr["receivables"][0]["name"], "Ravi");
    let usd = p.iter().find(|r| r["currency"] == "USD").unwrap();
    assert_eq!(usd["net_minor"], 4_000);
    // Before the debts existed, they are not part of the position.
    let early = rows(&h, "net_position", json!({"as_of":"2026-11-01"}));
    let inr = early.iter().find(|r| r["currency"] == "INR").unwrap();
    assert_eq!((inr["owed_to_me_minor"].as_i64(), inr["i_owe_people_minor"].as_i64()), (Some(0), Some(0)));
}

#[test]
fn rebuilding_from_the_log_reproduces_debts_and_their_legs() {
    let (_d, h) = setup();
    cmd(
        &h,
        "personal_debt.record",
        json!({"id":"debt-rbd-001","counterparty":"Ravi","direction":"lent","amount_minor":8_000,
               "date":"2026-11-02","account_id":"acct-chk-001"}),
    );
    cmd(&h, "personal_debt.settle", json!({"id":"debt-rbd-001","amount_minor":2_000,"date":"2026-11-04"}));
    cmd(&h, "personal_debt.update", json!({"id":"debt-rbd-001","counterparty":"Ravi K","due_date":"2026-12-01"}));
    let before = h.projection_digest().unwrap();
    h.rebuild_projections().unwrap();
    assert_eq!(h.projection_digest().unwrap(), before);
    let d = &rows(&h, "list_personal_debts", json!({}))[0];
    assert_eq!((d["counterparty"].as_str(), d["outstanding_minor"].as_i64()), (Some("Ravi K"), Some(6_000)));
}

#[test]
fn unknown_fields_that_would_imply_contacting_someone_or_a_bank_are_refused() {
    let (_d, h) = setup();
    for field in ["upi_id", "phone", "pay_from_bank", "account_number", "send_reminder"] {
        let mut payload = json!({"id":"debt-unk-001","counterparty":"Ravi","direction":"lent","amount_minor":100,
                                 "currency":"INR","date":"2026-11-02"});
        payload[field] = json!("x");
        assert_eq!(err(&h, "personal_debt.record", payload), "validation", "{field}");
    }
}
