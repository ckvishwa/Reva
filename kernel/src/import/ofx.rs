//! OFX 1.x (SGML) and 2.x (XML) statement parsing. Only `STMTTRN` entries are read.
//! Tolerant of missing closing tags; nothing is fetched from a bank or the network.

use super::{Candidate, ParseOutcome, RowResult};
use crate::civil::Date;
use crate::domains::finance::money;
use crate::error::{DomainError, DomainResult};

fn tag_value(block: &str, tag: &str) -> Option<String> {
    let open = format!("<{tag}>");
    let start = block.to_ascii_uppercase().find(&open)? + open.len();
    let rest = &block[start..];
    let end = rest.find('<').unwrap_or(rest.len());
    let value = rest[..end].trim();
    if value.is_empty() {
        None
    } else {
        Some(value.to_string())
    }
}

/// `YYYYMMDD[HHMMSS[.XXX][[offset:TZ]]]` -> date part.
fn parse_ofx_date(value: &str) -> Option<Date> {
    let digits: String = value.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.len() < 8 {
        return None;
    }
    Date::new(digits[0..4].parse().ok()?, digits[4..6].parse().ok()?, digits[6..8].parse().ok()?)
}

/// The statement currency (`CURDEF`), if present.
pub fn statement_currency(text: &str) -> Option<String> {
    tag_value(text, "CURDEF")
}

pub fn parse(bytes: &[u8], currency: &str) -> DomainResult<ParseOutcome> {
    let text = match String::from_utf8(bytes.to_vec()) {
        Ok(t) => t,
        // OFX 1.x files are commonly Windows-1252.
        Err(_) => bytes.iter().map(|&b| b as char).collect(),
    };
    let upper = text.to_ascii_uppercase();
    if !upper.contains("<OFX>") && !upper.contains("<STMTTRN>") {
        return Err(DomainError::validation("file", "not an OFX file (no <OFX> element)"));
    }
    if let Some(cur) = statement_currency(&text) {
        if cur.to_ascii_uppercase() != currency {
            return Err(DomainError::validation(
                "currency",
                format!("statement is in {cur} but the account uses {currency}"),
            ));
        }
    }

    let mut out = ParseOutcome::default();
    let mut search_from = 0;
    let mut index: u64 = 0;
    while let Some(rel) = upper[search_from..].find("<STMTTRN>") {
        let start = search_from + rel + "<STMTTRN>".len();
        let end = upper[start..]
            .find("</STMTTRN>")
            .map(|e| start + e)
            .unwrap_or_else(|| upper[start..].find("<STMTTRN>").map(|e| start + e).unwrap_or(upper.len()));
        let block = &text[start..end];
        search_from = end;
        index += 1;
        let raw: String = block.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(200).collect();

        let Some(date) = tag_value(block, "DTPOSTED").and_then(|d| parse_ofx_date(&d)) else {
            out.rejected.push(RowResult::rejected(index, "missing or invalid DTPOSTED".to_string(), raw));
            continue;
        };
        let Some(amount_text) = tag_value(block, "TRNAMT") else {
            out.rejected.push(RowResult::rejected(index, "missing TRNAMT".to_string(), raw));
            continue;
        };
        // OFX uses '.' as the decimal separator; tolerate a lone ',' decimal.
        let (dec, thou) = if amount_text.contains('.') {
            ('.', Some(','))
        } else if amount_text.matches(',').count() == 1 {
            (',', None)
        } else {
            ('.', Some(','))
        };
        let amount = match money::parse_decimal(&amount_text, currency, dec, thou) {
            Ok(v) if v != 0 => v,
            Ok(_) => {
                out.rejected.push(RowResult::rejected(index, "amount is zero".to_string(), raw));
                continue;
            }
            Err(reason) => {
                out.rejected.push(RowResult::rejected(index, reason, raw));
                continue;
            }
        };
        let name = tag_value(block, "NAME");
        let memo = tag_value(block, "MEMO");
        let description = match (&name, &memo) {
            (Some(n), _) => n.clone(),
            (None, Some(m)) => m.clone(),
            (None, None) => {
                out.rejected.push(RowResult::rejected(index, "missing NAME and MEMO".to_string(), raw));
                continue;
            }
        };
        out.candidates.push(Candidate {
            row: index,
            date,
            amount_minor: amount,
            description,
            merchant: None,
            category: None,
            notes: if name.is_some() { memo } else { None },
            fitid: tag_value(block, "FITID"),
            raw,
        });
    }
    if index == 0 {
        return Err(DomainError::validation("file", "no transactions (STMTTRN) found"));
    }
    Ok(out)
}
