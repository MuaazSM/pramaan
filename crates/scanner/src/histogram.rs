//! Per-block Shannon entropy (`byte_histogram`), `docs/01-FORENSIC-CORE.md` §4.3.
//!
//! Finds zeroed / wiped / high-entropy (compressed or encrypted) regions:
//! zeroed or highly repetitive blocks score near 0 bits/byte, dense video
//! or compressed data scores near 8.

use rayon::prelude::*;

/// Shannon entropy of `chunk`, in bits per byte (`0.0..=8.0`). Sums byte
/// values in ascending order (`0..=255`) so the result is reproducible
/// across runs and languages up to floating-point rounding.
pub fn entropy(chunk: &[u8]) -> f64 {
    if chunk.is_empty() {
        return 0.0;
    }
    let mut counts = [0u64; 256];
    for &b in chunk {
        counts[b as usize] += 1;
    }
    let total = chunk.len() as f64;
    let mut h = 0.0f64;
    for &c in counts.iter() {
        if c > 0 {
            let p = c as f64 / total;
            h -= p * p.log2();
        }
    }
    h
}

/// Computes `entropy()` for every `block`-byte block of `data[start..end]`
/// (the final block may be shorter), in parallel. Blocks are independent
/// (no overlap is needed, unlike the pattern scanners).
pub fn byte_histogram_bytes(data: &[u8], start: usize, end: usize, block: usize) -> Vec<f64> {
    assert!(block > 0, "block must be positive");
    let end = end.min(data.len());
    if start >= end {
        return Vec::new();
    }
    let n_blocks = (end - start).div_ceil(block);
    (0..n_blocks)
        .into_par_iter()
        .map(|i| {
            let bstart = start + i * block;
            let bend = (bstart + block).min(end);
            entropy(&data[bstart..bend])
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zeroed_block_has_zero_entropy() {
        let data = vec![0u8; 4096];
        let hist = byte_histogram_bytes(&data, 0, data.len(), 1024);
        assert_eq!(hist.len(), 4);
        for h in hist {
            assert_eq!(h, 0.0);
        }
    }

    #[test]
    fn uniform_random_block_has_high_entropy() {
        // Deterministic pseudo-uniform byte sequence exercising all 256 values.
        let data: Vec<u8> = (0..=255u16).cycle().take(65536).map(|v| v as u8).collect();
        let hist = byte_histogram_bytes(&data, 0, data.len(), 65536);
        assert_eq!(hist.len(), 1);
        assert!(
            hist[0] > 7.9,
            "expected near-8-bit entropy, got {}",
            hist[0]
        );
    }

    #[test]
    fn last_block_may_be_shorter() {
        let data = vec![7u8; 1500];
        let hist = byte_histogram_bytes(&data, 0, data.len(), 1024);
        assert_eq!(hist.len(), 2);
    }
}
