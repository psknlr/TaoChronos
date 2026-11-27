//! UTC days and months from a timestamp in milliseconds (the civil calendar of Howard Hinnant's `civil_from_days`):
//! what usage is counted by.  No clock is read here — the caller says when it is.

pub const MINUTE: i64 = 60_000;
pub const HOUR: i64 = 3_600_000;
pub const DAY: i64 = 86_400_000;

/// (year, month, day) of a UTC timestamp.
pub fn civil(ms: i64) -> (i64, u32, u32) {
    let z = ms.div_euclid(DAY) + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (yoe + era * 400 + i64::from(m <= 2), m, d)
}

/// `YYYY-MM-DD`, UTC.
pub fn day(ms: i64) -> String {
    let (y, m, d) = civil(ms);
    format!("{y:04}-{m:02}-{d:02}")
}

/// `YYYY-MM-01`, UTC: the first day of the month.
pub fn month_start(ms: i64) -> String {
    let (y, m, _) = civil(ms);
    format!("{y:04}-{m:02}-01")
}

/// Is this a day as `day` writes it?
pub fn is_day(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 10
        && b[4] == b'-'
        && b[7] == b'-'
        && b.iter().enumerate().all(|(i, c)| i == 4 || i == 7 || c.is_ascii_digit())
}

/// Seconds until the next UTC midnight.
pub fn to_midnight(ms: i64) -> i64 {
    (DAY - ms.rem_euclid(DAY) + 999) / 1000
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn days_and_months() {
        assert_eq!(day(0), "1970-01-01");
        assert_eq!(day(951_782_400_000), "2000-02-29");
        assert_eq!(day(1_795_824_000_000 - 1), "2026-11-27"); // the last millisecond before 2026-11-28 UTC
        assert_eq!(day(1_795_824_000_000), "2026-11-28");
        assert_eq!(month_start(1_795_824_000_000), "2026-11-01");
        assert_eq!(day(-1), "1969-12-31");
        assert!(is_day("2026-11-27") && !is_day("2026-1-27") && !is_day("2026/11/27"));
        assert_eq!(to_midnight(1_795_824_000_000 - 1000), 1);
    }
}
