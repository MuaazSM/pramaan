//! Multi-pattern signature scanning (`scan_signatures`), `docs/01-FORENSIC-CORE.md` §4.3.

use aho_corasick::AhoCorasick;
use rayon::prelude::*;

use crate::windows::core_windows;

/// A signature hit: `(pattern_idx, offset)`, matching the pattern's index in
/// the input `patterns` list and the absolute byte offset of the match's
/// first byte within `data`.
pub type SignatureHit = (usize, u64);

/// Scans `data[start..end]` for every pattern in `patterns`, in parallel
/// over `window`-byte windows overlapped by `max(pattern lengths) - 1`
/// bytes so matches spanning a window boundary are never missed or
/// double-counted. Results are sorted by `(offset, pattern_idx)`.
pub fn scan_signatures_bytes(
    data: &[u8],
    patterns: &[Vec<u8>],
    start: usize,
    end: usize,
    window: usize,
) -> Vec<SignatureHit> {
    let end = end.min(data.len());
    if patterns.is_empty() || start >= end {
        return Vec::new();
    }
    let overlap = patterns
        .iter()
        .map(|p| p.len())
        .max()
        .unwrap_or(1)
        .saturating_sub(1);
    let ac = AhoCorasick::new(patterns).expect("valid Aho-Corasick pattern set");

    let mut hits: Vec<SignatureHit> = core_windows(start, end, window)
        .into_par_iter()
        .flat_map_iter(|(core_start, core_end)| {
            let search_end = (core_end + overlap).min(end);
            let slice = &data[core_start..search_end];
            ac.find_iter(slice).filter_map(move |m| {
                let abs_offset = core_start + m.start();
                if abs_offset < core_end {
                    Some((m.pattern().as_usize(), abs_offset as u64))
                } else {
                    None
                }
            })
        })
        .collect();
    hits.sort_unstable();
    hits
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_a_simple_signature() {
        let data = b"xxxHELLOxxxWORLDxxx".to_vec();
        let hits = scan_signatures_bytes(
            &data,
            &[b"HELLO".to_vec(), b"WORLD".to_vec()],
            0,
            data.len(),
            1024,
        );
        assert_eq!(hits, vec![(0, 3), (1, 11)]);
    }

    #[test]
    fn finds_matches_spanning_a_window_boundary() {
        let mut data = vec![b'x'; 100];
        data[48..48 + 8].copy_from_slice(b"BOUNDARY");
        let hits = scan_signatures_bytes(&data, &[b"BOUNDARY".to_vec()], 0, data.len(), 50);
        assert_eq!(hits, vec![(0, 48)]);
    }

    #[test]
    fn respects_start_and_end() {
        let data = b"AAAA needle AAAA needle AAAA".to_vec();
        let hits = scan_signatures_bytes(&data, &[b"needle".to_vec()], 0, 15, 1024);
        assert_eq!(hits, vec![(0, 5)]);
    }

    #[test]
    fn empty_patterns_yield_no_hits() {
        let data = b"anything".to_vec();
        assert!(scan_signatures_bytes(&data, &[], 0, data.len(), 1024).is_empty());
    }
}
