"""A small H.264 SPS bit reader (docs/01-FORENSIC-CORE.md §4.7 step 3):
"Parse SPS for width/height/profile (write a small bit reader for
exp-Golomb; no decoding)". Used by the generic Annex B carver to size and
cluster channels when no vendor header is available.
"""

from __future__ import annotations

from dataclasses import dataclass

#: profile_idc values that carry the "high profile" extra SPS fields
#: (chroma_format_idc, bit depths, scaling lists) — ITU-T H.264 §7.3.2.1.1.
_HIGH_PROFILE_IDC = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}


class MalformedSps(ValueError):
    """Raised when an SPS RBSP can't be parsed (truncated, or uses a
    high-profile scaling-list feature this minimal reader doesn't decode)."""


@dataclass(frozen=True)
class SpsInfo:
    sps_id: int
    profile_idc: int
    level_idc: int
    width: int
    height: int


class _BitReader:
    """MSB-first bit reader over already-de-emulated RBSP bytes."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read_bit(self) -> int:
        byte_idx, bit_idx = divmod(self.pos, 8)
        if byte_idx >= len(self.data):
            raise MalformedSps("bit reader ran past end of RBSP")
        bit = (self.data[byte_idx] >> (7 - bit_idx)) & 1
        self.pos += 1
        return bit

    def read_bits(self, n: int) -> int:
        value = 0
        for _ in range(n):
            value = (value << 1) | self.read_bit()
        return value

    def read_ue(self) -> int:
        """Exp-Golomb unsigned."""
        leading_zeros = 0
        while self.read_bit() == 0:
            leading_zeros += 1
            if leading_zeros > 32:
                raise MalformedSps("exp-Golomb prefix too long")
        if leading_zeros == 0:
            return 0
        return (1 << leading_zeros) - 1 + self.read_bits(leading_zeros)

    def read_se(self) -> int:
        """Exp-Golomb signed."""
        k = self.read_ue()
        if k % 2 == 0:
            return -(k // 2)
        return (k + 1) // 2


def strip_emulation_prevention(rbsp_with_ep: bytes) -> bytes:
    """Remove H.264 Annex B emulation-prevention bytes: any ``0x03`` that
    immediately follows two ``0x00`` bytes and precedes a byte ``<= 0x03``."""
    out = bytearray()
    zero_run = 0
    i = 0
    n = len(rbsp_with_ep)
    while i < n:
        b = rbsp_with_ep[i]
        if zero_run >= 2 and b == 0x03 and i + 1 < n and rbsp_with_ep[i + 1] <= 0x03:
            i += 1
            zero_run = 0
            continue
        out.append(b)
        zero_run = zero_run + 1 if b == 0 else 0
        i += 1
    return bytes(out)


def parse_sps(rbsp: bytes) -> SpsInfo:
    """Parse an SPS RBSP (NAL header byte already stripped) for
    ``profile_idc``, ``level_idc``, ``sps_id`` and the cropped picture
    width/height. Raises :class:`MalformedSps` on anything this minimal
    reader can't handle (truncation, or seq_scaling_matrix_present_flag —
    not needed for the baseline-profile streams this corpus produces)."""
    data = strip_emulation_prevention(rbsp)
    if len(data) < 4:
        raise MalformedSps("SPS RBSP too short")
    br = _BitReader(data)
    profile_idc = br.read_bits(8)
    br.read_bits(8)  # constraint flag set + reserved
    level_idc = br.read_bits(8)
    sps_id = br.read_ue()

    chroma_format_idc = 1  # 4:2:0 implied when not signalled
    if profile_idc in _HIGH_PROFILE_IDC:
        chroma_format_idc = br.read_ue()
        if chroma_format_idc == 3:
            br.read_bit()  # separate_colour_plane_flag
        br.read_ue()  # bit_depth_luma_minus8
        br.read_ue()  # bit_depth_chroma_minus8
        br.read_bit()  # qpprime_y_zero_transform_bypass_flag
        if br.read_bit():  # seq_scaling_matrix_present_flag
            raise MalformedSps("seq_scaling_matrix_present_flag not supported")

    br.read_ue()  # log2_max_frame_num_minus4
    pic_order_cnt_type = br.read_ue()
    if pic_order_cnt_type == 0:
        br.read_ue()  # log2_max_pic_order_cnt_lsb_minus4
    elif pic_order_cnt_type == 1:
        br.read_bit()  # delta_pic_order_always_zero_flag
        br.read_se()  # offset_for_non_ref_pic
        br.read_se()  # offset_for_top_to_bottom_field
        num_ref_frames_in_cycle = br.read_ue()
        for _ in range(num_ref_frames_in_cycle):
            br.read_se()

    br.read_ue()  # max_num_ref_frames
    br.read_bit()  # gaps_in_frame_num_value_allowed_flag
    pic_width_in_mbs_minus1 = br.read_ue()
    pic_height_in_map_units_minus1 = br.read_ue()
    frame_mbs_only_flag = br.read_bit()
    if not frame_mbs_only_flag:
        br.read_bit()  # mb_adaptive_frame_field_flag
    br.read_bit()  # direct_8x8_inference_flag

    crop_left = crop_right = crop_top = crop_bottom = 0
    if br.read_bit():  # frame_cropping_flag
        crop_left = br.read_ue()
        crop_right = br.read_ue()
        crop_top = br.read_ue()
        crop_bottom = br.read_ue()

    sub_width_c = 1 if chroma_format_idc == 3 else 2
    sub_height_c = 1 if chroma_format_idc in (2, 3) else 2
    crop_unit_x = sub_width_c
    crop_unit_y = sub_height_c * (2 - frame_mbs_only_flag)

    width = (pic_width_in_mbs_minus1 + 1) * 16 - crop_unit_x * (crop_left + crop_right)
    height = (2 - frame_mbs_only_flag) * (pic_height_in_map_units_minus1 + 1) * 16 - (
        crop_unit_y * (crop_top + crop_bottom)
    )

    return SpsInfo(
        sps_id=sps_id, profile_idc=profile_idc, level_idc=level_idc, width=width, height=height
    )
