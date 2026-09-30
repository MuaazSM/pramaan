meta:
  id: dhav_record
  title: DHSIM frame record ("DHAV" / "dhav")
  license: CC0-1.0
  endian: le
doc: |
  Self-describing frame record: a 24-byte header, the H.264 Annex B access
  unit payload, then an 8-byte footer repeating the total length. Records
  pack back-to-back with no padding, so `total_length` is exactly how far
  to advance to the next record — and, because both a header checksum and
  a footer length-echo must agree, individual DHAV records remain
  identifiable by scanning even after the surrounding index/superblock has
  been reset by a format (docs/01-FORENSIC-CORE.md §4.6/§4.7, the "DHAV"
  vendor carver). Not compiled (see dhsim.ksy).
seq:
  - id: magic
    contents: "DHAV"
  - id: frame_type
    type: u1
    enum: frame_kind
    doc: "0xFD = I, 0xFC = P, 0xF0 = audio (not produced by this corpus)"
  - id: subtype
    type: u1
  - id: channel
    type: u1
  - id: reserved
    type: u1
  - id: sequence
    type: u4
  - id: total_length
    type: u4
    doc: header (24) + payload + footer (8)
  - id: packed_datetime
    type: u4
    doc: "bits: sec[0:6) min[6:12) hour[12:17) day[17:22) month[22:26) (year-2000)[26:32)"
  - id: milliseconds
    type: u2
  - id: extension_length
    type: u1
    doc: always 0 in this corpus
  - id: checksum
    type: u1
    doc: "sum(bytes[0:23]) & 0xFF — validates the header only"
  - id: payload
    size: total_length - 24 - 8
  - id: footer_magic
    contents: "dhav"
  - id: footer_total_length
    type: u4
    doc: must equal total_length; the record is invalid if it does not
enums:
  frame_kind:
    0xfd: i_frame
    0xfc: p_frame
    0xf0: audio
