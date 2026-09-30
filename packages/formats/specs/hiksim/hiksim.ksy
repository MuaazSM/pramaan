meta:
  id: hiksim
  title: HIKSIM (Hikvision-like, synthetic) — Tier A superblock
  license: CC0-1.0
  endian: le
  # Not compiled: kaitai-struct-compiler (npm package) is not installed in
  # this environment. This spec is hand-maintained and reviewed as the
  # source of truth for packages/formats/pramaan_formats/hiksim.py's
  # struct-based parser (docs/01-FORENSIC-CORE.md §4.5 fallback). Once ksc
  # is available, compile with:
  #   kaitai-struct-compiler -t python packages/formats/specs/hiksim/hiksim.ksy
  # and add a test asserting both parsers agree on the same sample image.
doc: |
  Modelled on the structures described in Han et al. 2015 and Dragonas et
  al. for Hikvision-family DVR/NVR firmware — a synthetic layout, not a
  real vendor format (CLAUDE.md rule 7 / docs/01-FORENSIC-CORE.md §1). See
  hikbtree.ksy, hiksim_data_block.ksy and rats_log.ksy for the other
  structures this superblock points at. All region sizes below are read
  from these fields at parse time, never hardcoded — the synthetic test
  corpus deliberately scales some regions down.
seq: []  # every field is offset-addressed (sparse header), not sequential
instances:
  magic:
    pos: 0x210
    size: 18
    contents: "HIKVISION@HANGZHOU"
  disk_capacity_bytes:
    pos: 0x230
    type: u8
  hikbtree_offset:
    pos: 0x240
    type: u8
    doc: absolute offset of the hikbtree.ksy structure
  hikbtree_size:
    pos: 0x248
    type: u8
  data_offset:
    pos: 0x250
    type: u8
    doc: absolute offset of the first hiksim_data_block.ksy block
  data_block_size:
    pos: 0x258
    type: u8
    doc: "Synthetic default 4 MiB; the small test corpus scales this down."
  data_block_count:
    pos: 0x260
    type: u4
  log_offset:
    pos: 0x270
    type: u8
    doc: absolute offset of the first rats_log_record.ksy record
  log_area_size:
    pos: 0x278
    type: u8
  init_time_unix_s:
    pos: 0x280
    type: u4
    doc: last format/init time — a deletion-verdict "format" signal
  model:
    pos: 0x300
    size: 32
    type: strz
    encoding: ASCII
  serial:
    pos: 0x320
    size: 48
    type: strz
    encoding: ASCII
