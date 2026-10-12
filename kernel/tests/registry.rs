//! AR-DOM-006 / ARD-700 section 5: no capability can move money, buy things, or touch bank
//! credentials. These tests inspect the command registry and the source tree.

mod common;

use std::fs;
use std::path::{Path, PathBuf};

use common::{code, open, MemKeys};
use serde_json::json;

const EXPECTED: &[&str] = &[
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

const FORBIDDEN_TOKENS: &[&str] = &[
    "pay",
    "payment",
    "transfer",
    "send",
    "withdraw",
    "withdrawal",
    "purchase",
    "buy",
    "wire",
    "ach",
    "login",
    "credential",
    "password",
    "bank",
    "card",
    "oauth",
    "plaid",
    "token",
];

#[test]
fn the_command_registry_is_exactly_the_reviewed_list() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    let mut actual = h.command_names();
    let mut expected: Vec<String> = EXPECTED.iter().map(|s| s.to_string()).collect();
    actual.sort();
    expected.sort();
    assert_eq!(actual, expected, "a new Finance command must be reviewed here against the no-money-movement rule");
}

#[test]
fn no_command_name_contains_a_money_movement_or_credential_term() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    for name in h.command_names() {
        for token in name.split(['.', '_']) {
            assert!(!FORBIDDEN_TOKENS.contains(&token), "{name} contains forbidden term {token:?}");
        }
    }
}

#[test]
fn money_movement_commands_are_rejected_at_runtime_even_if_asked_for_by_name() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    for kind in [
        "transfer.create",
        "payment.send",
        "bill.pay",
        "account.link_bank",
        "bank.login",
        "card.charge",
        "purchase.create",
        "account.withdraw",
        "shell.run",
    ] {
        let err = h.command(kind.to_string(), "{}".to_string()).unwrap_err();
        assert_eq!(code(&err), "validation", "{kind}");
    }
    assert_eq!(h.event_count().unwrap(), 0, "rejected commands write nothing");
}

#[test]
fn bill_mark_paid_only_records_and_exposes_no_way_to_pay() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    common::cmd(
        &h,
        "account.create",
        json!({"id": "acct-main-1", "name": "Main", "currency": "USD", "opening_balance_minor": 100000}),
    );
    common::cmd(
        &h,
        "bill.create",
        json!({"id": "bill-test-01", "name": "Power", "amount_minor": 5000, "currency": "USD", "due_date": "2026-10-20", "recurrence": "monthly", "account_id": "acct-main-1"}),
    );
    // Unknown fields that would imply paying through a bank are refused.
    for field in ["pay_from_bank", "routing_number", "account_number", "card_number", "password"] {
        let mut payload = json!({"id": "bill-test-01", "paid_date": "2026-10-20"});
        payload[field] = json!("x");
        let err = h.command("bill.mark_paid".into(), payload.to_string()).unwrap_err();
        assert_eq!(code(&err), "validation", "{field}");
    }
    common::cmd(&h, "bill.mark_paid", json!({"id": "bill-test-01", "paid_date": "2026-10-20"}));
    let balance = &common::rows(&h, "account_balances", json!({"as_of": "2026-12-31"}))[0];
    assert_eq!(balance["balance_minor"], 100000, "marking paid without record_transaction changes no balance");
}

fn rust_sources(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            rust_sources(&path, out);
        } else if path.extension().map(|e| e == "rs").unwrap_or(false) {
            out.push(path);
        }
    }
}

#[test]
fn source_tree_has_no_banking_or_payment_vocabulary_in_finance_commands() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/domains/finance");
    let mut files = Vec::new();
    rust_sources(&root, &mut files);
    assert!(!files.is_empty());
    for file in files {
        let text = fs::read_to_string(&file).unwrap().to_lowercase();
        for term in [
            "routing_number",
            "iban",
            "swift",
            "plaid",
            "oauth",
            "stripe",
            "paypal",
            "\"pay\"",
            "wire_transfer",
            "send_money",
        ] {
            assert!(!text.contains(term), "{} mentions {term:?}", file.display());
        }
    }
}
