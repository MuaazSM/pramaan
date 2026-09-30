meta:
  id: dhlg_log_record
  title: DHSIM device log record ("DHLG")
  license: CC0-1.0
  endian: le
doc: |
  32-byte fixed-stride records starting at dhsim.instances.log_offset.
  Same minor-type codes as HIKSIM's RATS log (docs/01-FORENSIC-CORE.md
  §4.6). Not compiled (see dhsim.ksy); source of truth for pramaan_logs'
  DHSIM reader (C3).
seq:
  - id: magic
    contents: "DHLG"
  - id: ts_unix_s
    type: u4
  - id: kind
    type: u2
    enum: kind_type
  - id: channel
    type: u2
  - id: user
    size: 16
    type: strz
    encoding: ASCII
  - id: param
    type: u4
enums:
  kind_type:
    0x01: login
    0x02: logout
    0x10: playback
    0x11: export
    0x40: hdd_format
    0x41: time_change
    0x50: power_on
