//! Import behaviour beyond the shared suite: encodings, sign conventions, duplicates against
//! manual entries, limits, dry-run purity, export safety.

mod common;

use common::{cmd, code, open, rows, MemKeys};
use reva_kernel::DomainHandle;
use serde_json::{json, Value};

fn setup() -> (tempfile::TempDir, std::sync::Arc<DomainHandle>) {
    let dir = tempfile::tempdir().unwrap();
    let h = open(dir.path(), &MemKeys::new()).unwrap();
    cmd(&h, "account.create", json!({"id": "acct-main-1", "name": "Main", "currency": "USD"}));
    cmd(&h, "category.create", json!({"id": "cat-coffee-1", "name": "Coffee", "aliases": ["cafe"]}));
    (dir, h)
}

fn import(h: &DomainHandle, format: &str, data: &[u8], options: Value) -> reva_kernel::ImportReport {
    h.import_data(format.to_string(), data.to_vec(), options.to_string()).unwrap()
}

fn mapping_amount() -> Value {
    json!({"date": "Date", "description": "Memo", "amount": "Amount"})
}

#[test]
fn utf8_bom_and_quoted_fields_are_handled() {
    let (_d, h) = setup();
    let mut data = vec![0xEF, 0xBB, 0xBF];
    data.extend_from_slice("Date,Memo,Amount\n2026-10-01,\"Coffee, large\",\"-3.50\"\n".as_bytes());
    let r = import(&h, "csv", &data, json!({"account_id": "acct-main-1", "mapping": mapping_amount()}));
    assert_eq!((r.accepted, r.rejected.len()), (1, 0));
    assert_eq!(rows(&h, "list_transactions", json!({}))[0]["description"], "Coffee, large");
}

#[test]
fn latin1_files_need_the_encoding_set_and_are_rejected_clearly_otherwise() {
    let (_d, h) = setup();
    // "Café" in ISO-8859-1.
    let data: Vec<u8> = b"Date,Memo,Amount\n2026-10-01,Caf\xE9,-2.00\n".to_vec();
    let err = h
        .import_data(
            "csv".into(),
            data.clone(),
            json!({"account_id": "acct-main-1", "mapping": mapping_amount()}).to_string(),
        )
        .unwrap_err();
    assert_eq!(code(&err), "validation");
    let mut m = mapping_amount();
    m["encoding"] = json!("latin1");
    let r = import(&h, "csv", &data, json!({"account_id": "acct-main-1", "mapping": m}));
    assert_eq!(r.accepted, 1);
    assert_eq!(rows(&h, "list_transactions", json!({}))[0]["description"], "Café");
}

#[test]
fn sign_conventions_thousands_separators_headerless_files_and_skipped_rows() {
    let (_d, h) = setup();
    // Bank shows spending as positive numbers: invert_sign flips them.
    let a = import(
        &h,
        "csv",
        b"Date,Memo,Amount\n2026-10-01,Spent,\"1,234.50\"\n",
        json!({"account_id": "acct-main-1", "mapping": {"date": "Date", "description": "Memo", "amount": "Amount", "invert_sign": true, "thousands_separator": ","}}),
    );
    assert_eq!(a.accepted, 1);
    assert_eq!(rows(&h, "list_transactions", json!({}))[0]["amount_minor"], -123_450);

    // No header: columns by index; two junk lines at the top.
    let b = import(
        &h,
        "csv",
        b"Statement for Oct\nAccount 1234\n01/10/2026|Rent|(900.00)\n02/10/2026|Refund|15.00\n",
        json!({"account_id": "acct-main-1", "mapping": {"has_header": false, "skip_rows": 2, "delimiter": "|", "date": 0, "date_format": "%d/%m/%Y", "description": 1, "amount": 2}}),
    );
    assert_eq!((b.accepted, b.rejected.len()), (2, 0));
    let all = rows(&h, "list_transactions", json!({"q": "rent"}));
    assert_eq!(all[0]["amount_minor"], -90_000);
}

