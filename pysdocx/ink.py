"""Per-stroke coordinate and attribute decoding.

Ported from crates/sdocx/src/decode.rs — keep in sync with that file; it is
the validated reference implementation.
"""

import struct

DELTA_SCALE = 1.0 / 32.0
MAX_PRESSURE = 1400.0
# Color marker: leading byte is a format version (0x02 on older Samsung Notes,
# 0x03 on v4.4.x+), then a fixed 0x00, then a byte that varies by tool
# (tool_id = (byte2 - 1) // 2 — exact for the 5 ink tools confirmed on
# samples/OnlyPensBlacksize10_*.sdocx: 0=pen, 1=fountain pen, 2=calligraphy
# pen, 3=pencil, 4=calligraphy brush), then three fixed 0x00 bytes.
#
# This byte is NOT a single global tool registry: on
# samples/OnlyHighlighterBlack_*.sdocx, "highlighter" reuses byte2=1 (same as
# "pen" above) and "marker pen" uses byte2=4 (even — the byte is not always
# odd). Treat tool_id as a per-category slot index, not a universal ID, until
# more ground-truth samples narrow it down further.
#
# The marker sits at a fixed offset from the end of data_blob (66 bytes for
# ink-pen strokes, 62 for highlighter/marker-pen strokes) — search only the
# tail of the blob, not the whole thing. A blob-wide backward scan risks
# matching this same 6-byte shape by coincidence inside the per-point
# channel data (pressure/timestamp/tilt are themselves streams of small
# sign-magnitude byte pairs, so runs of near-zero values can look like a
# marker), especially on long, low-variance strokes such as a straight,
# steady highlighter stroke.
COLOR_MARKER_LEN = 6
MARKER_SEARCH_WINDOW = 100
# "Straight-line" tool strokes (ruler-mode highlighter/marker) omit the 2-byte
# version prefix (0x02/0x03, 0x00) and store color/width directly as
# [TT, 0x00, 0x00, 0x00] + BGRA + f32 width, at a fixed offset from the end
# of data_blob (52 bytes for the start of BGRA, 48 for width). Confirmed on
# samples/OnlyHighlighterBlack_*.sdocx by searching for the exact width bytes
# of the freehand neighbor stroke inside the straight-line stroke's blob —
# found at len(data_blob)-48 on all 6 straight-line strokes, with TT matching
# the same tool identity as the long-form marker (0x01=highlighter,
# 0x04=marker pen). Used only as a fallback when the long-form marker isn't
# found — there's no observed "width only, no color" short-form case yet.
SHORT_MARKER_LEN = 4
# Ink-pen-category strokes (pen/fountain pen/calligraphy pen/pencil/brush)
# carry a 12-byte block right after the width float that highlighter/marker
# strokes never have: a u32 equal to `2 * tool_id`, then the width repeated
# as f32, then a 4-byte tag. This is what makes the long-form pen marker's
# tail 66 bytes vs. 62 for highlighter/marker. Confirmed across every sample
# checked (pens, highlighters, the big benchmark — 606 strokes, zero
# exceptions): present <=> the real app applies pressure-sensitive width
# (a fountain/calligraphy nib effect); absent <=> constant width (flat felt
# tip). This is NOT a width-magnitude heuristic — it's a structural marker,
# so it correctly handles small-size highlighters too (e.g. width 5.33,
# which numerically overlaps with pen widths but still reads as "flat").
TAPER_TAG_LEN = 12


def _has_pressure_taper(data_blob: bytes, pos: int, marker_len: int, tool_id: int, width: float) -> bool:
    offset = pos + marker_len + 8  # marker + BGRA(4) + width(4)
    if offset + TAPER_TAG_LEN > len(data_blob):
        return False
    tag = struct.unpack_from("<I", data_blob, offset)[0]
    if tag != 2 * tool_id:
        return False
    width_dup = struct.unpack_from("<f", data_blob, offset + 4)[0]
    return abs(width_dup - width) < 0.01


def decode_sign_mag(data: bytes, offset: int, count: int) -> list[int]:
    """Decode sign-magnitude byte pairs: (magnitude, sign_flag). 0x00 = +, else -."""
    vals = []
    for i in range(count):
        pos = offset + i * 2
        if pos + 1 >= len(data):
            break
        mag = data[pos]
        sign = data[pos + 1]
        vals.append(mag if sign == 0x00 else -mag)
    return vals


def decode_coordinates(
    data: bytes, start_x: float, start_y: float, n_deltas: int
) -> tuple[list[tuple[float, float]], int]:
    """Decode delta-encoded coordinates. Returns (points, n_coord_bytes).

    Each quartet is [dx_mag, dx_flag, dy_mag, dy_flag]; bit 7 of each flag is
    the sign. Bit 0 doubles that axis's resolution for this delta (scale
    1/16 instead of 1/32) — on freehand strokes it's always 0 (no-op), but
    "straight-line" tool strokes (ruler-mode highlighter/marker) set it on
    every single Y delta, consistently, because the synthesized uniform
    per-step Y delta for a steep line doesn't fit standard resolution.
    Confirmed against samples/OnlyHighlighterBlack_*.sdocx: without this, the
    decoded line is the right start point and X span but a much-too-shallow
    angle and roughly half the height it should be. Other low bits (1-6)
    still appear to carry unrelated metadata on v4.4.x+ and are ignored.
    """
    x, y = start_x, start_y
    points = [(x, y)]
    limit = n_deltas * 4
    i = 0
    n = len(data)
    while i + 3 < n and i < limit:
        dx_mag, dx_flag, dy_mag, dy_flag = data[i], data[i + 1], data[i + 2], data[i + 3]
        dx_scale = DELTA_SCALE * (2 if dx_flag & 1 else 1)
        dy_scale = DELTA_SCALE * (2 if dy_flag & 1 else 1)
        dx = (dx_mag if dx_flag & 0x80 == 0 else -dx_mag) * dx_scale
        dy = (dy_mag if dy_flag & 0x80 == 0 else -dy_mag) * dy_scale
        x += dx
        y += dy
        points.append((x, y))
        i += 4
    return points, i


