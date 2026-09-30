meta:
  id: hwsim_frame_header
  title: HWSIM (Honeywell-like, synthetic) — per-NAL frame header
  license: CC0-1.0
  endian: le
doc: |
  docs/01-FORENSIC-CORE.md §4.6: "Video data: per NAL, a 20-byte custom
  header [...]. Then the NAL with its 4-byte start code. Each channel run
  ends with 20 zero bytes, then 0xEE padding to the next 4 KiB boundary."

  Unlike HIKSIM/DHSIM (one header per *access unit*, covering a bundled
  SPS+PPS+IDR group), HWSIM writes one of these headers before *every*
  individual NAL — the documented exception (docs/progress/Q2.md
  "Decisions"). An access unit (one recovered "frame") is a run of these
  headered NALs where every non-VCL (SPS/PPS) header attaches to the
  following VCL (slice) header, exactly like the generic carver's own
  access-unit grouping (docs/01-FORENSIC-CORE.md §4.7 step 2) — pointed at
  each NAL's own header/payload here rather than the bundle's first one.
seq:
  - id: nal_type
    type: u1
    enum: nal_kind
  - id: fixed
    contents: [0x80, 0x01, 0x00]
  - id: width
    type: u2
  - id: height
    type: u2
  - id: nal_length
    type: u4
    doc: includes the following 4-byte Annex B start code
  - id: timestamp_us
    type: u8
    doc: absolute unix microseconds
  - id: nal
    size: nal_length

enums:
  nal_kind:
    0x82: idr_or_parameter_set
    0x02: non_idr
