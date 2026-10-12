//! Calendar arithmetic without a date crate (proleptic Gregorian, UTC).
//!
//! Dates are plain `YYYY-MM-DD` strings in storage and in the API. Only
//! `now_iso()` and `today()` read the system clock; every query that depends on
//! "today" also accepts an explicit `as_of`, so results are reproducible.

use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Date {
    pub year: i32,
    pub month: u32,
    pub day: u32,
}

pub fn is_leap(year: i32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

pub fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if is_leap(year) {
                29
            } else {
                28
            }
        }
        _ => 0,
    }
}

impl Date {
    pub fn new(year: i32, month: u32, day: u32) -> Option<Date> {
        if !(1..=12).contains(&month) || day == 0 || day > days_in_month(year, month) {
            return None;
        }
        if !(1900..=2200).contains(&year) {
            return None;
        }
        Some(Date { year, month, day })
    }

    /// Parse strictly `YYYY-MM-DD`.
    pub fn parse(text: &str) -> Option<Date> {
        let bytes = text.as_bytes();
        if bytes.len() != 10 || bytes[4] != b'-' || bytes[7] != b'-' {
            return None;
        }
        let year: i32 = text.get(0..4)?.parse().ok()?;
        let month: u32 = text.get(5..7)?.parse().ok()?;
        let day: u32 = text.get(8..10)?.parse().ok()?;
        Date::new(year, month, day)
    }

    pub fn to_iso(self) -> String {
        format!("{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }

    /// Days since 1970-01-01 (Howard Hinnant's algorithm).
    pub fn to_days(self) -> i64 {
        let y = i64::from(self.year) - i64::from(self.month <= 2);
        let era = if y >= 0 { y } else { y - 399 } / 400;
        let yoe = y - era * 400;
        let m = i64::from(self.month);
        let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + i64::from(self.day) - 1;
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        era * 146_097 + doe - 719_468
    }

    pub fn from_days(days: i64) -> Date {
        let z = days + 719_468;
        let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
        let doe = z - era * 146_097;
        let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
        let y = yoe + era * 400;
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        let mp = (5 * doy + 2) / 153;
        let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
        let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
        let year = (y + i64::from(m <= 2)) as i32;
        Date { year, month: m, day: d }
    }

    pub fn add_days(self, days: i64) -> Date {
        Date::from_days(self.to_days() + days)
    }

    /// Add calendar months, clamping the day (Jan 31 + 1 month = Feb 28/29).
    pub fn add_months(self, months: i32) -> Date {
        let total = self.year * 12 + (self.month as i32 - 1) + months;
        let year = total.div_euclid(12);
        let month = (total.rem_euclid(12) + 1) as u32;
        let day = self.day.min(days_in_month(year, month));
        Date { year, month, day }
    }

    pub fn first_of_month(self) -> Date {
        Date { year: self.year, month: self.month, day: 1 }
    }

    pub fn last_of_month(self) -> Date {
        Date { year: self.year, month: self.month, day: days_in_month(self.year, self.month) }
    }
}

pub fn now_unix_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

/// RFC 3339 UTC timestamp, millisecond precision.
pub fn now_iso() -> String {
    let ms = now_unix_ms();
    let secs = ms.div_euclid(1000);
    let millis = ms.rem_euclid(1000);
    let date = Date::from_days(secs.div_euclid(86_400));
    let rem = secs.rem_euclid(86_400);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        date.year,
        date.month,
        date.day,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60,
        millis
    )
}

pub fn today() -> Date {
    Date::from_days(now_unix_ms().div_euclid(1000).div_euclid(86_400))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_days() {
        for d in [Date::new(1970, 1, 1).unwrap(), Date::new(2024, 2, 29).unwrap(), Date::new(2026, 10, 12).unwrap()] {
            assert_eq!(Date::from_days(d.to_days()), d);
        }
        assert_eq!(Date::new(1970, 1, 1).unwrap().to_days(), 0);
        assert_eq!(Date::new(2000, 3, 1).unwrap().to_days(), 11_017);
    }

    #[test]
    fn rejects_invalid_dates() {
        assert!(Date::parse("2025-02-29").is_none());
        assert!(Date::parse("2025-13-01").is_none());
        assert!(Date::parse("2025-1-01").is_none());
        assert!(Date::parse("2024-02-29").is_some());
    }

    #[test]
    fn add_months_clamps() {
        assert_eq!(Date::parse("2026-01-31").unwrap().add_months(1).to_iso(), "2026-02-28");
        assert_eq!(Date::parse("2026-11-30").unwrap().add_months(3).to_iso(), "2027-02-28");
        assert_eq!(Date::parse("2026-03-15").unwrap().add_months(-3).to_iso(), "2025-12-15");
    }
}
