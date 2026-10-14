//! The shared Finance conformance suite, run natively.
//! The same `conformance/finance.json` is run through the Python and Kotlin bindings.

mod common;

use std::sync::Arc;

use common::{code, open, MemKeys};
use reva_kernel::{today, DomainHandle};
use serde_json::{json, Value};

fn subset(expected: &Value, actual: &Value, path: &str) -> Result<(), String> {
    match (expected, actual) {
        (Value::Object(e), Value::Object(a)) => {
            for (k, v) in e {
                let av = a.get(k).ok_or_else(|| format!("{path}.{k}: missing in {actual}"))?;
                subset(v, av, &format!("{path}.{k}"))?;
            }
            Ok(())
        }
        (Value::Array(e), Value::Array(a)) => {
            if e.len() != a.len() {
                return Err(format!("{path}: expected {} items, got {}: {actual}", e.len(), a.len()));
            }
            for (i, (ev, av)) in e.iter().zip(a).enumerate() {
                subset(ev, av, &format!("{path}[{i}]"))?;
            }
            Ok(())
        }
        (e, a) if e == a => Ok(()),
        (e, a) => Err(format!("{path}: expected {e}, got {a}")),
    }
}

const VOLATILE: &[&str] = &["version", "created_at", "updated_at"];

fn strip(value: &mut Value) {
    match value {
        Value::Object(map) => {
            for key in VOLATILE {
                map.remove(*key);
            }
            map.values_mut().for_each(strip);
        }
        Value::Array(items) => items.iter_mut().for_each(strip),
        _ => {}
    }
}

fn list(h: &DomainHandle, name: &str) -> Value {
    let params = if name == "list_transactions" { json!({"limit": 1000}) } else { json!({}) };
    let out = h.query(name.to_string(), params.to_string()).unwrap();
    let mut rows: Value = serde_json::from_str(&out.rows_json).unwrap();
    strip(&mut rows);
    rows
}

struct Ctx {
    dir: tempfile::TempDir,
    keys: Arc<MemKeys>,
    handle: Arc<DomainHandle>,
}

fn expect_code(step: &Value, label: &str, got: Option<&reva_kernel::DomainError>) -> Result<bool, String> {
    // Returns Ok(true) when the step expected an error and got the right one.
    match (step.get("expect_error"), got) {
        (Some(want), Some(e)) => {
            if code(e) != want.as_str().unwrap() {
                Err(format!("{label}: expected error {want}, got {e}"))
            } else {
                Ok(true)
            }
        }
        (Some(want), None) => Err(format!("{label}: expected error {want}, but it succeeded")),
        (None, Some(e)) => Err(format!("{label}: unexpected error: {e}")),
        (None, None) => Ok(false),
    }
}

