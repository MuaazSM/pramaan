meta:
  id: rats_log_record
  title: HIKSIM device log record ("RATS")
  license: CC0-1.0
  endian: le
doc: |
  64-byte fixed-stride records starting at hiksim.instances.log_offset, up
  to hiksim.instances.log_area_size / 64 of them. Records also survive
  outside the declared log area after a format (docs/01-FORENSIC-CORE.md
  §4.9) — carved separately, same record shape. Not compiled (see
  hiksim.ksy); source of truth for pramaan_logs' HIKSIM reader (C3).
seq:
  - id: magic
    contents: "RATS"
  - id: ts_unix_s
    type: u4
  - id: major
    type: u2
  - id: minor
    type: u2
    enum: minor_type
  - id: user
    size: 16
    type: strz
    encoding: ASCII
  - id: channel
    type: u4
  - id: param1
    type: u8
  - id: param2
    type: u8
  - id: pad_tail
    size-eos: true
    doc: "Trailing padding to the fixed 64-byte stride; never read."
enums:
  minor_type:
    0x01: login
    0x02: logout
    0x10: playback
    0x11: export
    0x40: hdd_format
    0x41: time_change
    0x50: power_on
