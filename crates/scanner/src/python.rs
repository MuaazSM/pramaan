//! PyO3 bindings, built only when the (non-default) `python` feature is
//! enabled — i.e. only by `maturin develop --features python` (see
//! `just setup`). Never compiled by plain `cargo build`/`test`/`clippy`.
//!
//! Mirrors `docs/01-FORENSIC-CORE.md` §4.3 exactly and matches the pure
//! Python fallback in `pramaan_core.scan` byte-for-byte on offsets/types
//! (see `tests/core/test_scan.py`).

use std::path::PathBuf;

use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;

use crate::annexb::Codec;
use crate::{byte_histogram_path, scan_annexb_path, scan_signatures_path, DEFAULT_WINDOW};

fn io_err(e: std::io::Error) -> PyErr {
    PyOSError::new_err(e.to_string())
}

/// `scan_signatures(path, patterns, start=0, end=None, window=None) -> list[(pattern_idx, offset)]`.
#[pyfunction]
#[pyo3(signature = (path, patterns, start=0, end=None, window=None))]
fn scan_signatures(
    path: PathBuf,
    patterns: Vec<Vec<u8>>,
    start: usize,
    end: Option<usize>,
    window: Option<usize>,
) -> PyResult<Vec<(usize, u64)>> {
    let window = window.unwrap_or(DEFAULT_WINDOW);
    scan_signatures_path(&path, &patterns, start, end, window).map_err(io_err)
}

/// `scan_annexb(path, start=0, end=None, codec="auto", window=None) -> list[(offset, start_code_len, nal_type, codec)]`.
#[pyfunction]
#[pyo3(signature = (path, start=0, end=None, codec="auto".to_string(), window=None))]
fn scan_annexb(
    path: PathBuf,
    start: usize,
    end: Option<usize>,
    codec: String,
    window: Option<usize>,
) -> PyResult<Vec<(u64, u8, u8, String)>> {
    let codec_enum = Codec::parse(&codec).ok_or_else(|| {
        PyValueError::new_err(format!("unknown codec {codec:?}; expected h264/h265/auto"))
    })?;
    let window = window.unwrap_or(DEFAULT_WINDOW);
    let hits = scan_annexb_path(&path, start, end, codec_enum, window).map_err(io_err)?;
    Ok(hits
        .into_iter()
        .map(|h| (h.offset, h.start_code_len, h.nal_type, h.codec.to_string()))
        .collect())
}

/// `byte_histogram(path, start=0, end=None, block=1048576) -> list[float]`.
#[pyfunction]
#[pyo3(signature = (path, start=0, end=None, block=1024 * 1024))]
fn byte_histogram(
    path: PathBuf,
    start: usize,
    end: Option<usize>,
    block: usize,
) -> PyResult<Vec<f64>> {
    byte_histogram_path(&path, start, end, block).map_err(io_err)
}

#[pymodule]
fn pramaan_scanner(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(scan_signatures, m)?)?;
    m.add_function(wrap_pyfunction!(scan_annexb, m)?)?;
    m.add_function(wrap_pyfunction!(byte_histogram, m)?)?;
    m.add("DEFAULT_WINDOW", DEFAULT_WINDOW)?;
    Ok(())
}
