//! Bank CSV parsing with a configurable column mapping (one mapping per bank).

use serde::Deserialize;
use serde_json::Value;

use super::{Candidate, ParseOutcome, RowResult};
use crate::civil::Date;
use crate::domains::finance::money;
use crate::error::{DomainError, DomainResult};

/// A column is addressed by header name (case-insensitive) or by zero-based index.
#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
pub enum ColRef {
    Index(usize),
    Name(String),
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Mapping {
    pub date: ColRef,
    #[serde(default = "default_date_format")]
    pub date_format: String,
    pub description: ColRef,
    /// Signed amount column. Use either `amount` or `debit` + `credit`.
    pub amount: Option<ColRef>,
    pub debit: Option<ColRef>,
    pub credit: Option<ColRef>,
    pub category: Option<ColRef>,
    pub merchant: Option<ColRef>,
    pub notes: Option<ColRef>,
    #[serde(default = "default_true")]
    pub has_header: bool,
    #[serde(default = "default_delimiter")]
    pub delimiter: String,
    #[serde(default = "default_dot")]
    pub decimal_separator: String,
    #[serde(default)]
    pub thousands_separator: Option<String>,
    /// Some banks show money leaving the account as positive numbers.
    #[serde(default)]
    pub invert_sign: bool,
    #[serde(default)]
    pub skip_rows: usize,
    /// `utf-8` (default) or `latin1`.
    #[serde(default = "default_encoding")]
    pub encoding: String,
}

fn default_date_format() -> String {
    "%Y-%m-%d".to_string()
}
fn default_true() -> bool {
    true
}
fn default_delimiter() -> String {
    ",".to_string()
}
fn default_dot() -> String {
    ".".to_string()
}
fn default_encoding() -> String {
    "utf-8".to_string()
}

/// Parse a date with a strptime-like format: %Y %y %m %d %b (Jan) %B (January), other
/// characters must match literally.
pub fn parse_date_with(text: &str, format: &str) -> Option<Date> {
    const MONTHS: [&str; 12] = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ];
    let t: Vec<char> = text.trim().chars().collect();
    let f: Vec<char> = format.chars().collect();
    let (mut ti, mut fi) = (0, 0);
    let (mut year, mut month, mut day) = (None::<i32>, None::<u32>, None::<u32>);
    let take_digits = |ti: &mut usize, min: usize, max: usize| -> Option<u32> {
        let start = *ti;
        while *ti < t.len() && *ti - start < max && t[*ti].is_ascii_digit() {
            *ti += 1;
        }
        if *ti - start < min {
            return None;
        }
        t[start..*ti].iter().collect::<String>().parse().ok()
    };
    while fi < f.len() {
        if f[fi] == '%' && fi + 1 < f.len() {
            match f[fi + 1] {
                'Y' => year = Some(take_digits(&mut ti, 4, 4)? as i32),
                'y' => {
                    let yy = take_digits(&mut ti, 2, 2)? as i32;
                    year = Some(if yy >= 70 { 1900 + yy } else { 2000 + yy });
                }
                'm' => month = Some(take_digits(&mut ti, 1, 2)?),
                'd' => day = Some(take_digits(&mut ti, 1, 2)?),
                'b' | 'B' => {
                    let rest: String = t[ti..].iter().collect::<String>().to_lowercase();
                    let mut found = None;
                    for (i, name) in MONTHS.iter().enumerate() {
                        let full = f[fi + 1] == 'B';
                        let candidate = if full { name } else { &name[..3] };
                        if rest.starts_with(candidate) {
                            found = Some((i as u32 + 1, candidate.len()));
                            break;
                        }
                    }
                    let (m, len) = found?;
                    month = Some(m);
                    ti += len;
                }
                other => {
                    if t.get(ti) != Some(&other) {
                        return None;
                    }
                    ti += 1;
                }
            }
            fi += 2;
        } else {
            if t.get(ti) != Some(&f[fi]) {
                return None;
            }
            ti += 1;
            fi += 1;
        }
    }
    if ti != t.len() {
        return None;
    }
    Date::new(year?, month?, day?)
}

