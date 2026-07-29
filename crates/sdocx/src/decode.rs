const DELTA_SCALE: f64 = 1.0 / 32.0;
const MAX_PRESSURE: f64 = 1400.0;
/// Color marker: leading byte is a format version (0x02 on older Samsung Notes,
/// 0x03 on v4.4.x+), then a fixed 0x00, then a byte that varies by tool
/// (tool_id = (byte2 - 1) / 2 — exact for the 5 ink tools confirmed on
/// samples/OnlyPensBlacksize10_*.sdocx: 0=pen, 1=fountain pen, 2=calligraphy
/// pen, 3=pencil, 4=calligraphy brush), then three fixed 0x00 bytes.
///
/// This byte is NOT a single global tool registry: on
/// samples/OnlyHighlighterBlack_*.sdocx, "highlighter" reuses byte2=1 (same as
/// "pen" above) and "marker pen" uses byte2=4 (even — the byte is not always
/// odd). Treat tool_id as a per-category slot index, not a universal ID,
/// until more ground-truth samples narrow it down further.
///
/// The marker sits at a fixed offset from the end of the data blob (66 bytes
/// for ink-pen strokes, 62 for highlighter/marker-pen strokes) — search only
/// the tail, not the whole blob. A blob-wide backward scan risks matching
/// this same 6-byte shape by coincidence inside the per-point channel data
/// (pressure/timestamp/tilt are themselves streams of small sign-magnitude
/// byte pairs, so runs of near-zero values can look like a marker),
/// especially on long, low-variance strokes such as a straight, steady
/// highlighter stroke.
const COLOR_MARKER_LEN: usize = 6;
const MARKER_SEARCH_WINDOW: usize = 100;
/// "Straight-line" tool strokes (ruler-mode highlighter/marker) omit the
/// 2-byte version prefix (0x02/0x03, 0x00) and store color/width directly as
/// `[TT, 0x00, 0x00, 0x00]` + BGRA + f32 width, at a fixed offset from the
/// end of the data blob (52 bytes for the start of BGRA, 48 for width).
/// Confirmed on samples/OnlyHighlighterBlack_*.sdocx by searching for the
/// exact width bytes of the freehand neighbor stroke inside the
/// straight-line stroke's blob — found at `len(data_blob) - 48` on all 6
/// straight-line strokes, with TT matching the same tool identity as the
/// long-form marker (0x01 = highlighter, 0x04 = marker pen). Used only as a
/// fallback when the long-form marker isn't found — there's no observed
/// "width only, no color" short-form case yet.
const SHORT_MARKER_LEN: usize = 4;
/// Ink-pen-category strokes (pen/fountain pen/calligraphy pen/pencil/brush)
/// carry a 12-byte block right after the width float that highlighter/marker
/// strokes never have: a u32 equal to `2 * tool_id`, then the width repeated
/// as f32, then a 4-byte tag. This is what makes the long-form pen marker's
/// tail 66 bytes vs. 62 for highlighter/marker. Confirmed across every
/// sample checked (pens, highlighters, the big benchmark — 606 strokes, zero
/// exceptions): present <=> the real app applies pressure-sensitive width
/// (a fountain/calligraphy nib effect); absent <=> constant width (flat felt
/// tip). This is NOT a width-magnitude heuristic — it's a structural marker,
/// so it correctly handles small-size highlighters too (e.g. width 5.33,
/// which numerically overlaps with pen widths but still reads as "flat").
const TAPER_TAG_LEN: usize = 12;

use crate::types::{Color, Point};

/// Decode sign-magnitude byte pairs: (magnitude, sign_flag).
/// `0x00` = positive, `0x80` = negative.
pub fn decode_sign_mag(data: &[u8], offset: usize, count: usize) -> Vec<i64> {
    let mut vals = Vec::with_capacity(count);
    for i in 0..count {
        let pos = offset + i * 2;
        if pos + 1 >= data.len() {
            break;
        }
        let mag = data[pos] as i64;
        let sign = data[pos + 1];
        vals.push(if sign == 0x00 { mag } else { -mag });
    }
    vals
}

