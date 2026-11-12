//! Finance recurring and net-worth reports, exact integer totals, and identical totals after a JSON
//! backup is restored into a fresh install.

mod common;

use common::{cmd, code, open, rows, MemKeys};
use reva_kernel::DomainHandle;
use serde_json::{json, Value};

fn seed(h: &DomainHandle) {
    cmd(
        h,
        "account.create",
        json!({"id":"acct-check-1","name":"Checking","currency":"USD","opening_balance_minor":250_000}),
    );
    cmd(
        h,
        "account.create",
        json!({"id":"acct-card-01","name":"Card","kind":"credit","currency":"USD","opening_balance_minor":-40_000}),
    );
    cmd(
        h,
        "account.create",
        json!({"id":"acct-eur-001","name":"Euro","currency":"EUR","opening_balance_minor":10_000}),
    );
    cmd(h, "category.create", json!({"id":"cat-food-001","name":"Food","kind":"expense"}));
    cmd(h, "category.create", json!({"id":"cat-move-001","name":"Move","kind":"transfer"}));
    for (id, account, date, amount, category) in [
        ("tx-salary-01", "acct-check-1", "2026-10-01", 300_000, None),
        ("tx-food-0001", "acct-check-1", "2026-10-03", -1_999, Some("cat-food-001")),
        ("tx-food-0002", "acct-card-01", "2026-10-04", -3_001, Some("cat-food-001")),
        ("tx-refund-01", "acct-card-01", "2026-10-05", 1_000, Some("cat-food-001")),
        ("tx-move-0001", "acct-check-1", "2026-10-06", -20_000, Some("cat-move-001")),
        ("tx-move-0002", "acct-card-01", "2026-10-06", 20_000, Some("cat-move-001")),
        ("tx-euro-0001", "acct-eur-001", "2026-10-07", -500, None),
    ] {
        let mut payload = json!({"id":id,"account_id":account,"date":date,"amount_minor":amount,"description":id});
        if let Some(c) = category {
            payload["category_id"] = json!(c);
        }
        cmd(h, "transaction.create", payload);
    }
    for (id, kind, amount, currency, recurrence, due) in [
        ("bill-rent-01", "bill", 120_000, "USD", "monthly", "2026-11-01"),
        ("bill-gym-001", "subscription", 999, "USD", "monthly", "2026-10-25"),
        ("bill-water-1", "bill", 4_500, "USD", "quarterly", "2026-12-15"),
        ("bill-paper-1", "subscription", 250, "USD", "weekly", "2026-10-21"),
        ("bill-insur-1", "bill", 60_000, "USD", "yearly", "2027-03-01"),
        ("bill-once-01", "bill", 7_777, "USD", "once", "2026-10-22"),
        ("inc-salary-1", "income", 300_000, "USD", "biweekly", "2026-10-30"),
        ("bill-eur-001", "subscription", 1_299, "EUR", "monthly", "2026-10-20"),
    ] {
        cmd(
            h,
            "bill.create",
            json!({"id":id,"name":id,"kind":kind,"amount_minor":amount,"currency":currency,"recurrence":recurrence,"due_date":due}),
        );
    }
    cmd(h, "networth_snapshot.create", json!({"id":"nw-2026-10-0","as_of":"2026-10-02"}));
    cmd(h, "networth_snapshot.create", json!({"id":"nw-2026-10-1","as_of":"2026-10-07"}));
}

fn setup() -> (tempfile::TempDir, std::sync::Arc<DomainHandle>) {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    seed(&h);
    (dir, h)
}

fn by_currency(list: Vec<Value>) -> std::collections::BTreeMap<String, Value> {
    list.into_iter().map(|r| (r["currency"].as_str().unwrap().to_string(), r)).collect()
}