fn decode(bytes: &[u8], encoding: &str) -> DomainResult<String> {
    let bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF][..]).unwrap_or(bytes);
    match encoding {
        "utf-8" | "utf8" => String::from_utf8(bytes.to_vec()).map_err(|_| {
            DomainError::validation("file", "not valid UTF-8; set mapping.encoding to \"latin1\" if the bank uses it")
        }),
        "latin1" | "iso-8859-1" | "windows-1252" => Ok(bytes.iter().map(|&b| b as char).collect()),
        other => Err(DomainError::validation("mapping.encoding", format!("unsupported encoding {other:?}"))),
    }
}

fn resolve(col: &ColRef, header: &Option<Vec<String>>, what: &str) -> DomainResult<usize> {
    match col {
        ColRef::Index(i) => Ok(*i),
        ColRef::Name(name) => {
            let header = header.as_ref().ok_or_else(|| {
                DomainError::validation(format!("mapping.{what}"), "column names need has_header = true")
            })?;
            let wanted = name.trim().to_lowercase();
            header
                .iter()
                .position(|h| h.trim().to_lowercase() == wanted)
                .ok_or_else(|| DomainError::validation(format!("mapping.{what}"), format!("no column named {name:?}")))
        }
    }
}

fn single_char(value: &str, what: &str) -> DomainResult<char> {
    let mut it = value.chars();
    match (it.next(), it.next()) {
        (Some(c), None) => Ok(c),
        _ => Err(DomainError::validation(format!("mapping.{what}"), "must be a single character")),
    }
}

