meta:
  id: hwsim_partition1
  title: HWSIM (Honeywell-like, synthetic) — partition 1 (video)
  license: CC0-1.0
  endian: le
doc: |
  All offsets below are partition-relative (add the video partition's own
  starting byte offset, from the GPT partition array — hwsim_machine_data.ksy
  — to get an absolute disk offset). docs/01-FORENSIC-CORE.md §4.6:

    "Partition 1 header (partition-relative 0x0): u64 video data offset,
    u64 next write offset, u64 available bytes, u64 total allocatable,
    then from 0x40 a block-group index of 16-byte entries [...]. Video
    block list at 0x40000 [...]. Video channel list at 0x400000 [...]."

  The block-group index and video block list are informational (block
  bookkeeping); the video channel list is the *live recording index* a
  VendorParser reads (docs/progress/C3.md: one 16-byte entry per live
  recording). All three lists are terminated by an all-zero 16-byte entry.
seq: []
instances:
  video_data_offset:
    pos: 0x00
    type: u8
    doc: partition-relative offset where NAL-headered video data begins
  next_write_offset:
    pos: 0x08
    type: u8
    doc: partition-relative (already includes video_data_offset, not added to it)
  available_bytes:
    pos: 0x10
    type: u8
  total_allocatable:
    pos: 0x18
    type: u8
  block_group_index_offset:
    value: 0x40
  video_block_list_offset:
    value: 0x40000
  video_channel_list_offset:
    value: 0x400000

block_group_entry:
  seq:
    - id: reserved0
      type: u4
    - id: group_start_ts_unix_s
      type: u4
    - id: group_number
      type: u4
    - id: reserved1
      type: u4

video_block_list_entry:
  doc: |
    16-byte entry: u32 0, u32 block_start_ts (unix s), 3 pad, u8
    block_number, u8 group_number, 3 pad (the spec's own "7 pad" doesn't
    sum to a 16-byte stride with the other named fields at their literal
    offsets — same class of pad-sizing note Q1 documented for HIKSIM's
    HIKBTREE/RATS records; only the trailing pad is resized here).
  seq:
    - id: reserved0
      type: u4
    - id: block_start_ts_unix_s
      type: u4
    - id: pad0
      size: 3
    - id: block_number
      type: u1
    - id: group_number
      type: u1
    - id: pad1
      size: 3

video_channel_list_entry:
  doc: the live recording index — one entry per currently-referenced recording
  seq:
    - id: channel
      type: u1
    - id: stream
      type: u1
      doc: "0x00 = main, 0x20 = sub"
    - id: reserved
      type: u2
    - id: start_ts_unix_s
      type: u4
    - id: start_offset_4k
      type: u4
      doc: 4 KiB units, relative to video_data_offset
    - id: length_4k
      type: u4
      doc: 4 KiB units