#[test]
fn recurring_summary_gives_exact_yearly_totals_and_excludes_one_off_bills() {
    let (_d, h) = setup();
    let out = by_currency(rows(&h, "recurring_summary", json!({"as_of":"2026-10-19"})));
    let usd = &out["USD"];
    // 120000*12 + 999*12 + 4500*4 + 250*52 + 60000*1 = 1_440_000 + 11_988 + 18_000 + 13_000 + 60_000
    assert_eq!(usd["yearly_outgoing_minor"], 1_542_988);
    assert_eq!(usd["yearly_income_minor"], 300_000 * 26);
    assert_eq!(usd["yearly_net_minor"], 300_000 * 26 - 1_542_988);
    // Due by 2026-11-18: rent, gym and paper (outgoing), salary (income). The one-off bill is not recurring.
    assert_eq!(usd["due_soon_outgoing_minor"], 120_000 + 999 + 250);
    assert_eq!(usd["due_soon_income_minor"], 300_000);
    assert_eq!(usd["items"].as_array().unwrap().len(), 6);
    assert!(usd["items"].as_array().unwrap().iter().all(|i| i["id"] != "bill-once-01"));
    assert_eq!(out["EUR"]["yearly_outgoing_minor"], 1_299 * 12, "currencies are never mixed");

    cmd(&h, "bill.update", json!({"id":"bill-gym-001","active":false}));
    let after = by_currency(rows(&h, "recurring_summary", json!({"as_of":"2026-10-19"})));
    assert_eq!(after["USD"]["yearly_outgoing_minor"], 1_542_988 - 999 * 12, "inactive bills drop out");
    assert_eq!(code(&h.query("recurring_summary".into(), json!({"days":400}).to_string()).unwrap_err()), "validation");
}

#[test]
fn networth_report_shows_live_totals_and_change_between_snapshots() {
    let (_d, h) = setup();
    let report = rows(&h, "networth_report", json!({"as_of":"2026-10-19"})).remove(0);
    // Checking 250000+300000-1999-20000; card -40000-3001+1000+20000; transfers move money, never create it.
    let usd = &report["current"]["USD"];
    assert_eq!(usd["assets_minor"], 528_001);
    assert_eq!(usd["liabilities_minor"], 22_001);
    assert_eq!(usd["net_minor"], 506_000);
    assert_eq!(report["current"]["EUR"]["net_minor"], 9_500);
    let history = report["history"].as_array().unwrap();
    assert_eq!(history.len(), 2);
    assert_eq!(history[0]["by_currency"]["USD"]["net_minor"], 510_000);
    assert_eq!(history[0]["by_currency"]["USD"]["change_minor"], Value::Null, "no earlier snapshot");
    assert_eq!(history[1]["by_currency"]["USD"]["net_minor"], 506_000);
    assert_eq!(history[1]["by_currency"]["USD"]["change_minor"], -4_000);
}

#[test]
fn cashflow_is_exact_and_transfers_are_neither_income_nor_spending() {
    let (_d, h) = setup();
    let flow = by_currency(rows(&h, "cashflow", json!({"period":"2026-10","as_of":"2026-10-19"})));
    assert_eq!(flow["USD"]["income_minor"], 301_000, "the refund counts as money in");
    assert_eq!(flow["USD"]["expense_minor"], 5_000);
    assert_eq!(flow["EUR"]["expense_minor"], 500);
    let spend = rows(&h, "spend_by_category", json!({"period":"2026-10","as_of":"2026-10-19"}));
    let food = spend.iter().find(|r| r["category_id"] == "cat-food-001").unwrap();
    // Spending is gross outflow: the refund is money in (counted in cashflow income above), not negative spend.
    assert_eq!(food["spent_minor"], 5_000, "1999 + 3001");
    assert_eq!(food["transactions"], 2);
    assert!(spend.iter().all(|r| r["category_id"] != "cat-move-001"), "transfers are not spending");
}

#[test]
fn every_total_is_identical_after_restoring_a_backup_into_a_fresh_install() {
    let (_d, a) = setup();
    let backup = a.export("json".into()).unwrap();
    let dir = tempfile::tempdir().unwrap();
    let b = open(dir.path(), &MemKeys::new()).unwrap();
    let report = b.import_data("json".into(), backup, "{}".into()).unwrap();
    assert!(report.rejected.is_empty(), "{:?}", report.rejected);
    assert_eq!(a.projection_digest().unwrap(), b.projection_digest().unwrap());
    for (name, params) in [
        ("recurring_summary", json!({"as_of":"2026-10-19"})),
        ("networth_report", json!({"as_of":"2026-10-19"})),
        ("cashflow", json!({"period":"2026-10","as_of":"2026-10-19"})),
        ("spend_by_category", json!({"period":"2026-10","as_of":"2026-10-19"})),
        ("account_balances", json!({"as_of":"2026-10-19"})),
        ("upcoming_bills", json!({"as_of":"2026-10-19","days":60})),
        ("budget_status", json!({"month":"2026-10"})),
    ] {
        assert_eq!(rows(&a, name, params.clone()), rows(&b, name, params), "{name} differs after restore");
    }
}