pub fn parse(bytes: &[u8], mapping_json: &Value, currency: &str) -> DomainResult<ParseOutcome> {
    let mapping: Mapping =
        serde_json::from_value(mapping_json.clone()).map_err(|e| DomainError::validation("mapping", e.to_string()))?;
    if mapping.amount.is_none() && mapping.debit.is_none() && mapping.credit.is_none() {
        return Err(DomainError::validation("mapping", "set `amount`, or `debit` and/or `credit`"));
    }
    if mapping.amount.is_some() && (mapping.debit.is_some() || mapping.credit.is_some()) {
        return Err(DomainError::validation("mapping", "use either `amount` or `debit`/`credit`, not both"));
    }
    let delimiter = single_char(&mapping.delimiter, "delimiter")?;
    if !delimiter.is_ascii() {
        return Err(DomainError::validation("mapping.delimiter", "must be ASCII"));
    }
    let dec = single_char(&mapping.decimal_separator, "decimal_separator")?;
    let thou = match &mapping.thousands_separator {
        Some(s) => Some(single_char(s, "thousands_separator")?),
        None => None,
    };
    let text = decode(bytes, &mapping.encoding)?;

    let mut reader = ::csv::ReaderBuilder::new()
        .delimiter(delimiter as u8)
        .has_headers(false)
        .flexible(true)
        .from_reader(text.as_bytes());

    let mut records = reader.records();
    let mut line_no: u64 = 0;
    for _ in 0..mapping.skip_rows {
        if records.next().is_some() {
            line_no += 1;
        }
    }
    let mut header: Option<Vec<String>> = None;
    if mapping.has_header {
        match records.next() {
            Some(Ok(rec)) => {
                line_no += 1;
                header = Some(rec.iter().map(str::to_string).collect());
            }
            Some(Err(e)) => return Err(DomainError::validation("file", format!("unreadable header: {e}"))),
            None => return Err(DomainError::validation("file", "empty file")),
        }
    }
    let date_i = resolve(&mapping.date, &header, "date")?;
    let desc_i = resolve(&mapping.description, &header, "description")?;
    let amount_i = mapping.amount.as_ref().map(|c| resolve(c, &header, "amount")).transpose()?;
    let debit_i = mapping.debit.as_ref().map(|c| resolve(c, &header, "debit")).transpose()?;
    let credit_i = mapping.credit.as_ref().map(|c| resolve(c, &header, "credit")).transpose()?;
    let category_i = mapping.category.as_ref().map(|c| resolve(c, &header, "category")).transpose()?;
    let merchant_i = mapping.merchant.as_ref().map(|c| resolve(c, &header, "merchant")).transpose()?;
    let notes_i = mapping.notes.as_ref().map(|c| resolve(c, &header, "notes")).transpose()?;

    let mut out = ParseOutcome::default();
    for record in records {
        line_no += 1;
        let rec = match record {
            Ok(r) => r,
            Err(e) => {
                out.rejected.push(RowResult::rejected(line_no, format!("unreadable row: {e}"), String::new()));
                continue;
            }
        };
        let raw = rec.iter().collect::<Vec<_>>().join(&mapping.delimiter);
        if rec.iter().all(|f| f.trim().is_empty()) {
            continue; // blank line
        }
        let get = |i: usize| rec.get(i).map(str::trim).filter(|s| !s.is_empty());
        let date = match get(date_i).and_then(|s| parse_date_with(s, &mapping.date_format)) {
            Some(d) => d,
            None => {
                out.rejected.push(RowResult::rejected(
                    line_no,
                    format!("date does not match {}", mapping.date_format),
                    raw,
                ));
                continue;
            }
        };
        let Some(description) = get(desc_i) else {
            out.rejected.push(RowResult::rejected(line_no, "missing description".to_string(), raw));
            continue;
        };
        let amount = (|| -> Result<i64, String> {
            if let Some(i) = amount_i {
                let text = get(i).ok_or_else(|| "missing amount".to_string())?;
                let v = money::parse_decimal(text, currency, dec, thou)?;
                return Ok(v);
            }
            let debit = debit_i.and_then(&get).map(|s| money::parse_decimal(s, currency, dec, thou)).transpose()?;
            let credit = credit_i.and_then(&get).map(|s| money::parse_decimal(s, currency, dec, thou)).transpose()?;
            match (debit, credit) {
                (Some(d), None) => Ok(-d.abs()),
                (None, Some(c)) => Ok(c.abs()),
                (Some(0), Some(c)) => Ok(c.abs()),
                (Some(d), Some(0)) => Ok(-d.abs()),
                (Some(_), Some(_)) => Err("both debit and credit are filled".to_string()),
                (None, None) => Err("missing amount".to_string()),
            }
        })();
        let mut amount = match amount {
            Ok(v) => v,
            Err(reason) => {
                out.rejected.push(RowResult::rejected(line_no, reason, raw));
                continue;
            }
        };
        if mapping.invert_sign && amount_i.is_some() {
            amount = -amount;
        }
        if amount == 0 {
            out.rejected.push(RowResult::rejected(line_no, "amount is zero".to_string(), raw));
            continue;
        }
        out.candidates.push(Candidate {
            row: line_no,
            date,
            amount_minor: amount,
            description: description.to_string(),
            merchant: merchant_i.and_then(&get).map(str::to_string),
            category: category_i.and_then(&get).map(str::to_string),
            notes: notes_i.and_then(&get).map(str::to_string),
            fitid: None,
            raw,
        });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_date_formats() {
        assert_eq!(parse_date_with("2026-10-05", "%Y-%m-%d").unwrap().to_iso(), "2026-10-05");
        assert_eq!(parse_date_with("05/10/2026", "%d/%m/%Y").unwrap().to_iso(), "2026-10-05");
        assert_eq!(parse_date_with("10/05/26", "%m/%d/%y").unwrap().to_iso(), "2026-10-05");
        assert_eq!(parse_date_with("5 Oct 2026", "%d %b %Y").unwrap().to_iso(), "2026-10-05");
        assert_eq!(parse_date_with("5 October 2026", "%d %B %Y").unwrap().to_iso(), "2026-10-05");
        assert!(parse_date_with("31/02/2026", "%d/%m/%Y").is_none());
        assert!(parse_date_with("2026-10-05 extra", "%Y-%m-%d").is_none());
    }
}
