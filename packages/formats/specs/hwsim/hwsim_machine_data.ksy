meta:
  id: hwsim_machine_data
  title: HWSIM (Honeywell-like, synthetic) — GPT disk + machine data
  license: CC0-1.0
  endian: le
  # Not compiled: kaitai-struct-compiler (npm package) is not installed in
  # this environment. Hand-maintained, reviewed source of truth for
  # packages/formats/pramaan_formats/hwsim.py's struct-based parser
  # (docs/01-FORENSIC-CORE.md §4.5 fallback).
doc: |
  HWSIM is a real, CRC-valid GPT-partitioned disk (protective MBR, primary
  + backup GPT header/array — docs/01-FORENSIC-CORE.md §4.6). Partition 1
  is video (see hwsim_partition1.ksy), partition 2 is a "system" partition
  holding an HWSYS JSON blob (not otherwise parsed by CORE). Sector size is
  512 bytes throughout, matching the standard GPT convention the spec's
  own worked geometry assumes ("1 MBR + 1 primary header + 32 sectors for
  a standard 128x128-byte partition array = LBA 34").
seq: []
instances:
  sector_size:
    value: 512
  machine_data_lba:
    value: 34
    doc: |
      "Machine data at sector 34" (docs/01-FORENSIC-CORE.md §4.6) — falls
      out of the GPT math exactly (1 protective MBR + 1 primary header +
      32 sectors for a standard 128-entry x 128-byte partition array), not
      an independently-hardcoded constant.
  machine_data_magic:
    pos: 34 * 512
    size: 18
    contents: "HONEYWELL-NVR-SIM\0"
  model:
    pos: 34 * 512 + 18
    size: 32
    type: strz
    encoding: ASCII
  serial:
    pos: 34 * 512 + 18 + 32
    size: 32
    type: strz
    encoding: ASCII
  gpt_header_lba:
    value: 1
  gpt_signature:
    pos: 1 * 512
    size: 8
    contents: "EFI PART"
  gpt_partition_entry_lba:
    pos: 1 * 512 + 72
    type: u8
  gpt_num_partition_entries:
    pos: 1 * 512 + 80
    type: u4
  gpt_partition_entry_size:
    pos: 1 * 512 + 84
    type: u4
  gpt_partition_entry_array_crc32:
    pos: 1 * 512 + 88
    type: u4
    doc: CRC32 of the whole partition entry array, computed over its raw bytes