/// Decode delta-encoded coordinates. Each quartet is `[dx_mag, dx_flag, dy_mag, dy_flag]`;
/// bit 7 of each flag is the sign. Bit 0 doubles that axis's resolution for this delta
/// (scale 1/16 instead of 1/32) — on freehand strokes it's always 0 (no-op), but
/// "straight-line" tool strokes (ruler-mode highlighter/marker) set it on every single Y
/// delta, consistently, because the synthesized uniform per-step Y delta for a steep line
/// doesn't fit standard resolution. Confirmed against samples/OnlyHighlighterBlack_*.sdocx:
/// without this, the decoded line has the right start point and X span but a
/// much-too-shallow angle and roughly half the height it should be. Other low bits (1-6)
/// still appear to carry unrelated metadata on v4.4.x+ and are ignored.
///
/// Reads exactly `n_deltas` quartets, producing `n_deltas + 1` points (including the start).
/// Stops early if `data` runs out. Returns `(points, n_coord_bytes)`.
pub fn decode_coordinates(
    data: &[u8],
    start_x: f64,
    start_y: f64,
    n_deltas: usize,
) -> (Vec<Point>, usize) {
    let mut x = start_x;
    let mut y = start_y;
    let mut points = vec![Point { x, y }];
    let limit = n_deltas * 4;
    let mut i = 0;

    while i + 3 < data.len() && i < limit {
        let dx_mag = data[i];
        let dx_flag = data[i + 1];
        let dy_mag = data[i + 2];
        let dy_flag = data[i + 3];

        let dx_scale = if dx_flag & 1 == 1 {
            DELTA_SCALE * 2.0
        } else {
            DELTA_SCALE
        };
        let dy_scale = if dy_flag & 1 == 1 {
            DELTA_SCALE * 2.0
        } else {
            DELTA_SCALE
        };

        let dx = if dx_flag & 0x80 == 0 {
            dx_mag as f64
        } else {
            -(dx_mag as f64)
        } * dx_scale;
        let dy = if dy_flag & 0x80 == 0 {
            dy_mag as f64
        } else {
            -(dy_mag as f64)
        } * dy_scale;

        x += dx;
        y += dy;
        points.push(Point { x, y });
        i += 4;
    }

    (points, i)
}

/// Decoded trailing channel data from a stroke's data blob.
pub struct TrailingData {
    pub pressures: Vec<f64>,
    pub timestamps: Vec<i64>,
    pub tilt_x: Vec<i64>,
    pub tilt_y: Vec<i64>,
    pub color: Option<Color>,
    pub pen_width: f32,
    /// Pen tool (0=pen, 1=fountain pen, 2=calligraphy pen, 3=pencil,
    /// 4=calligraphy brush; not a single global registry — see the
    /// `COLOR_MARKER_LEN` doc comment for the highlighter/marker-pen caveat).
    /// `None` when no color marker was found at all.
    pub tool_id: Option<u8>,
    /// `true` for ink-pen-category tools (pressure-sensitive width); `false`
    /// for highlighter/marker-category tools (constant width). See
    /// `TAPER_TAG_LEN`.
    pub tapered: bool,
}

/// Decode all trailing data: per-point channels (pressure, timestamp, tilt_x, tilt_y)
/// and per-stroke color + pen width.
pub fn decode_trailing(data_blob: &[u8], n_coord_bytes: usize, n_points: usize) -> TrailingData {
    let trail_start = n_coord_bytes + 4; // 4-byte gap after coordinates

    // Decode 4 per-point channels
    let mut channels: [Vec<i64>; 4] = Default::default();
    for (ch_idx, channel) in channels.iter_mut().enumerate() {
        let ch_offset = trail_start + ch_idx * n_points * 2;
        if ch_offset + n_points * 2 > data_blob.len() {
            continue;
        }
        let deltas = decode_sign_mag(data_blob, ch_offset, n_points);
        let mut cumsum: i64 = 0;
        let mut values = Vec::with_capacity(deltas.len());
        for d in deltas {
            cumsum += d;
            values.push(cumsum);
        }
        *channel = values;
    }

    // Normalize pressure to 0.0..1.0
    let pressures: Vec<f64> = channels[0]
        .iter()
        .map(|&v| (v as f64 / MAX_PRESSURE).clamp(0.0, 1.0))
        .collect();

    let timestamps = std::mem::take(&mut channels[1]);
    let tilt_x = std::mem::take(&mut channels[2]);
    let tilt_y = std::mem::take(&mut channels[3]);

    // Extract color, pen width, tool id and taper from the color marker
    let (color, pen_width, tool_id, tapered) = extract_color_and_width(data_blob);

    TrailingData {
        pressures,
        timestamps,
        tilt_x,
        tilt_y,
        color,
        pen_width,
        tool_id,
        tapered,
    }
}