#[test]
fn rows_with_both_debit_and_credit_or_zero_amounts_are_rejected_with_a_reason() {
    let (_d, h) = setup();
    let r = import(
        &h,
        "csv",
        b"Date,Memo,Debit,Credit\n2026-10-01,Both,5.00,5.00\n2026-10-02,Zero,0.00,\n2026-10-03,Fine,5.00,\n2026-10-04,NoAmount,,\n",
        json!({"account_id": "acct-main-1", "mapping": {"date": "Date", "description": "Memo", "debit": "Debit", "credit": "Credit"}}),
    );
    assert_eq!(r.accepted, 1);
    let reasons: Vec<_> = r.rejected.iter().map(|x| (x.row, x.reason.as_str())).collect();
    assert_eq!(reasons, vec![(2, "both debit and credit are filled"), (3, "amount is zero"), (5, "missing amount")]);
}

#[test]
fn a_manual_entry_and_an_imported_row_are_the_same_transaction_once() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-manual-1", "account_id": "acct-main-1", "date": "2026-10-05", "amount_minor": -450, "description": "Coffee Shop"}),
    );
    let data = b"Date,Memo,Amount\n2026-10-05,COFFEE SHOP,-4.50\n2026-10-05,coffee shop,-4.50\n";
    let r = import(&h, "csv", data, json!({"account_id": "acct-main-1", "mapping": mapping_amount()}));
    // First row matches the manual entry; the second identical row is a genuinely new transaction.
    assert_eq!((r.accepted, r.duplicates), (1, 1));
    let rows_json: Vec<Value> = serde_json::from_str(&r.rows_json).unwrap();
    assert!(rows_json.iter().any(|x| x["status"] == "duplicate" && x["reason"].as_str().unwrap().contains("manual")));
}

#[test]
fn dry_run_is_identical_to_the_real_run_and_changes_nothing() {
    let (_d, h) = setup();
    let data = b"Date,Memo,Amount\n2026-10-01,A,-1.00\n2026-10-02,B,-2.00\n2026-13-45,C,-3.00\n";
    let opts = |dry| json!({"account_id": "acct-main-1", "mapping": mapping_amount(), "dry_run": dry});
    let digest = h.projection_digest().unwrap();
    let events = h.event_count().unwrap();
    let pending = h.pending_events(100).unwrap().count;
    let dry = import(&h, "csv", data, opts(true));
    assert_eq!(h.projection_digest().unwrap(), digest);
    assert_eq!(h.event_count().unwrap(), events);
    assert_eq!(h.pending_events(100).unwrap().count, pending, "no outbox entries either");
    let real = import(&h, "csv", data, opts(false));
    assert_eq!(
        (dry.accepted, dry.duplicates, dry.rejected.len()),
        (real.accepted, real.duplicates, real.rejected.len())
    );
    assert_eq!(dry.accepted, 2);
    assert_ne!(h.projection_digest().unwrap(), digest);
}

#[test]
fn every_row_is_accounted_for() {
    let (_d, h) = setup();
    let mut csv = String::from("Date,Memo,Amount\n");
    for i in 0..200 {
        match i % 4 {
            0 => csv.push_str(&format!("2026-10-01,ok {i},-{}.00\n", i + 1)),
            1 => csv.push_str(&format!("not-a-date,bad date {i},-1.00\n")),
            2 => csv.push_str(&format!("2026-10-02,bad amount {i},abc\n")),
            _ => csv.push_str(&format!("2026-10-03,ok {i},-{}.25\n", i + 1)),
        }
    }
    let r = import(&h, "csv", csv.as_bytes(), json!({"account_id": "acct-main-1", "mapping": mapping_amount()}));
    let all: Vec<Value> = serde_json::from_str(&r.rows_json).unwrap();
    assert_eq!(all.len(), 200, "nothing dropped silently");
    assert_eq!(r.accepted + r.duplicates + r.rejected.len() as u64, 200);
    assert_eq!((r.accepted, r.rejected.len()), (100, 100));
    assert!(r.rejected.iter().all(|x| !x.reason.is_empty()));
}

