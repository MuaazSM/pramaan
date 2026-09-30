meta:
  id: hiksim_data_block
  title: HIKSIM data block — IMKH header + embedded MPEG-PS elementary stream
  license: CC0-1.0
  endian: le
doc: |
  One of hiksim.instances.data_block_count blocks, each
  hiksim.instances.data_block_size bytes, starting at
  hiksim.instances.data_offset. After the 40-byte IMKH header, the rest of
  the block is a standard ISO/IEC 13818-1 MPEG-PS stream — **big-endian**,
  independent of the container's little-endian convention — of three
  record kinds, repeated per access unit until the zero-filled block tail:
    1. pack header (00 00 01 BA), 14 bytes, carrying a 33-bit SCR used here
       as a 90 kHz PTS-style per-frame timestamp.
    2. (keyframes only) a private_stream_1 PES (00 00 01 BD) whose payload
       is "HKTS" + u32 BE absolute unix seconds + u16 BE milliseconds + u8
       channel — the one place an *absolute* clock reading is written.
    3. a video PES (00 00 01 E0) carrying one H.264 Annex B access unit
       (SPS/PPS/IDR, or a single P-slice), with a PTS-only optional header.
  Not compiled (see hiksim.ksy) — source of truth for
  pramaan_formats.mpegps / pramaan_formats.hiksim's record-by-record reader,
  which also backs pramaan_recovery's HIKSIM-PS vendor carver for data that
  survives outside the live HIKBTREE index.
seq:
  - id: magic
    contents: "IMKH"
  - id: codec_id
    type: u2
    doc: "0x0100 = H.264"
  - id: pad_34
    size: 34
  - id: ps_stream
    size-eos: true
    doc: parsed record-by-record; see pack_header / private_pes / video_pes below
types:
  pack_header:
    seq:
      - id: start_code
        contents: [0x00, 0x00, 0x01, 0xba]
      - id: body
        size: 10
        doc: bit-packed SCR/mux-rate fields per ISO/IEC 13818-1; see mpegps.parse_pack_header
  private_pes:
    seq:
      - id: start_code
        contents: [0x00, 0x00, 0x01, 0xbd]
      - id: length
        type: u2be
      - id: payload
        size: length
  video_pes:
    seq:
      - id: start_code
        contents: [0x00, 0x00, 0x01, 0xe0]
      - id: length
        type: u2be
        doc: "0 only for payloads > 0xFFFF bytes ('unbounded'); not produced by this synthetic corpus"
      - id: header_flags_1
        type: u1
      - id: header_flags_2
        type: u1
      - id: header_data_length
        type: u1
      - id: optional_fields
        size: header_data_length
        doc: "PTS-only in this corpus: 5 bytes, marker '0010'"
      - id: payload
        size: length - 3 - header_data_length
        doc: H.264 Annex B access unit (4-byte start codes between NALs)
  hkts_payload:
    seq:
      - id: magic
        contents: "HKTS"
      - id: unix_s
        type: u4be
      - id: ms
        type: u2be
      - id: channel
        type: u1
