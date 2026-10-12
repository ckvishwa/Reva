//! Export Finance data as CSV (transactions, for spreadsheets) or JSON (everything, for
//! restore into a fresh install). Exports are returned to the host as bytes; the Kernel
//! never writes them to disk or sends them anywhere.

use rusqlite::Connection;
use serde_json::{json, Map, Value};

use crate::civil;
use crate::domains::finance::{money, schema};
use crate::error::{DomainError, DomainResult};
use crate::import::json_format::{FORMAT_NAME, FORMAT_VERSION};

pub fn export(conn: &Connection, format: &str) -> DomainResult<Vec<u8>> {
    match format {
        "json" => export_json(conn),
        "csv" => export_csv(conn),
        other => Err(DomainError::validation("format", format!("unsupported export format {other:?}"))),
    }
}

fn export_json(conn: &Connection) -> DomainResult<Vec<u8>> {
    let sections: [(&str, &str, &str); 6] = [
        ("accounts", "account", "ORDER BY id"),
        ("categories", "category", "ORDER BY id"),
        ("budgets", "budget", "ORDER BY id"),
        ("bills", "bill", "ORDER BY id"),
        ("transactions", "transaction", "ORDER BY date, id"),
        ("networth_snapshots", "networth_snapshot", "ORDER BY as_of, id"),
    ];
    let mut doc = Map::new();
    doc.insert("format".to_string(), json!(FORMAT_NAME));
    doc.insert("version".to_string(), json!(FORMAT_VERSION));
    doc.insert("exported_at".to_string(), json!(civil::now_iso()));
    for (key, aggregate_type, order) in sections {
        let rows = schema::select(conn, aggregate_type, order, vec![])?;
        doc.insert(key.to_string(), Value::Array(rows.into_iter().map(Value::Object).collect()));
    }
    Ok(serde_json::to_vec_pretty(&Value::Object(doc))?)
}

fn export_csv(conn: &Connection) -> DomainResult<Vec<u8>> {
    let mut writer = ::csv::WriterBuilder::new().from_writer(Vec::new());
    let header = [
        "id",
        "date",
        "account",
        "account_id",
        "amount",
        "amount_minor",
        "currency",
        "description",
        "merchant",
        "category",
        "notes",
    ];
    writer.write_record(header).map_err(|e| DomainError::internal(e.to_string()))?;
    let mut stmt = conn.prepare(
        "SELECT t.id, t.date, COALESCE(a.name, ''), t.account_id, t.amount_minor, t.currency, t.description,
                COALESCE(t.merchant, ''), COALESCE(c.name, ''), COALESCE(t.notes, '')
           FROM transactions t
           LEFT JOIN accounts a ON a.id = t.account_id
           LEFT JOIN categories c ON c.id = t.category_id
          ORDER BY t.date, t.id",
    )?;
    let mut rows = stmt.query([])?;
    while let Some(r) = rows.next()? {
        let amount_minor: i64 = r.get(4)?;
        let currency: String = r.get(5)?;
        let record = [
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
            money::format_minor(amount_minor, &currency),
            amount_minor.to_string(),
            currency,
            r.get::<_, String>(6)?,
            r.get::<_, String>(7)?,
            r.get::<_, String>(8)?,
            r.get::<_, String>(9)?,
        ];
        // Spreadsheet formula injection guard: a leading = + - @ in text cells is prefixed.
        let safe: Vec<String> = record
            .iter()
            .enumerate()
            .map(|(i, v)| {
                let is_text = matches!(i, 2 | 7 | 8 | 9 | 10);
                if is_text && v.starts_with(['=', '+', '-', '@']) {
                    format!("'{v}")
                } else {
                    v.clone()
                }
            })
            .collect();
        writer.write_record(&safe).map_err(|e| DomainError::internal(e.to_string()))?;
    }
    writer.into_inner().map_err(|e| DomainError::internal(e.to_string()))
}