#[test]
fn limits_and_bad_options_are_validation_errors() {
    let (_d, h) = setup();
    let big = vec![b'x'; 9 * 1024 * 1024];
    let e = h
        .import_data("csv".into(), big, json!({"account_id": "acct-main-1", "mapping": mapping_amount()}).to_string())
        .unwrap_err();
    assert_eq!(code(&e), "validation");
    for options in [
        json!({"mapping": mapping_amount()}),
        json!({"account_id": "acct-main-1"}),
        json!({"account_id": "acct-main-1", "mapping": {"date": "Date", "description": "Memo"}}),
        json!({"account_id": "acct-main-1", "mapping": {"date": "Date", "description": "Memo", "amount": "A", "debit": "D"}}),
        json!({"account_id": "acct-main-1", "mapping": {"date": "Date", "description": "Memo", "amount": "A", "surprise": 1}}),
        json!({"account_id": "acct-main-1", "mapping": {"date": "Date", "description": "Memo", "amount": "A", "delimiter": "ab"}}),
    ] {
        let e = h.import_data("csv".into(), b"Date,Memo,A\n".to_vec(), options.to_string()).unwrap_err();
        assert_eq!(code(&e), "validation", "{options}");
    }
    assert_eq!(code(&h.import_data("xls".into(), vec![1], "{}".into()).unwrap_err()), "validation");
    assert_eq!(
        code(
            &h.import_data("ofx".into(), b"hello".to_vec(), json!({"account_id": "acct-main-1"}).to_string())
                .unwrap_err()
        ),
        "validation"
    );
}

#[test]
fn ofx_xml_style_files_and_comma_decimals_parse() {
    let (_d, h) = setup();
    let ofx = "<?xml version=\"1.0\"?><OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD</CURDEF><BANKTRANLIST>\
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20261001000000[0:GMT]</DTPOSTED><TRNAMT>-7,25</TRNAMT><FITID>X1</FITID><NAME>Lunch</NAME></STMTTRN>\
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20261002</DTPOSTED><TRNAMT>-1,234.50</TRNAMT><FITID>X2</FITID><MEMO>Only memo</MEMO></STMTTRN>\
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>";
    let r = import(&h, "ofx", ofx.as_bytes(), json!({"account_id": "acct-main-1"}));
    assert_eq!((r.accepted, r.rejected.len()), (2, 0));
    let amounts: Vec<i64> =
        rows(&h, "list_transactions", json!({})).iter().map(|x| x["amount_minor"].as_i64().unwrap()).collect();
    assert!(amounts.contains(&-725) && amounts.contains(&-123_450), "{amounts:?}");
}

#[test]
fn csv_export_neutralises_spreadsheet_formulas() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-formula-1", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -100, "description": "=HYPERLINK(\"http://evil\")", "notes": "+1+1"}),
    );
    let text = String::from_utf8(h.export("csv".into()).unwrap()).unwrap();
    assert!(text.contains("'=HYPERLINK"), "{text}");
    assert!(text.contains("'+1+1"));
    assert!(!text.lines().any(|l| l.split(',').any(|c| c.starts_with("=HYPERLINK"))));
}

#[test]
fn csv_export_neutralises_every_text_column_and_tab_or_cr_prefixes() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-formula-2", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -250,
               "description": "\tcmd", "merchant": "@SUM(1)", "notes": "\r=1+1"}),
    );
    cmd(&h, "account.create", json!({"id": "acct-formula-1", "name": "=evil()", "currency": "USD"}));
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-formula-3", "account_id": "acct-formula-1", "date": "2026-10-02", "amount_minor": -500, "description": "plain"}),
    );
    let text = String::from_utf8(h.export("csv".into()).unwrap()).unwrap();
    for cell in ["'\tcmd", "'@SUM(1)", "'\r=1+1", "'=evil()"] {
        assert!(text.contains(cell), "missing {cell:?} in {text}");
    }
    // Amounts stay real numbers, so spreadsheets can still add them up.
    assert!(text.contains(",-2.50,-250,") && text.contains(",-5.00,-500,"), "{text}");
}

#[test]
fn json_export_import_into_a_non_empty_install_reports_duplicates_not_errors() {
    let (_d, h) = setup();
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-one-0001", "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -100, "description": "one", "category": "cafe"}),
    );
    let dump = h.export("json".into()).unwrap();
    let r = h.import_data("json".into(), dump.clone(), "{}".into()).unwrap();
    assert_eq!(r.accepted, 0);
    assert_eq!(r.duplicates, 3, "account, category and transaction already exist");
    let tampered = String::from_utf8(dump).unwrap().replace("reva-finance-export", "other");
    assert_eq!(code(&h.import_data("json".into(), tampered.into_bytes(), "{}".into()).unwrap_err()), "validation");
}