fn run_step(ctx: &mut Ctx, step: &Value, index: usize) -> Result<(), String> {
    let op = step["op"].as_str().unwrap_or("");
    let label = format!("step {index} ({op} {})", step["kind"].as_str().or(step["name"].as_str()).unwrap_or(""));
    match op {
        "command" => {
            let result = ctx.handle.command(step["kind"].as_str().unwrap().to_string(), step["payload"].to_string());
            if expect_code(step, &label, result.as_ref().err())? {
                return Ok(());
            }
            if let (Some(expect), Ok(r)) = (step.get("expect"), &result) {
                let actual = json!({"event_id": r.event_id, "aggregate_id": r.aggregate_id, "version": r.version});
                subset(expect, &actual, "commit").map_err(|m| format!("{label}: {m}"))?;
            }
        }
        "query" => {
            let result = ctx.handle.query(step["name"].as_str().unwrap().to_string(), step["params"].to_string());
            if expect_code(step, &label, result.as_ref().err())? {
                return Ok(());
            }
            let r = result.unwrap();
            if let Some(expect) = step.get("expect_rows") {
                let rows: Value = serde_json::from_str(&r.rows_json).unwrap();
                subset(expect, &rows, "rows").map_err(|m| format!("{label}: {m}"))?;
            }
            if let Some(expect) = step.get("expect_source_ids_sorted") {
                let mut ids = r.source_ids.clone();
                ids.sort();
                if json!(ids) != *expect {
                    return Err(format!("{label}: source ids {ids:?} != {expect}"));
                }
            }
        }
        "today" => {
            let text = today(vec![ctx.handle.clone()], step["as_of"].as_str().map(str::to_string))
                .map_err(|e| format!("{label}: {e}"))?;
            let actual: Value = serde_json::from_str(&text).unwrap();
            subset(&step["expect"], &actual, "today").map_err(|m| format!("{label}: {m}"))?;
        }
        "import" | "import_error" => {
            let before = (ctx.handle.event_count().unwrap(), ctx.handle.projection_digest().unwrap());
            let result = ctx.handle.import_data(
                step["format"].as_str().unwrap().to_string(),
                step["data"].as_str().unwrap().as_bytes().to_vec(),
                step["options"].to_string(),
            );
            if op == "import_error" {
                if !expect_code(step, &label, result.as_ref().err())? {
                    return Err(format!("{label}: import_error step needs expect_error"));
                }
            } else {
                let r = result.map_err(|e| format!("{label}: {e}"))?;
                let rejected: Vec<Value> =
                    r.rejected.iter().map(|x| json!({"row": x.row, "reason": x.reason})).collect();
                let actual = json!({"accepted": r.accepted, "duplicates": r.duplicates, "dry_run": r.dry_run, "rejected": rejected});
                subset(&step["expect"], &actual, "report").map_err(|m| format!("{label}: {m}"))?;
                let rows: Value = serde_json::from_str(&r.rows_json).unwrap();
                let listed = rows.as_array().map(Vec::len).unwrap_or(0);
                let total = (r.accepted + r.duplicates) as usize + r.rejected.len();
                if listed != total {
                    return Err(format!("{label}: row report has {listed} rows but counts add to {total}"));
                }
            }
            if step["check_unchanged"].as_bool().unwrap_or(false) || op == "import_error" {
                let after = (ctx.handle.event_count().unwrap(), ctx.handle.projection_digest().unwrap());
                if before != after {
                    return Err(format!("{label}: state changed but must not have"));
                }
            }
        }
        "reopen" => {
            let digest = ctx.handle.projection_digest().unwrap();
            let events = ctx.handle.event_count().unwrap();
            let keys = ctx.keys.clone();
            ctx.handle = open(ctx.dir.path(), &keys).map_err(|e| format!("{label}: reopen failed: {e}"))?;
            if ctx.handle.projection_digest().unwrap() != digest || ctx.handle.event_count().unwrap() != events {
                return Err(format!("{label}: state differs after reopen"));
            }
        }
        "rebuild_equals_live" => {
            let before = ctx.handle.projection_digest().unwrap();
            let n = ctx.handle.rebuild_projections().unwrap();
            let after = ctx.handle.projection_digest().unwrap();
            if before != after {
                return Err(format!("{label}: rebuilt projections differ from live state after replaying {n} events"));
            }
            if ctx.handle.integrity_check().unwrap() != "ok" {
                return Err(format!("{label}: integrity_check is not ok"));
            }
        }
        "export_roundtrip" => {
            let bytes = ctx.handle.export("json".to_string()).unwrap();
            let dir_b = tempfile::tempdir().unwrap();
            let keys_b = MemKeys::new();
            let b = open(dir_b.path(), &keys_b).map_err(|e| format!("{label}: {e}"))?;
            let r = b
                .import_data("json".to_string(), bytes.clone(), "{}".to_string())
                .map_err(|e| format!("{label}: {e}"))?;
            if !r.rejected.is_empty() || r.accepted == 0 {
                return Err(format!("{label}: round trip import: accepted {}, rejected {:?}", r.accepted, r.rejected));
            }
            for name in [
                "list_accounts",
                "list_categories",
                "list_budgets",
                "list_bills",
                "list_networth_snapshots",
                "list_transactions",
            ] {
                let (x, y) = (list(&ctx.handle, name), list(&b, name));
                if x != y {
                    return Err(format!("{label}: {name} differs after round trip:\n{x}\n{y}"));
                }
            }
            let again = b.import_data("json".to_string(), bytes, json!({"dry_run": true}).to_string()).unwrap();
            if again.accepted != 0 || again.duplicates != r.accepted {
                return Err(format!("{label}: re-importing the same export must be all duplicates"));
            }
            if b.integrity_check().unwrap() != "ok" {
                return Err(format!("{label}: integrity_check on restored install"));
            }
        }
        "export_csv_check" => {
            let text = String::from_utf8(ctx.handle.export("csv".to_string()).unwrap()).unwrap();
            if text.lines().next() != step["expect_header"].as_str() {
                return Err(format!("{label}: csv header was {:?}", text.lines().next()));
            }
            for needle in step["expect_contains"].as_array().unwrap() {
                if !text.contains(needle.as_str().unwrap()) {
                    return Err(format!("{label}: csv missing {needle}"));
                }
            }
        }
        "no_money_movement" => {
            const FORBIDDEN: &[&str] = &[
                "pay",
                "payment",
                "transfer",
                "send",
                "withdraw",
                "purchase",
                "buy",
                "wire",
                "ach",
                "login",
                "credential",
                "password",
                "bank",
            ];
            for name in ctx.handle.command_names() {
                for token in name.split(['.', '_']) {
                    if FORBIDDEN.contains(&token) {
                        return Err(format!("{label}: command {name} looks like money movement"));
                    }
                }
            }
        }
        other => return Err(format!("{label}: unknown op {other}")),
    }
    Ok(())
}

#[test]
fn finance_conformance_native() {
    let suite: Value = serde_json::from_str(include_str!("conformance/finance.json")).unwrap();
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let handle = open(dir.path(), &keys).unwrap();
    let mut ctx = Ctx { dir, keys, handle };
    let steps = suite["steps"].as_array().unwrap();
    let mut failures = Vec::new();
    for (i, step) in steps.iter().enumerate() {
        if let Err(message) = run_step(&mut ctx, step, i) {
            failures.push(message);
        }
    }
    assert!(failures.is_empty(), "{} of {} steps failed:\n{}", failures.len(), steps.len(), failures.join("\n"));
    println!("conformance: {} steps passed", steps.len());
}
