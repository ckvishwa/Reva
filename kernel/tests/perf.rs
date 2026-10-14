//! AR-DOM-011: query p95 <= 100 ms on 10,000 records. Slow in debug builds, so it is ignored by
//! default. Run:  cargo test -p reva-kernel --release --test perf -- --ignored --nocapture
//! This measures the development PC only; the reference-phone figure is NEEDS_HARDWARE.

mod common;

use std::time::Instant;

use common::{cmd, open, MemKeys};
use serde_json::json;

fn p95(mut samples: Vec<f64>) -> f64 {
    samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
    samples[((samples.len() as f64) * 0.95).ceil() as usize - 1]
}

#[test]
#[ignore = "performance measurement; run with --release --ignored"]
fn queries_stay_under_100ms_p95_with_10k_transactions() {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    for (i, name) in ["Checking", "Savings", "Card", "Cash", "Travel"].iter().enumerate() {
        cmd(&h, "account.create", json!({"id": format!("acct-perf-{i}0"), "name": name, "currency": "USD"}));
    }
    let categories = ["Groceries", "Dining", "Fuel", "Rent", "Utilities", "Health", "Travel", "Gifts", "Fun", "Tools"];
    for (i, name) in categories.iter().enumerate() {
        cmd(&h, "category.create", json!({"id": format!("cat-perf-{i:02}"), "name": name}));
        cmd(
            &h,
            "budget.set",
            json!({"category_id": format!("cat-perf-{i:02}"), "amount_minor": 50_000, "currency": "USD", "start_month": "2026-01"}),
        );
    }
    for i in 0..20 {
        cmd(
            &h,
            "bill.create",
            json!({"id": format!("bill-perf-{i:02}"), "name": format!("Bill {i}"), "amount_minor": 1000 + i, "currency": "USD", "due_date": "2026-10-20", "recurrence": "monthly"}),
        );
    }

    let mut csv = String::from("Date,Memo,Amount,Category\n");
    for n in 0..10_000_u32 {
        let month = 1 + (n % 12);
        let day = 1 + (n % 28);
        let amount = -(100 + i64::from(n % 9000));
        csv.push_str(&format!(
            "2026-{month:02}-{day:02},Purchase number {n} at store {},{}.{:02},{}\n",
            n % 97,
            amount / 100,
            (-amount) % 100,
            categories[(n % 10) as usize]
        ));
    }
    let mapping = json!({"date": "Date", "description": "Memo", "amount": "Amount", "category": "Category"});
    let started = Instant::now();
    let mut accepted = 0;
    for (i, chunk) in csv.lines().skip(1).collect::<Vec<_>>().chunks(2000).enumerate() {
        let body = format!("Date,Memo,Amount,Category\n{}\n", chunk.join("\n"));
        let r = h
            .import_data(
                "csv".into(),
                body.into_bytes(),
                json!({"account_id": format!("acct-perf-{}0", i % 5), "mapping": mapping}).to_string(),
            )
            .unwrap();
        accepted += r.accepted;
    }
    println!("imported {accepted} transactions in {:.2}s", started.elapsed().as_secs_f64());
    assert_eq!(accepted, 10_000);
    assert_eq!(h.integrity_check().unwrap(), "ok");

    let queries: Vec<(&str, serde_json::Value)> = vec![
        ("spend_by_category", json!({"period": "2026-10"})),
        ("spend_by_category", json!({"period": "this_year", "as_of": "2026-10-12"})),
        ("cashflow", json!({"period": "2026"})),
        ("budget_status", json!({"as_of": "2026-10-12"})),
        ("account_balances", json!({"as_of": "2026-12-31"})),
        ("upcoming_bills", json!({"as_of": "2026-10-12", "days": 30})),
        ("list_transactions", json!({"limit": 100})),
        ("list_transactions", json!({"q": "store 42", "limit": 100})),
        ("list_transactions", json!({"account_id": "acct-perf-20", "from": "2026-03-01", "to": "2026-03-31"})),
    ];
    let mut worst = 0.0_f64;
    for (name, params) in &queries {
        let mut samples = Vec::new();
        for _ in 0..40 {
            let t = Instant::now();
            h.query((*name).to_string(), params.to_string()).unwrap();
            samples.push(t.elapsed().as_secs_f64() * 1000.0);
        }
        let value = p95(samples);
        println!("{name:<20} {params:<70} p95 = {value:7.2} ms");
        worst = worst.max(value);
    }
    println!("worst p95 = {worst:.2} ms (target <= 100 ms)");
    assert!(worst <= 100.0, "worst p95 {worst:.2} ms exceeds 100 ms");
}
