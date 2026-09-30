meta:
  id: dhsim_index_entry
  title: DHSIM recording index entry
  license: CC0-1.0
  endian: le
doc: |
  32-byte fixed-size entries starting at dhsim.instances.index_offset,
  dhsim.instances.index_entry_count of them. `state == 0` (freed by
  expiry) does not erase `offset`/`length` — the recording's bytes and
  location remain fully recoverable straight from the index
  (docs/01-FORENSIC-CORE.md §4.6/§4.10, "expiry" vs "format"). Not
  compiled (see dhsim.ksy) — source of truth for dhsim.py's index reader.
seq:
  - id: state
    type: u1
    doc: "1 = active, 0 = free (expired but data intact)"
  - id: channel
    type: u1
  - id: pad_2
    type: u2
  - id: start_ts_unix_s
    type: u4
  - id: end_ts_unix_s
    type: u4
  - id: pad_4
    type: u4
  - id: offset
    type: u8
    doc: absolute offset of the first dhav_record.ksy record in this recording
  - id: length
    type: u8
    doc: total byte length of the recording's DHAV record stream