/// Returns `(color, pen_width, tool_id, tapered)`. `tool_id` is `None` when
/// no marker is found at all (still-undecoded territory).
fn extract_color_and_width(data_blob: &[u8]) -> (Option<Color>, f32, Option<u8>, bool) {
    let mut color = None;
    let mut width: f32 = 0.8;

    // Find the last color marker: [VV, 00, TT, 00, 00, 00] with VV in {0x02, 0x03}.
    // Search only the tail (see MARKER_SEARCH_WINDOW doc comment) to avoid
    // coincidental matches inside per-point channel data.
    let search_start = data_blob.len().saturating_sub(MARKER_SEARCH_WINDOW);
    let long_pos = data_blob[search_start..]
        .windows(COLOR_MARKER_LEN)
        .rposition(|w| matches!(w[0], 0x02 | 0x03) && w[1] == 0x00 && w[3..] == [0x00, 0x00, 0x00])
        .map(|relative| search_start + relative);

    let (pos, marker_len, tool_id) = if let Some(pos) = long_pos {
        (
            Some(pos),
            COLOR_MARKER_LEN,
            Some(data_blob[pos + 2].saturating_sub(1) / 2),
        )
    } else {
        // Fallback: short-form marker (straight-line tool strokes), only
        // valid when immediately followed by a BGRA color (alpha 0xFF).
        let short_pos = data_blob[search_start..]
            .windows(SHORT_MARKER_LEN + 4)
            .rposition(|w| w[1] == 0x00 && w[2] == 0x00 && w[3] == 0x00 && w[7] == 0xFF)
            .map(|relative| search_start + relative);
        match short_pos {
            Some(pos) => (
                Some(pos),
                SHORT_MARKER_LEN,
                Some(data_blob[pos].saturating_sub(1) / 2),
            ),
            None => (None, 0, None),
        }
    };

    if let Some(pos) = pos {
        let after = &data_blob[pos + marker_len..];
        if after.len() >= 4 && after[3] == 0xFF {
            // BGRA color present
            color = Some(Color {
                r: after[2],
                g: after[1],
                b: after[0],
            });
            if after.len() >= 8 {
                width = f32::from_le_bytes([after[4], after[5], after[6], after[7]]);
            }
        } else if after.len() >= 4 {
            width = f32::from_le_bytes([after[0], after[1], after[2], after[3]]);
        }
    }

    let tapered = match (pos, tool_id) {
        (Some(pos), Some(tool_id)) => {
            has_pressure_taper(data_blob, pos, marker_len, tool_id, width)
        }
        _ => false,
    };

    (color, width, tool_id, tapered)
}

