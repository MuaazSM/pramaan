//! Pramaan scanner: disk-speed signature and NAL search.
//!
//! This crate is a placeholder skeleton created by task W0.1 (monorepo
//! scaffold). Task C1 (Wave 1) fills in `scan_signatures`, `scan_annexb`
//! and `byte_histogram`, plus the PyO3/maturin bindings. A pure-Python
//! backend with the same interface lives in `packages/core` and is always
//! kept in parity per `docs/01-FORENSIC-CORE.md` §4.3 — the Rust build is
//! optional at runtime.

/// Returns the crate name; exists only so `cargo build`/`cargo test`
/// have something real to compile and check in CI before C1 lands.
pub fn crate_name() -> &'static str {
    "pramaan_scanner"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crate_name_is_stable() {
        assert_eq!(crate_name(), "pramaan_scanner");
    }
}
