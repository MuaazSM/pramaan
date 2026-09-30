meta:
  id: hikbtree
  title: HIKSIM recording index ("HIKBTREE")
  license: CC0-1.0
  endian: le
doc: |
  Located at hiksim.instances.hikbtree_offset. Fixed 48-byte entry stride;
  only the first `entry_count` entries (the +0x10 field) are meaningful —
  slots at/after `entry_count` are not part of the live index and must not
  be read as recordings (docs/01-FORENSIC-CORE.md §4.6). Not compiled (see
  hiksim.ksy) — source of truth for hiksim.py's HIKBTREE reader.
seq: []
instances:
  magic:
    pos: 0
    size: 8
    contents: "HIKBTREE"
  entry_count:
    pos: 0x10
    type: u4
  entries:
    pos: 0x60
    type: hikbtree_entry
    repeat: expr
    repeat-expr: entry_count
types:
  hikbtree_entry:
    seq:
      - id: state
        type: u8
        doc: "0 = in use; 0xFFFFFFFFFFFFFFFF = free"
      - id: channel
        type: u1
      - id: has_footage
        type: u1
      - id: pad_6
        size: 6
      - id: start_ts_unix_s
        type: u4
      - id: end_ts_unix_s
        type: u4
      - id: data_block_offset
        type: u8
      - id: pad_tail
        size-eos: true
        doc: "Trailing padding to the fixed 48-byte stride; never read."
