//! Pramaan scanner: disk-speed signature and Annex B NAL search.
//!
//! Implements `docs/01-FORENSIC-CORE.md` §4.3: `scan_signatures`,
//! `scan_annexb` (H.264 + H.265 NAL type decoding) and `byte_histogram`,
//! parallel over overlapped windows via rayon. The core logic in
//! [`signatures`], [`annexb`], [`histogram`] and [`windows`] is plain Rust
//! with no PyO3 dependency, so `cargo build`/`test`/`clippy` always work
//! with zero Python linkage. The `python` module (behind the optional,
//! non-default `python` feature) adds the PyO3 bindings that `maturin`
//! builds into the importable `pramaan_scanner` extension module.
//!
//! An identical pure-Python backend lives at `pramaan_core.scan` and is
//! always kept in parity (`tests/core/test_scan.py`) — the Rust extension
//! is optional at runtime; `pramaan_core.scan.backend()` falls back to
//! Python whenever it isn't importable.
//!
//! Evidence files are opened read-only: [`open_readonly_mmap`] opens with
//! `File::open` (read-only) and maps with `memmap2::Mmap` (an immutable,
//! read-only mapping — there is no write-capable mmap path in this crate),
//! matching CLAUDE.md rule 1.

pub mod annexb;
pub mod histogram;
pub mod signatures;
pub mod windows;

#[cfg(feature = "python")]
mod python;

pub use annexb::{scan_annexb_bytes, Codec, NalHit};
pub use histogram::byte_histogram_bytes;
pub use signatures::{scan_signatures_bytes, SignatureHit};
pub use windows::{core_windows, DEFAULT_WINDOW};

use memmap2::Mmap;
use std::fs::File;
use std::io;
use std::path::Path;

/// Opens `path` read-only and memory-maps it read-only. Raw images only
/// (mirrors `pramaan_core.evidence.EvidenceReader.mmap_readonly`); this
/// crate has no E01 support, matching §4.3's "raw only" scope for the fast
/// path — E01 images are scanned via the Python fallback, which reads
/// through `EvidenceReader`.
pub fn open_readonly_mmap(path: &Path) -> io::Result<Mmap> {
    let file = File::open(path)?; // `File::open` is read-only; never opened for write here.
                                  // SAFETY: the mapping is read-only (`Mmap`, not `MmapMut`) over a file
                                  // this process only ever opens for reading. The usual mmap caveat
                                  // (another process truncating/mutating the file concurrently) applies
                                  // equally to any mmap-based reader and is accepted per the evidence
                                  // read-only contract, which forbids *this process* from writing.
    unsafe { Mmap::map(&file) }
}

fn clamp_end(end: Option<usize>, len: usize) -> usize {
    end.map(|e| e.min(len)).unwrap_or(len)
}

/// `scan_signatures(path, patterns, start=0, end=None, window=DEFAULT_WINDOW)`.
pub fn scan_signatures_path(
    path: &Path,
    patterns: &[Vec<u8>],
    start: usize,
    end: Option<usize>,
    window: usize,
) -> io::Result<Vec<SignatureHit>> {
    let mmap = open_readonly_mmap(path)?;
    let end = clamp_end(end, mmap.len());
    Ok(scan_signatures_bytes(
        &mmap,
        patterns,
        start.min(end),
        end,
        window,
    ))
}

/// `scan_annexb(path, start=0, end=None, codec="auto", window=DEFAULT_WINDOW)`.
pub fn scan_annexb_path(
    path: &Path,
    start: usize,
    end: Option<usize>,
    codec: Codec,
    window: usize,
) -> io::Result<Vec<NalHit>> {
    let mmap = open_readonly_mmap(path)?;
    let end = clamp_end(end, mmap.len());
    Ok(scan_annexb_bytes(&mmap, start.min(end), end, window, codec))
}

/// `byte_histogram(path, start=0, end=None, block=1 MiB)`.
pub fn byte_histogram_path(
    path: &Path,
    start: usize,
    end: Option<usize>,
    block: usize,
) -> io::Result<Vec<f64>> {
    let mmap = open_readonly_mmap(path)?;
    let end = clamp_end(end, mmap.len());
    Ok(byte_histogram_bytes(&mmap, start.min(end), end, block))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_temp(bytes: &[u8]) -> tempfile_path::TempFile {
        tempfile_path::TempFile::new(bytes)
    }

    // Minimal same-crate temp-file helper (avoids adding a dev-dependency
    // just for this): writes to a uniquely named file under `std::env::temp_dir()`
    // and removes it on drop.
    mod tempfile_path {
        use std::fs;
        use std::io::Write;
        use std::path::PathBuf;
        use std::sync::atomic::{AtomicU64, Ordering};

        static COUNTER: AtomicU64 = AtomicU64::new(0);

        pub struct TempFile {
            pub path: PathBuf,
        }

        impl TempFile {
            pub fn new(bytes: &[u8]) -> Self {
                let n = COUNTER.fetch_add(1, Ordering::Relaxed);
                let path = std::env::temp_dir().join(format!(
                    "pramaan_scanner_test_{}_{}.bin",
                    std::process::id(),
                    n
                ));
                let mut f = fs::File::create(&path).expect("create temp file");
                f.write_all(bytes).expect("write temp file");
                f.flush().expect("flush temp file");
                Self { path }
            }
        }

        impl Drop for TempFile {
            fn drop(&mut self) {
                let _ = fs::remove_file(&self.path);
            }
        }
    }

    #[test]
    fn scan_signatures_path_reads_the_mapped_file() {
        let tmp = write_temp(b"xxxNEEDLExxx");
        let hits = scan_signatures_path(&tmp.path, &[b"NEEDLE".to_vec()], 0, None, DEFAULT_WINDOW)
            .unwrap();
        assert_eq!(hits, vec![(0, 3)]);
    }

    #[test]
    fn scan_annexb_path_decodes_from_disk() {
        let tmp = write_temp(&[0x00, 0x00, 0x01, 0x65, 0x00]);
        let hits = scan_annexb_path(&tmp.path, 0, None, Codec::H264, DEFAULT_WINDOW).unwrap();
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].nal_type, 5);
    }

    #[test]
    fn byte_histogram_path_reads_from_disk() {
        let tmp = write_temp(&[0u8; 2048]);
        let hist = byte_histogram_path(&tmp.path, 0, None, 1024).unwrap();
        assert_eq!(hist, vec![0.0, 0.0]);
    }

    #[test]
    fn open_readonly_mmap_never_opens_for_write() {
        let tmp = write_temp(b"evidence");
        let before = std::fs::metadata(&tmp.path).unwrap().modified().unwrap();
        let mmap = open_readonly_mmap(&tmp.path).unwrap();
        assert_eq!(&mmap[..], b"evidence");
        drop(mmap);
        let after = std::fs::metadata(&tmp.path).unwrap().modified().unwrap();
        assert_eq!(before, after);
    }
}