def color_hex(color: tuple[int, int, int] | None) -> str | None:
    """Format an (r, g, b) tuple as '#rrggbb', or None through unchanged."""
    if color is None:
        return None
    r, g, b = color
    return f"#{r:02x}{g:02x}{b:02x}"


def extract_color_and_width(
    data_blob: bytes,
) -> tuple[tuple[int, int, int] | None, float, int | None, bool, bool, int]:
    """Decode (color, pen_width, tool_id, marker_found, tapered, intensity).

    color is (r, g, b) or None. tool_id is None when marker_found is False —
    i.e. no recognized marker is present at all (still-undecoded territory).
    tapered is True for ink-pen-category tools (pressure-sensitive width),
    False for highlighter/marker-category tools (constant width) — see
    TAPER_TAG_LEN. intensity is the BGRA alpha byte (0-255): the pen's opacity
    setting — 255 = full, lower = the "intensità" slider (e.g. pencil at
    intensity 0 stores alpha 0x03, intensity 50 alpha 0x80). Defaults to 255.
    """
    color = None
    width = 0.8
    tool_id = None
    intensity = 255
    pos = None
    marker_len = COLOR_MARKER_LEN
    search_start = max(len(data_blob) - MARKER_SEARCH_WINDOW, 0)
    for i in range(len(data_blob) - COLOR_MARKER_LEN, search_start - 1, -1):
        window = data_blob[i : i + COLOR_MARKER_LEN]
        if (
            window[0] in (0x02, 0x03)
            and window[1] == 0x00
            and window[3] == 0x00
            and window[4] == 0x00
            and window[5] == 0x00
        ):
            pos = i
            tool_id = (window[2] - 1) // 2
            break

    if pos is None:
        # Fallback: short-form marker (straight-line tool strokes), only
        # valid when immediately followed by a BGRA color (alpha 0xFF).
        for i in range(len(data_blob) - SHORT_MARKER_LEN - 4, search_start - 1, -1):
            window = data_blob[i : i + SHORT_MARKER_LEN]
            after = data_blob[i + SHORT_MARKER_LEN : i + SHORT_MARKER_LEN + 4]
            if window[1] == 0x00 and window[2] == 0x00 and window[3] == 0x00 and after[3] == 0xFF:
                pos = i
                marker_len = SHORT_MARKER_LEN
                tool_id = (window[0] - 1) // 2
                break

    if pos is not None:
        after = data_blob[pos + marker_len :]
        # After the marker, the layout is either [BGRA][f32 width] (explicit
        # color) or [f32 width] directly (default ink, no color). The 4th byte
        # (alpha) disambiguates together with whether the leading 4 bytes are a
        # sane width float:
        #   - alpha == 0xFF        -> full-opacity color, width at offset 4
        #   - leading f32 is sane  -> no color, width at offset 0 (default ink;
        #                             its float exponent byte is ~0x3D-0x42,
        #                             never an alpha value we observe: 03/80/FF)
        #   - otherwise            -> reduced-opacity color, alpha = "intensity"
        #                             (the pen's intensità slider), width at 4
        w0 = struct.unpack_from("<f", after, 0)[0] if len(after) >= 4 else None
        if len(after) >= 8 and after[3] == 0xFF:
            color = (after[2], after[1], after[0])
            width = struct.unpack_from("<f", after, 4)[0]
        elif w0 is not None and 0.1 < w0 < 70.0:
            width = w0
        elif len(after) >= 8:
            color = (after[2], after[1], after[0])
            intensity = after[3]
            width = struct.unpack_from("<f", after, 4)[0]
        elif w0 is not None:
            width = w0

    tapered = pos is not None and tool_id is not None and _has_pressure_taper(
        data_blob, pos, marker_len, tool_id, width
    )

    return color, width, tool_id, pos is not None, tapered, intensity


def decode_trailing(data_blob: bytes, n_coord_bytes: int, n_points: int) -> dict:
    """Decode all trailing data: 4 per-point channels + per-stroke color/width."""
    trail_start = n_coord_bytes + 4  # 4-byte gap after coordinates

    channels: list[list[int]] = []
    for ch_idx in range(4):
        ch_offset = trail_start + ch_idx * n_points * 2
        if ch_offset + n_points * 2 > len(data_blob):
            channels.append([])
            continue
        deltas = decode_sign_mag(data_blob, ch_offset, n_points)
        cumsum = 0
        values = []
        for d in deltas:
            cumsum += d
            values.append(cumsum)
        channels.append(values)

    pressures = [min(max(v / MAX_PRESSURE, 0.0), 1.0) for v in channels[0]]
    timestamps, tilt_x, tilt_y = channels[1], channels[2], channels[3]
    color, pen_width, tool_id, marker_found, tapered, intensity = extract_color_and_width(data_blob)

    return {
        "pressures": pressures,
        "timestamps": timestamps,
        "tilt_x": tilt_x,
        "tilt_y": tilt_y,
        "color": color,
        "pen_width": pen_width,
        "tool_id": tool_id,
        "tapered": tapered,
        "intensity": intensity,
        "broad_pen": not marker_found,
    }
