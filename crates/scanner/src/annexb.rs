//! Annex B start-code scanning with H.264/H.265 NAL type decoding
//! (`scan_annexb`), `docs/01-FORENSIC-CORE.md` §4.3 and §4.8.

use aho_corasick::AhoCorasick;
use rayon::prelude::*;

use crate::windows::core_windows;

/// Annex B start code, 3-byte form; a preceding `0x00` makes it the 4-byte
/// form. Both are searched for by locating this fixed tail.
const START_CODE_TAIL: &[u8] = &[0x00, 0x00, 0x01];

/// Bytes needed past the start-of-start-code offset to read one byte of NAL
/// header (enough to decode either an H.264 or an H.265 NAL type) plus a
/// safety margin, used as the window overlap.
const ANNEXB_OVERLAP: usize = 8;

/// H.264 NAL types considered "plausible" access-unit boundaries:
/// non-IDR slice(1), IDR slice(5), SPS(7), PPS(8).
const H264_PLAUSIBLE: [u8; 4] = [1, 5, 7, 8];

/// H.265 NAL types considered "plausible": TRAIL_R(1), IDR_W_RADL(19),
/// IDR_N_LP(20), VPS/SPS/PPS(32-34).
const H265_PLAUSIBLE: [u8; 6] = [1, 19, 20, 32, 33, 34];

/// One decoded Annex B hit: `(offset, start_code_len, nal_type, codec)`.
/// `offset` is the absolute offset of the start code itself (the leading
/// `0x00` of a 3- or 4-byte code); `codec` is `"h264"` or `"h265"`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NalHit {
    pub offset: u64,
    pub start_code_len: u8,
    pub nal_type: u8,
    pub codec: &'static str,
}

/// Requested codec interpretation for NAL-type decoding.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Codec {
    H264,
    H265,
    /// Decode both interpretations and pick whichever falls in the
    /// "plausible" set (§4.8); ties and no-match default to H.264. This is
    /// a documented heuristic, not a guarantee — a single NAL header byte
    /// cannot unambiguously distinguish the two codecs.
    Auto,
}

impl Codec {
    pub fn parse(s: &str) -> Option<Codec> {
        match s {
            "h264" => Some(Codec::H264),
            "h265" => Some(Codec::H265),
            "auto" => Some(Codec::Auto),
            _ => None,
        }
    }
}

fn h264_type(header_byte: u8) -> u8 {
    header_byte & 0x1F
}

fn h265_type(header_byte: u8) -> u8 {
    (header_byte >> 1) & 0x3F
}

fn decode(header_byte: u8, codec: Codec) -> (u8, &'static str) {
    match codec {
        Codec::H264 => (h264_type(header_byte), "h264"),
        Codec::H265 => (h265_type(header_byte), "h265"),
        Codec::Auto => {
            let h264 = h264_type(header_byte);
            let h265 = h265_type(header_byte);
            if H264_PLAUSIBLE.contains(&h264) {
                (h264, "h264")
            } else if H265_PLAUSIBLE.contains(&h265) {
                (h265, "h265")
            } else {
                (h264, "h264")
            }
        }
    }
}

/// Scans `data[start..end]` for Annex B start codes, decoding the NAL type
/// that follows each one. Parallel over `window`-byte windows with a fixed
/// overlap large enough to always see the header byte after a start code
/// found near a window's end.
pub fn scan_annexb_bytes(
    data: &[u8],
    start: usize,
    end: usize,
    window: usize,
    codec: Codec,
) -> Vec<NalHit> {
    let end = end.min(data.len());
    if start >= end {
        return Vec::new();
    }
    let ac = AhoCorasick::new([START_CODE_TAIL]).expect("valid start-code pattern");

    let mut hits: Vec<NalHit> = core_windows(start, end, window)
        .into_par_iter()
        .flat_map_iter(|(core_start, core_end)| {
            // Capped at `end` (not `data.len()`), matching `scan_signatures`:
            // the overlap only ever looks *within* the requested range to
            // resolve a boundary match, never past it.
            let search_end = (core_end + ANNEXB_OVERLAP).min(end);
            let slice = &data[core_start..search_end];
            ac.find_iter(slice).filter_map(move |m| {
                let abs_pos = core_start + m.start();
                if abs_pos >= core_end {
                    return None; // belongs to the next window's core
                }
                let header_idx = abs_pos + 3;
                if header_idx >= end {
                    return None; // truncated at the requested end, nothing to decode
                }
                let four_byte = abs_pos > 0 && data[abs_pos - 1] == 0x00;
                let offset = if four_byte { abs_pos - 1 } else { abs_pos };
                let start_code_len = if four_byte { 4 } else { 3 };
                let (nal_type, codec_name) = decode(data[header_idx], codec);
                Some(NalHit {
                    offset: offset as u64,
                    start_code_len,
                    nal_type,
                    codec: codec_name,
                })
            })
        })
        .collect();
    hits.sort_unstable_by_key(|h| h.offset);
    hits
}

#[cfg(test)]
mod tests {
    use super::*;

    fn h264_nal(nal_type: u8, four_byte: bool) -> Vec<u8> {
        let mut v = if four_byte { vec![0x00] } else { vec![] };
        v.extend_from_slice(&[0x00, 0x00, 0x01, 0x60 | nal_type]); // ref_idc bits set, ignored
        v
    }

    #[test]
    fn decodes_h264_idr_after_three_byte_start_code() {
        let data = h264_nal(5, false);
        let hits = scan_annexb_bytes(&data, 0, data.len(), 1024, Codec::H264);
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].offset, 0);
        assert_eq!(hits[0].start_code_len, 3);
        assert_eq!(hits[0].nal_type, 5);
        assert_eq!(hits[0].codec, "h264");
    }

    #[test]
    fn decodes_four_byte_start_code() {
        let data = h264_nal(7, true);
        let hits = scan_annexb_bytes(&data, 0, data.len(), 1024, Codec::H264);
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].offset, 0);
        assert_eq!(hits[0].start_code_len, 4);
        assert_eq!(hits[0].nal_type, 7);
    }

    #[test]
    fn finds_start_codes_spanning_a_window_boundary() {
        let mut data = vec![0xAB; 100];
        data[48..53].copy_from_slice(&[0x00, 0x00, 0x01, 0x65, 0x00]); // IDR, type 5
        let hits = scan_annexb_bytes(&data, 0, data.len(), 50, Codec::H264);
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].offset, 48);
        assert_eq!(hits[0].nal_type, 5);
    }

    #[test]
    fn auto_prefers_plausible_h264_type() {
        let data = h264_nal(5, false); // 0x65 -> h264 type 5 plausible
        let hits = scan_annexb_bytes(&data, 0, data.len(), 1024, Codec::Auto);
        assert_eq!(hits[0].codec, "h264");
        assert_eq!(hits[0].nal_type, 5);
    }

    #[test]
    fn auto_falls_back_to_h265_for_vps() {
        // header byte 0x40 -> h264 type = 0 (not plausible), h265 type = 32 (VPS, plausible)
        let mut data = vec![0x00, 0x00, 0x01, 0x40];
        data.push(0x00);
        let hits = scan_annexb_bytes(&data, 0, data.len(), 1024, Codec::Auto);
        assert_eq!(hits[0].codec, "h265");
        assert_eq!(hits[0].nal_type, 32);
    }
}