fn has_pressure_taper(
    data_blob: &[u8],
    pos: usize,
    marker_len: usize,
    tool_id: u8,
    width: f32,
) -> bool {
    let offset = pos + marker_len + 8; // marker + BGRA(4) + width(4)
    if offset + TAPER_TAG_LEN > data_blob.len() {
        return false;
    }
    let tag = u32::from_le_bytes(data_blob[offset..offset + 4].try_into().unwrap());
    if tag != 2 * tool_id as u32 {
        return false;
    }
    let width_dup = f32::from_le_bytes(data_blob[offset + 4..offset + 8].try_into().unwrap());
    (width_dup - width).abs() < 0.01
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_decode_sign_mag_positive() {
        let data = [42, 0x00, 10, 0x00];
        let vals = decode_sign_mag(&data, 0, 2);
        assert_eq!(vals, vec![42, 10]);
    }

    #[test]
    fn test_decode_sign_mag_negative() {
        let data = [42, 0x80, 10, 0x80];
        let vals = decode_sign_mag(&data, 0, 2);
        assert_eq!(vals, vec![-42, -10]);
    }

    #[test]
    fn test_decode_sign_mag_mixed() {
        let data = [5, 0x00, 3, 0x80, 7, 0x00];
        let vals = decode_sign_mag(&data, 0, 3);
        assert_eq!(vals, vec![5, -3, 7]);
    }

    #[test]
    fn test_decode_sign_mag_with_offset() {
        let data = [0xFF, 0xFF, 5, 0x00, 3, 0x80];
        let vals = decode_sign_mag(&data, 2, 2);
        assert_eq!(vals, vec![5, -3]);
    }

    #[test]
    fn test_decode_coordinates_simple() {
        // Two deltas: (+32/32, +64/32) then (+0, -32/32)
        let data = [
            32, 0x00, 64, 0x00, // dx=+1.0, dy=+2.0
            0, 0x00, 32, 0x80, // dx=+0.0, dy=-1.0
        ];
        let (points, n_bytes) = decode_coordinates(&data, 10.0, 20.0, 2);
        assert_eq!(points.len(), 3);
        assert!((points[0].x - 10.0).abs() < 1e-10);
        assert!((points[0].y - 20.0).abs() < 1e-10);
        assert!((points[1].x - 11.0).abs() < 1e-10);
        assert!((points[1].y - 22.0).abs() < 1e-10);
        assert!((points[2].x - 11.0).abs() < 1e-10);
        assert!((points[2].y - 21.0).abs() < 1e-10);
        assert_eq!(n_bytes, 8);
    }

    #[test]
    fn test_decode_coordinates_negative() {
        let data = [
            64, 0x80, 32, 0x80, // dx=-2.0, dy=-1.0
        ];
        let (points, n_bytes) = decode_coordinates(&data, 5.0, 5.0, 1);
        assert_eq!(points.len(), 2);
        assert!((points[1].x - 3.0).abs() < 1e-10);
        assert!((points[1].y - 4.0).abs() < 1e-10);
        assert_eq!(n_bytes, 4);
    }

    #[test]
    fn test_decode_coordinates_flag_low_bits_ignored() {
        // v4.4.x flag bytes carry metadata in bits 1-6; only bit 7 is the sign
        // and bit 0 is the resolution-doubling flag (tested separately below).
        let data = [
            32, 0x06, 64, 0x86, // dx=+1.0 (bit7=0), dy=-2.0 (bit7=1); bits 1-6 ignored
        ];
        let (points, n_bytes) = decode_coordinates(&data, 0.0, 0.0, 1);
        assert_eq!(points.len(), 2);
        assert!((points[1].x - 1.0).abs() < 1e-10);
        assert!((points[1].y + 2.0).abs() < 1e-10);
        assert_eq!(n_bytes, 4);
    }

    #[test]
    fn test_decode_coordinates_flag_bit0_doubles_resolution() {
        // "Straight-line" tool strokes (ruler-mode highlighter/marker) set bit 0
        // on every Y delta, which doubles that delta's resolution (scale 1/16
        // instead of 1/32). Confirmed on samples/OnlyHighlighterBlack_*.sdocx:
        // without this, decoded lines have the right start point and X span but
        // are too shallow and roughly half the height they should be.
        let data = [
            32, 0x00, 64, 0x01, // dx=+1.0 (normal), dy=+4.0 (bit0 set -> doubled)
        ];
        let (points, n_bytes) = decode_coordinates(&data, 0.0, 0.0, 1);
        assert_eq!(points.len(), 2);
        assert!((points[1].x - 1.0).abs() < 1e-10);
        assert!((points[1].y - 4.0).abs() < 1e-10);
        assert_eq!(n_bytes, 4);
    }

    #[test]
    fn test_extract_color_v4_4_marker() {
        // v4.4.x uses 0x03 as the color-marker version byte.
        let mut data = vec![0u8; 20];
        let marker_pos = 4;
        data[marker_pos..marker_pos + 6].copy_from_slice(&[0x03, 0x00, 0x01, 0x00, 0x00, 0x00]);
        data[marker_pos + 6] = 0x14; // B
        data[marker_pos + 7] = 0xA1; // G
        data[marker_pos + 8] = 0x47; // R
        data[marker_pos + 9] = 0xFF; // A
        let (color, _, tool_id, _) = extract_color_and_width(&data);
        assert_eq!(
            color,
            Some(Color {
                r: 0x47,
                g: 0xA1,
                b: 0x14
            })
        );
        assert_eq!(tool_id, Some(0));
    }

    #[test]
    fn test_extract_color_rejects_unknown_version() {
        // Leading byte must be 0x02 or 0x03; 0x01 is not a known version.
        // Byte 9 (0x07, not 0x00) also keeps this from accidentally looking
        // like a valid short-form marker (the long form's last 4 bytes,
        // [TT, 00, 00, 00], are themselves a valid short-form shape).
        let mut data = vec![0u8; 20];
        data[4..10].copy_from_slice(&[0x01, 0x00, 0x01, 0x00, 0x00, 0x07]);
        data[10] = 0x14;
        data[11] = 0xA1;
        data[12] = 0x47;
        data[13] = 0xFF;
        let (color, _, tool_id, _) = extract_color_and_width(&data);
        assert_eq!(color, None);
        // No valid marker -> tool is unidentified.
        assert_eq!(tool_id, None);
    }

    #[test]
    fn test_extract_color_decodes_tool_id() {
        // Marker byte 2 encodes tool_id * 2 + 1; e.g. 0x05 -> calligraphy pen (tool_id 2).
        let mut data = vec![0u8; 20];
        let marker_pos = 4;
        data[marker_pos..marker_pos + 6].copy_from_slice(&[0x02, 0x00, 0x05, 0x00, 0x00, 0x00]);
        let width_bytes = 7.71_f32.to_le_bytes();
        data[marker_pos + 6..marker_pos + 10].copy_from_slice(&width_bytes);

        let (_, width, tool_id, _) = extract_color_and_width(&data);
        assert_eq!(tool_id, Some(2));
        assert!((width - 7.71).abs() < 0.01);
    }

    #[test]
    fn test_extract_color_accepts_even_marker_byte() {
        // samples/OnlyHighlighterBlack_*.sdocx: "marker pen" uses byte2=0x04
        // (even) — the byte is not always odd, unlike the 5 ink tools.
        let mut data = vec![0u8; 20];
        let marker_pos = 4;
        data[marker_pos..marker_pos + 6].copy_from_slice(&[0x02, 0x00, 0x04, 0x00, 0x00, 0x00]);
        let width_bytes = 31.35_f32.to_le_bytes();
        data[marker_pos + 6..marker_pos + 10].copy_from_slice(&width_bytes);

        let (_, width, tool_id, _) = extract_color_and_width(&data);
        assert_eq!(tool_id, Some(1));
        assert!((width - 31.35).abs() < 0.01);
    }

    #[test]
    fn test_extract_color_ignores_match_outside_search_window() {
        // A marker-shaped byte sequence sitting in the per-point channel data,
        // far from the end, must not be mistaken for the real marker — this
        // is exactly the bug found on samples/OnlyHighlighterBlack_*.sdocx,
        // where long, low-variance strokes produced coincidental matches deep
        // inside the channel data.
        let mut data = vec![0u8; 300];
        data[10..16].copy_from_slice(&[0x02, 0x00, 0x04, 0x00, 0x00, 0x00]);
        let (color, width, tool_id, _) = extract_color_and_width(&data);
        assert_eq!(color, None);
        assert_eq!(tool_id, None);
        assert_eq!(width, 0.8);
    }

    #[test]
    fn test_extract_color_short_form_marker() {
        // "Straight-line" tool strokes (ruler-mode highlighter/marker) omit
        // the 2-byte version prefix: [TT, 00, 00, 00] + BGRA + f32 width,
        // with TT matching the same tool identity as the long-form marker
        // (here 0x01 = highlighter). Confirmed on
        // samples/OnlyHighlighterBlack_*.sdocx.
        let mut data = vec![0u8; 20];
        let marker_pos = 4;
        data[marker_pos..marker_pos + 4].copy_from_slice(&[0x01, 0x00, 0x00, 0x00]);
        data[marker_pos + 4] = 0x25; // B
        data[marker_pos + 5] = 0x25; // G
        data[marker_pos + 6] = 0x25; // R
        data[marker_pos + 7] = 0xFF; // A
        let width_bytes = 57.37_f32.to_le_bytes();
        data[marker_pos + 8..marker_pos + 12].copy_from_slice(&width_bytes);

        let (color, width, tool_id, _) = extract_color_and_width(&data);
        assert_eq!(
            color,
            Some(Color {
                r: 0x25,
                g: 0x25,
                b: 0x25
            })
        );
        assert_eq!(tool_id, Some(0));
        assert!((width - 57.37).abs() < 0.01);
    }

    #[test]
    fn test_extract_color_detects_pressure_taper() {
        // Ink-pen-category strokes carry a 12-byte block right after the
        // width float: a u32 equal to 2*tool_id, then the width repeated.
        // Confirmed on samples/OnlyPensBlacksize10_*.sdocx (tool_id=0=pen).
        let mut data = vec![0u8; 30];
        let marker_pos = 4;
        data[marker_pos..marker_pos + 6].copy_from_slice(&[0x02, 0x00, 0x01, 0x00, 0x00, 0x00]);
        data[marker_pos + 6] = 0x25; // B
        data[marker_pos + 7] = 0x25; // G
        data[marker_pos + 8] = 0x25; // R
        data[marker_pos + 9] = 0xFF; // A
        let width_bytes = 3.61_f32.to_le_bytes();
        data[marker_pos + 10..marker_pos + 14].copy_from_slice(&width_bytes);
        // tool_id=0 -> tag = 2*0 = 0
        data[marker_pos + 14..marker_pos + 18].copy_from_slice(&0u32.to_le_bytes());
        // width repeated
        data[marker_pos + 18..marker_pos + 22].copy_from_slice(&width_bytes);

        let (_, _, tool_id, tapered) = extract_color_and_width(&data);
        assert_eq!(tool_id, Some(0));
        assert!(tapered);
    }

    #[test]
    fn test_extract_color_short_form_marker_is_not_tapered() {
        // Highlighter/marker (short-form) strokes never carry the taper
        // block, even when the bytes right after width happen to be zero.
        let mut data = vec![0u8; 20];
        let marker_pos = 4;
        data[marker_pos..marker_pos + 4].copy_from_slice(&[0x01, 0x00, 0x00, 0x00]);
        data[marker_pos + 4] = 0x25;
        data[marker_pos + 5] = 0x25;
        data[marker_pos + 6] = 0x25;
        data[marker_pos + 7] = 0xFF;
        let width_bytes = 57.37_f32.to_le_bytes();
        data[marker_pos + 8..marker_pos + 12].copy_from_slice(&width_bytes);

        let (_, _, _, tapered) = extract_color_and_width(&data);
        assert!(!tapered);
    }

    #[test]
    fn test_extract_color_with_bgra() {
        // Marker + BGRA (B=0x14, G=0xA1, R=0x47, A=0xFF) + pen width
        let mut data = vec![0u8; 20];
        let marker_pos = 4;
        data[marker_pos..marker_pos + 6].copy_from_slice(&[0x02, 0x00, 0x01, 0x00, 0x00, 0x00]);
        data[marker_pos + 6] = 0x14; // B
        data[marker_pos + 7] = 0xA1; // G
        data[marker_pos + 8] = 0x47; // R
        data[marker_pos + 9] = 0xFF; // A
        let width_bytes = 5.54_f32.to_le_bytes();
        data[marker_pos + 10..marker_pos + 14].copy_from_slice(&width_bytes);

        let (color, width, _, _) = extract_color_and_width(&data);
        assert_eq!(
            color,
            Some(Color {
                r: 0x47,
                g: 0xA1,
                b: 0x14
            })
        );
        assert!((width - 5.54).abs() < 0.01);
    }

    #[test]
    fn test_extract_color_default() {
        // Marker + pen width only (no 0xFF at byte 3)
        let mut data = vec![0u8; 16];
        let marker_pos = 2;
        data[marker_pos..marker_pos + 6].copy_from_slice(&[0x02, 0x00, 0x01, 0x00, 0x00, 0x00]);
        let width_bytes = 9.12_f32.to_le_bytes();
        data[marker_pos + 6..marker_pos + 10].copy_from_slice(&width_bytes);

        let (color, width, _, _) = extract_color_and_width(&data);
        assert_eq!(color, None);
        assert!((width - 9.12).abs() < 0.01);
    }

    #[test]
    fn test_decode_trailing_pressure() {
        // Build a minimal data blob: 4 bytes of coord data + 4-byte gap + pressure deltas
        let n_coord_bytes = 4;
        let n_points = 3;

        let mut blob = vec![0u8; 100];
        // Pressure deltas at offset 8 (n_coord_bytes + 4): [100, +], [50, +], [20, -]
        let trail_start = n_coord_bytes + 4;
        blob[trail_start] = 100;
        blob[trail_start + 1] = 0x00; // +100
        blob[trail_start + 2] = 50;
        blob[trail_start + 3] = 0x00; // +50
        blob[trail_start + 4] = 20;
        blob[trail_start + 5] = 0x80; // -20

        let result = decode_trailing(&blob, n_coord_bytes, n_points);
        assert_eq!(result.pressures.len(), 3);
        // cumsum: 100, 150, 130 -> normalized: 100/1400, 150/1400, 130/1400
        assert!((result.pressures[0] - 100.0 / 1400.0).abs() < 1e-10);
        assert!((result.pressures[1] - 150.0 / 1400.0).abs() < 1e-10);
        assert!((result.pressures[2] - 130.0 / 1400.0).abs() < 1e-10);
    }
}
