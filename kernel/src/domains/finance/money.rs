//! Money is an integer count of minor units plus an ISO 4217 currency code. No floats.

pub fn valid_currency(code: &str) -> bool {
    code.len() == 3 && code.bytes().all(|b| b.is_ascii_uppercase())
}

/// Decimal places of the minor unit.
pub fn exponent(currency: &str) -> u32 {
    match currency {
        "BIF" | "CLP" | "DJF" | "GNF" | "ISK" | "JPY" | "KMF" | "KRW" | "PYG" | "RWF" | "UGX" | "UYI" | "VND"
        | "VUV" | "XAF" | "XOF" | "XPF" => 0,
        "BHD" | "IQD" | "JOD" | "KWD" | "LYD" | "OMR" | "TND" => 3,
        _ => 2,
    }
}

pub const MAX_ABS_MINOR: i64 = 1_000_000_000_000_000; // 10^15

/// Parse a human amount such as `-1,234.50`, `(12.00)`, `$3.99`, `12,50 €` or `45.00 DR`.
/// Extra fractional digits are accepted only if they are zeros: no silent rounding.
pub fn parse_decimal(
    text: &str,
    currency: &str,
    decimal_sep: char,
    thousands_sep: Option<char>,
) -> Result<i64, String> {
    let mut s = text.trim().to_string();
    if s.is_empty() {
        return Err("empty amount".to_string());
    }
    let mut negative = false;
    if s.starts_with('(') && s.ends_with(')') && s.len() > 2 {
        negative = true;
        s = s[1..s.len() - 1].trim().to_string();
    }
    let upper = s.to_uppercase();
    if let Some(stripped) = upper.strip_suffix("DR") {
        negative = true;
        s = stripped.trim().to_string();
    } else if let Some(stripped) = upper.strip_suffix("CR") {
        s = stripped.trim().to_string();
    } else {
        s = upper;
    }
    if let Some(stripped) = s.strip_suffix('-') {
        negative = !negative;
        s = stripped.trim().to_string();
    }
    if let Some(stripped) = s.strip_prefix('-') {
        negative = !negative;
        s = stripped.trim().to_string();
    } else if let Some(stripped) = s.strip_prefix('+') {
        s = stripped.trim().to_string();
    }
    let cleaned: String = s
        .chars()
        .filter(|c| !c.is_whitespace() && !matches!(c, '$' | '€' | '£' | '¥' | '₹') && !c.is_alphabetic())
        .filter(|c| Some(*c) != thousands_sep)
        .collect();
    if cleaned.is_empty() {
        return Err("no digits in amount".to_string());
    }
    let (int_part, frac_part) = match cleaned.split_once(decimal_sep) {
        Some((i, f)) => (i.to_string(), f.to_string()),
        None => (cleaned.clone(), String::new()),
    };
    if int_part.is_empty() && frac_part.is_empty() {
        return Err("no digits in amount".to_string());
    }
    if !int_part.bytes().all(|b| b.is_ascii_digit()) || !frac_part.bytes().all(|b| b.is_ascii_digit()) {
        return Err(format!("not a number: {text:?}"));
    }
    let exp = exponent(currency) as usize;
    let (kept, extra) = if frac_part.len() > exp { frac_part.split_at(exp) } else { (frac_part.as_str(), "") };
    if extra.bytes().any(|b| b != b'0') {
        return Err(format!("more than {exp} decimal places for {currency}"));
    }
    let mut digits = int_part;
    digits.push_str(kept);
    for _ in kept.len()..exp {
        digits.push('0');
    }
    let digits = digits.trim_start_matches('0');
    let magnitude: i64 =
        if digits.is_empty() { 0 } else { digits.parse::<i64>().map_err(|_| "amount too large".to_string())? };
    if magnitude > MAX_ABS_MINOR {
        return Err("amount too large".to_string());
    }
    Ok(if negative { -magnitude } else { magnitude })
}

pub fn format_minor(minor: i64, currency: &str) -> String {
    let exp = exponent(currency);
    let sign = if minor < 0 { "-" } else { "" };
    let abs = minor.unsigned_abs();
    if exp == 0 {
        return format!("{sign}{abs}");
    }
    let base = 10_u64.pow(exp);
    format!("{sign}{}.{:0width$}", abs / base, abs % base, width = exp as usize)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_common_bank_formats() {
        assert_eq!(parse_decimal("-1,234.50", "USD", '.', Some(',')), Ok(-123_450));
        assert_eq!(parse_decimal("(12.00)", "USD", '.', Some(',')), Ok(-1_200));
        assert_eq!(parse_decimal("$3.99", "USD", '.', Some(',')), Ok(399));
        assert_eq!(parse_decimal("12,50", "EUR", ',', Some('.')), Ok(1_250));
        assert_eq!(parse_decimal("45.00 DR", "USD", '.', Some(',')), Ok(-4_500));
        assert_eq!(parse_decimal("45.00 CR", "USD", '.', Some(',')), Ok(4_500));
        assert_eq!(parse_decimal("500", "JPY", '.', Some(',')), Ok(500));
        assert_eq!(parse_decimal("1.234", "KWD", '.', Some(',')), Ok(1_234));
        assert_eq!(parse_decimal("5.", "USD", '.', None), Ok(500));
        assert_eq!(parse_decimal("5.100", "USD", '.', None), Ok(510));
    }

    #[test]
    fn rejects_lossy_or_bad_amounts() {
        assert!(parse_decimal("1.234", "USD", '.', None).is_err());
        assert!(parse_decimal("abc", "USD", '.', None).is_err());
        assert!(parse_decimal("", "USD", '.', None).is_err());
        assert!(parse_decimal("1.2.3", "USD", '.', None).is_err());
        assert!(parse_decimal("99999999999999999999", "USD", '.', None).is_err());
    }

    #[test]
    fn formats_minor_units() {
        assert_eq!(format_minor(-123_450, "USD"), "-1234.50");
        assert_eq!(format_minor(5, "USD"), "0.05");
        assert_eq!(format_minor(500, "JPY"), "500");
        assert_eq!(format_minor(1_234, "KWD"), "1.234");
    }
}