#[test]
fn json_import_rejects_records_that_break_the_rules_with_reasons() {
    let (_d, h) = setup();
    let doc = json!({
        "format": "reva-finance-export", "version": 1,
        "accounts": [
            {"id": "acct-good-01", "name": "Good", "currency": "USD", "kind": "checking", "opening_balance_minor": 0},
            {"id": "acct-bad-001", "name": "Bad currency", "currency": "dollars"}
        ],
        "categories": [],
        "transactions": [
            {"id": "tx-ok-00001", "account_id": "acct-good-01", "date": "2026-10-01", "amount_minor": -5, "currency": "USD", "description": "fine"},
            {"id": "tx-orphan-1", "account_id": "acct-nowhere", "date": "2026-10-01", "amount_minor": -5, "currency": "USD", "description": "orphan"},
            {"id": "tx-baddate1", "account_id": "acct-good-01", "date": "2026-02-30", "amount_minor": -5, "currency": "USD", "description": "bad date"}
        ]
    });
    let r = h.import_data("json".into(), doc.to_string().into_bytes(), "{}".into()).unwrap();
    assert_eq!(r.accepted, 2);
    assert_eq!(r.rejected.len(), 3);
    assert!(r.rejected.iter().all(|x| !x.reason.is_empty()));
}

#[test]
fn ofx_with_non_ascii_text_does_not_misalign_offsets() {
    let (_d, h) = setup();
    // Characters whose Unicode uppercase has a different byte length ("ß" -> "SS", "ŉ" -> "ʼN").
    let ofx = "<OFX><CURDEF>USD<BANKTRANLIST>\
<STMTTRN><DTPOSTED>20261001<TRNAMT>-4.00<FITID>U1<NAME>Straße Café ŉ ß<MEMO>große Rechnung ß ß ß\n\
<STMTTRN><DTPOSTED>20261002<TRNAMT>-5.00<FITID>U2<NAME>Zweite ß Zeile\n</BANKTRANLIST></OFX>";
    let r = import(&h, "ofx", ofx.as_bytes(), json!({"account_id": "acct-main-1"}));
    assert_eq!((r.accepted, r.rejected.len()), (2, 0));
    let descriptions: Vec<String> = rows(&h, "list_transactions", json!({}))
        .iter()
        .map(|x| x["description"].as_str().unwrap().to_string())
        .collect();
    assert!(descriptions.contains(&"Straße Café ŉ ß".to_string()), "{descriptions:?}");
    assert!(descriptions.contains(&"Zweite ß Zeile".to_string()));
}

#[test]
fn json_import_rejects_malformed_carried_fields_and_snapshots() {
    let (_d, h) = setup();
    let doc = json!({
        "format": "reva-finance-export", "version": 1,
        "accounts": [
            {"id": "acct-good-01", "name": "Good", "currency": "USD", "kind": "checking", "opening_balance_minor": 0, "archived": "yes"},
            {"id": "acct-good-02", "name": "Also good", "currency": "USD", "kind": "checking", "opening_balance_minor": 0, "created_at": "not a timestamp"}
        ],
        "bills": [
            {"id": "bill-zero-01", "name": "Zero day", "amount_minor": 100, "currency": "USD", "recurrence": "monthly", "due_date": "2026-11-01", "anchor_day": 0}
        ],
        "transactions": [
            {"id": "tx-badfp-001", "account_id": "acct-good-01", "date": "2026-10-01", "amount_minor": -1, "currency": "USD", "description": "x", "fingerprint": "zz"}
        ],
        "networth_snapshots": [
            {"id": "nw-bad-0001", "as_of": "2026-10-01", "by_currency": {"USD": {"assets_minor": "lots"}}},
            {"id": "nw-bad-0002", "as_of": "2026-10-01", "by_currency": {"usd": {"assets_minor": 1, "liabilities_minor": 0, "net_minor": 1}}},
            {"id": "nw-good-001", "as_of": "2026-10-01", "by_currency": {"USD": {"assets_minor": 1, "liabilities_minor": 0, "net_minor": 1}}}
        ]
    });
    let r = h.import_data("json".into(), doc.to_string().into_bytes(), "{}".into()).unwrap();
    assert_eq!(r.accepted, 1, "only the well-formed snapshot is accepted: {:?}", r.rejected);
    assert_eq!(r.rejected.len(), 6);
    assert_eq!(rows(&h, "list_accounts", json!({})).len(), 1, "only the account from setup()");
    assert_eq!(rows(&h, "list_bills", json!({})).len(), 0);
}
