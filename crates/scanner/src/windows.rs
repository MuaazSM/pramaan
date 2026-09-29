//! Shared window partitioning for the parallel scanners.
//!
//! `docs/01-FORENSIC-CORE.md` §4.3: "Parallel over 64 MiB windows with
//! overlap = max pattern length." Each scanner partitions `[start, end)`
//! into non-overlapping *core* ranges of at most `window` bytes; a match is
//! attributed to the core range that contains its start offset. To find
//! matches that straddle a core boundary, callers search an *extended*
//! slice that additionally covers `overlap` bytes past the core's end, then
//! discard any hit whose start offset falls outside the core range (it will
//! be found again, without duplication, by the following window whose core
//! begins exactly where this one's overlap does).

/// Default window size: 64 MiB, per spec.
pub const DEFAULT_WINDOW: usize = 64 * 1024 * 1024;

/// Partition `[start, end)` into consecutive, non-overlapping core ranges of
/// at most `window` bytes each. Returns an empty vec if `start >= end`.
pub fn core_windows(start: usize, end: usize, window: usize) -> Vec<(usize, usize)> {
    assert!(window > 0, "window must be positive");
    let mut out = Vec::new();
    if start >= end {
        return out;
    }
    let mut s = start;
    while s < end {
        let e = (s + window).min(end);
        out.push((s, e));
        s = e;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn partitions_cover_the_range_exactly_once() {
        let windows = core_windows(0, 100, 30);
        assert_eq!(windows, vec![(0, 30), (30, 60), (60, 90), (90, 100)]);
    }

    #[test]
    fn empty_range_yields_no_windows() {
        assert_eq!(core_windows(10, 10, 30), Vec::new());
        assert_eq!(core_windows(10, 5, 30), Vec::new());
    }

    #[test]
    fn single_window_when_smaller_than_window_size() {
        assert_eq!(core_windows(0, 5, 30), vec![(0, 5)]);
    }
}
