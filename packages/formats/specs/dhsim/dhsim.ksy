meta:
  id: dhsim
  title: DHSIM (Dahua-like, synthetic) — Tier A superblock
  license: CC0-1.0
  endian: le
  # Not compiled: kaitai-struct-compiler (npm package) is not installed in
  # this environment. Hand-maintained source of truth for
  # packages/formats/pramaan_formats/dhsim.py's struct-based parser
  # (docs/01-FORENSIC-CORE.md §4.5 fallback). Once ksc is available:
  #   kaitai-struct-compiler -t python packages/formats/specs/dhsim/dhsim.ksy
  # then add a test asserting both parsers agree on the same sample image.
doc: |
  Modelled on the structures described in Dragonas et al. 2024 and Rzayeva
  et al. 2025 for Dahua-family DVR/NVR firmware — a synthetic layout, not a
  real vendor format (CLAUDE.md rule 7 / docs/01-FORENSIC-CORE.md §1). See
  dhsim_index_entry.ksy, dhav_record.ksy and dhlg_log.ksy for the other
  structures. Unlike HIKSIM, DHSIM's data region is not block-quantized:
  index entries carry an explicit (offset, length), so recordings pack
  back-to-back with no padding between them.
seq: []  # sparse header, offset-addressed
instances:
  magic:
    pos: 0
    size: 8
    contents: "DHFS4.1\0"
  index_offset:
    pos: 0x10
    type: u8
    doc: absolute offset of the first dhsim_index_entry.ksy entry
  index_entry_count:
    pos: 0x18
    type: u4
    doc: |
      Number of 32-byte entries physically present at index_offset. An
      entry's own `state` byte (see dhsim_index_entry.ksy) tells you
      whether it is still active or has been freed (expiry) — both kinds
      are counted here and both keep valid offset/length (data untouched).
  data_offset:
    pos: 0x20
    type: u8
  data_region_size:
    pos: 0x28
    type: u8
  init_time_unix_s:
    pos: 0x30
    type: u4
    doc: last format/init time — a deletion-verdict "format" signal
  model:
    pos: 0x40
    size: 32
    type: strz
    encoding: ASCII
  serial:
    pos: 0x80
    size: 48
    type: strz
    encoding: ASCII
  log_offset:
    pos: 0xC0
    type: u8
    doc: absolute offset of the first dhlg_log.ksy record
  log_area_size:
    pos: 0xC8
    type: u8
