use crate::decode::{decode_coordinates, decode_trailing};
use crate::error::{Error, Result};
use crate::types::{
    BoundingBox, Color, ColorRun, FontSizeRun, Page, PageElement, PageTemplate,
    PageTemplateSource, Point, RichTextBox, RichTextRun, Stroke,
};

// Layer/object tree constants (mirror pysdocx page.py):
const OBJECT_ENTRY_LEN: usize = 7; // raw_type(u8) + child_count(i16) + blob_size(u32)
const OBJECT_BASE_HEADER_LEN: usize = 105; // common object header before variable data
const OBJECT_BBOX_OFFSET: usize = 68; // stroke record starts here within a type-1 blob
const STROKE_OBJECT_BASE_TOTAL_SIZE: u32 = 121; // header total_size minus this = extra_len
/// Sanity cap for the recovered-bbox acceptance path ONLY — a trusted header
/// bbox is allowed any point count (real 23k-point strokes exist; see pysdocx).
const STROKE_MAX_POINTS: usize = 4000;

// Strokes with extra_len == 48 are a distinct "flat synthetic line" variant
// (confirmed on samples/Allsamsungnotes_260630_113259.sdocx, page e9561382,
// the "EVIDENZIATORE/PENNARELLO LINEA DRITTA" — straight-line highlighter/
// marker — labeled groups): bbox height is always exactly 1.0 px and the
// coordinate-delta-decoded points cover only a small fraction of the bbox
// width, in all 5 instances found across every sample checked, no
// counterexamples. The bbox itself (already correct — these strokes pass
// `fits_bbox` without needing recovery) is the real line; the decoded
// points are not the path to render, for reasons not yet understood.
const FLAT_LINE_EXTRA_LEN: usize = 48;
const FLAT_LINE_MAX_HEIGHT: f64 = 1.5;
const FLAT_LINE_MAX_DECODED_FRACTION: f64 = 0.5;

fn looks_like_flat_synthetic_line(stroke: &Stroke, extra_len: usize) -> bool {
    let bbox_width = stroke.bbox.x_max - stroke.bbox.x_min;
    let bbox_height = stroke.bbox.y_max - stroke.bbox.y_min;
    if extra_len != FLAT_LINE_EXTRA_LEN || bbox_height > FLAT_LINE_MAX_HEIGHT || bbox_width <= 0.0 {
        return false;
    }
    let Some(first) = stroke.points.first() else {
        return false;
    };
    let Some(last) = stroke.points.last() else {
        return false;
    };
    let decoded_len = (last.x - first.x).hypot(last.y - first.y);
    decoded_len < FLAT_LINE_MAX_DECODED_FRACTION * bbox_width
}

struct ParsedStroke {
    stroke: Stroke,
    /// Whether the decoded points actually lie within the stroke's bounding box.
    /// A misread start-point offset (wrong layout variant) scatters points far
    /// outside the box, so this tells a correct decode from a garbage one.
    fits_bbox: bool,
    /// Raw point count read from the record (pre-decode), for the sanity cap.
    n_points_field: usize,
}

/// One object from the layer/object tree, flattened depth-first.
struct PageObject {
    raw_type: u8,
    blob_off: usize,
    blob_end: usize,
}

/// Walk the page's layer table at `base` and every layer's object tree,
/// returning all objects flattened depth-first (parent before children).
fn parse_object_tree(data: &[u8], base: usize) -> Vec<PageObject> {
    let mut out = Vec::new();
    let Some(layer_count) = read_u16(data, base) else {
        return out;
    };
    let mut pos = base + 4; // u16 layer_count + u16 current_layer_index

    'layers: for _ in 0..layer_count {
        // u32 layer prefix
        if pos + 4 > data.len() {
            break;
        }
        pos += 4;
        // u32 next_offset + 4 flag bytes + u32 layer_flags
        if pos + 12 > data.len() {
            break;
        }
        let content_flags = data[pos + 7];
        pos += 12;

        if content_flags & 0x01 != 0 {
            pos += 1;
        }
        if content_flags & 0x02 != 0 {
            pos += 4;
        }
        for bit in [0x04u8, 0x08] {
            if content_flags & bit != 0 {
                match skip_utf16_string(data, pos) {
                    Some(next) => pos = next,
                    None => break 'layers,
                }
            }
        }
        if content_flags & 0x10 != 0 {
            if pos + 8 > data.len() {
                break;
            }
            pos += 8; // modified_time
        }
        if content_flags & 0x20 != 0 {
            pos += 4;
        }

        let Some(object_count) = read_u32(data, pos) else {
            break;
        };
        pos += 4;
        pos = parse_objects_into(data, pos, object_count as usize, 0, &mut out);
        pos += 32; // layer content hash
    }
    out
}

fn parse_objects_into(
    data: &[u8],
    mut pos: usize,
    count: usize,
    depth: usize,
    out: &mut Vec<PageObject>,
) -> usize {
    for _ in 0..count {
        if pos + OBJECT_ENTRY_LEN > data.len() {
            break;
        }
        let raw_type = data[pos];
        let child_count = i16::from_le_bytes(data[pos + 1..pos + 3].try_into().unwrap());
        let blob_size = u32::from_le_bytes(data[pos + 3..pos + 7].try_into().unwrap()) as usize;
        let blob_off = pos + OBJECT_ENTRY_LEN;
        let Some(blob_end) = blob_off.checked_add(blob_size).filter(|&e| e <= data.len()) else {
            break;
        };
        out.push(PageObject {
            raw_type,
            blob_off,
            blob_end,
        });
        pos = blob_end;
        if child_count > 0 && depth < 16 {
            pos = parse_objects_into(data, pos, child_count as usize, depth + 1, out);
        }
    }
    pos
}

/// Skip a length-prefixed UTF-16 string: i16 char count, then chars.
fn skip_utf16_string(data: &[u8], offset: usize) -> Option<usize> {
    let char_len = read_i16(data, offset)?;
    if char_len < 0 {
        return None;
    }
    let end = offset + 2 + char_len as usize * 2;
    (end <= data.len()).then_some(end)
}

/// The decoded common object header at the start of an object blob
/// (mirrors pysdocx `_parse_object_header`; only the fields consumers need).
struct ObjectHeader {
    total_size: u32,
    field_flags: u64,
    bbox: BoundingBox,
}

/// Parse the common object header at the start of a blob (mirrors pysdocx
/// `_parse_object_header`). Strokes only need `total_size` (it yields
/// `extra_len`); text boxes also use `field_flags` (rotation gate) and the
/// header `bbox`.
fn parse_object_header(blob: &[u8]) -> Option<ObjectHeader> {
    if blob.len() < OBJECT_BASE_HEADER_LEN {
        return None;
    }
    let total_size = read_u32(blob, 0)?;
    let mut pos = 4 + 2 + 4; // total_size + data_type + var_data_offset
    let flag_len = *blob.get(pos)? as usize;
    pos += 1 + flag_len;
    let field_len = *blob.get(pos)? as usize;
    let mut field_flags: u64 = 0;
    for (i, &b) in blob.get(pos + 1..pos + 1 + field_len.min(8))?.iter().enumerate() {
        field_flags |= (b as u64) << (8 * i);
    }
    pos += 1 + field_len;
    pos += 4; // format_version
    let uuid_byte_len = read_i16(blob, pos)?;
    if uuid_byte_len < 0 {
        return None;
    }
    pos += 2 + uuid_byte_len as usize;
    pos += 8; // modified_time
    let bbox = BoundingBox {
        x_min: read_f64(blob, pos)?,
        y_min: read_f64(blob, pos + 8)?,
        x_max: read_f64(blob, pos + 16)?,
        y_max: read_f64(blob, pos + 24)?,
    };
    pos += 32;
    pos += 4 + 1; // timestamp + resizable
    (pos <= blob.len()).then_some(ObjectHeader {
        total_size,
        field_flags,
        bbox,
    })
}

/// The stroke-header bbox itself is a plausible page-sized rectangle (generous
/// 2x margin). `points_fit_bbox` only checks containment, so an astronomically
/// large garbage bbox (seen: ~1e150) trivially "contains" any points — this
/// closes that loophole.
fn bbox_is_page_scaled(bbox: &BoundingBox, width: u32, height: u32) -> bool {
    let (mx, my) = (width as f64 * 2.0, height as f64 * 2.0);
    bbox.x_min.is_finite()
        && bbox.y_min.is_finite()
        && bbox.x_max.is_finite()
        && bbox.y_max.is_finite()
        && -mx <= bbox.x_min
        && bbox.x_min <= bbox.x_max
        && bbox.x_max <= width as f64 + mx
        && -my <= bbox.y_min
        && bbox.y_min <= bbox.y_max
        && bbox.y_max <= height as f64 + my
}

/// A correctly-decoded stroke's points fall inside its bounding box, which
/// Samsung stores as the exact min/max of those points. When a layout variant
/// misreads the absolute start point, the decoded coordinates land wildly
/// outside the box (e.g. `1e266` or collapsed on the origin), so bbox
/// containment distinguishes the right layout from a garbage one.
fn points_fit_bbox(points: &[Point], bbox: &BoundingBox) -> bool {
    const TOL: f64 = 4.0;
    if points.is_empty()
        || ![bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max]
            .iter()
            .all(|v| v.is_finite())
        || bbox.x_max < bbox.x_min
        || bbox.y_max < bbox.y_min
    {
        return false;
    }
    let inside = points
        .iter()
        .filter(|p| {
            p.x >= bbox.x_min - TOL
                && p.x <= bbox.x_max + TOL
                && p.y >= bbox.y_min - TOL
                && p.y <= bbox.y_max + TOL
        })
        .count();
    inside * 5 >= points.len() * 4 // >= 80% inside
}

/// All points are finite and lie within the page (a generous margin allows for
/// content that slightly overflows the page rectangle). Distinguishes a real
/// on-page decode from garbage coordinates (e.g. `1e266`) or NaN.
fn within_page_bounds(points: &[Point], width: u32, height: u32) -> bool {
    if points.len() < 2 {
        return false;
    }
    let mx = (width as f64 * 0.1).max(50.0);
    let my = (height as f64 * 0.1).max(50.0);
    let (w, h) = (width as f64, height as f64);
    points.iter().all(|p| {
        p.x.is_finite()
            && p.y.is_finite()
            && p.x >= -mx
            && p.x <= w + mx
            && p.y >= -my
            && p.y <= h + my
    })
}

/// Axis-aligned bounds of a decoded point set.
fn bbox_of(points: &[Point]) -> BoundingBox {
    let mut b = BoundingBox {
        x_min: f64::MAX,
        y_min: f64::MAX,
        x_max: f64::MIN,
        y_max: f64::MIN,
    };
    for p in points {
        b.x_min = b.x_min.min(p.x);
        b.y_min = b.y_min.min(p.y);
        b.x_max = b.x_max.max(p.x);
        b.y_max = b.y_max.max(p.y);
    }
    b
}

/// Parse a `.page` binary file into a `Page`.
///
/// Layout: `base = u32 @ 0x00`; stroke count at `base + 0x66`; first stroke at `base + 0xB5`.
/// Each stroke is preceded by a 71-byte record; on v4.4.x+, byte 3 of that record encodes
/// an extra-attribute-block length (value − 0x79) injected inside the stroke's metadata.
pub fn parse_page(data: &[u8]) -> Result<Page> {
    if data.len() < 0xA0 {
        return Err(Error::Format("page file too short for header".into()));
    }

    // Base offset at 0x00 — shifts stroke fields for files with embedded media
    let base = u32::from_le_bytes(data[0x00..0x04].try_into().unwrap()) as usize;

    // Page dimensions at 0x16 and 0x1A
    let width = u32::from_le_bytes(data[0x16..0x1A].try_into().unwrap());
    let height = u32::from_le_bytes(data[0x1A..0x1E].try_into().unwrap());

    // Page UUID at 0x28, length at 0x26
    let uuid_char_len = u16::from_le_bytes(data[0x26..0x28].try_into().unwrap()) as usize;
    let uuid_bytes = &data[0x28..0x28 + uuid_char_len * 2];
    let uuid: String = uuid_bytes
        .chunks_exact(2)
        .map(|c| u16::from_le_bytes([c[0], c[1]]))
        .map(|c| char::from_u32(c as u32).unwrap_or('\u{FFFD}'))
        .collect();

    // Content bounding box at 0x80 (4 x f64)
    let content_bbox = BoundingBox {
        x_min: f64::from_le_bytes(data[0x80..0x88].try_into().unwrap()),
        y_min: f64::from_le_bytes(data[0x88..0x90].try_into().unwrap()),
        x_max: f64::from_le_bytes(data[0x90..0x98].try_into().unwrap()),
        y_max: f64::from_le_bytes(data[0x98..0xA0].try_into().unwrap()),
    };

    let background_color = page_background_color(data, base, width);
    let template = background_color.and_then(|_| page_template(data, base, width));

    // Walk the layer/object tree (deterministic `type, child_count, size, blob`
    // boundaries) and decode only raw type-1 objects as strokes. The old flat
    // stroke walk derailed at the first interleaved non-stroke object and lost
    // every stroke after it — up to ~75% of a mixed page (see pysdocx
    // parse_page, which this mirrors).
    let objects = parse_object_tree(data, base);
    let mut strokes = Vec::new();

    for obj in &objects {
        if obj.raw_type != 1 {
            continue;
        }
        let blob = &data[obj.blob_off..obj.blob_end];
        let Some(total_size) = parse_object_header(blob).map(|h| h.total_size) else {
            continue;
        };
        let extra_len = total_size.saturating_sub(STROKE_OBJECT_BASE_TOTAL_SIZE) as usize;
        let stroke_off = obj.blob_off + OBJECT_BBOX_OFFSET;

        let current = parse_stroke(data, stroke_off, extra_len, StrokeLayout::Current);
        let shifted = parse_stroke(data, stroke_off, extra_len, StrokeLayout::StartPointMinusThree);

        // Pick the layout whose decoded points are consistent with the stroke's
        // bounding box, not the one that merely yields more points — a garbage
        // decode can read a larger (bogus) point count and win the old tiebreak.
        let parsed = match (current, shifted) {
            (Some(current), Some(shifted)) => Some(match (current.fits_bbox, shifted.fits_bbox) {
                (true, false) => current,
                (false, true) => shifted,
                // Both consistent: keep the legacy "more points" tiebreak.
                (true, true) if shifted.stroke.points.len() > current.stroke.points.len() => {
                    shifted
                }
                (true, true) => current,
                (false, false) => current,
            }),
            (current, shifted) => current.or(shifted),
        };
        let Some(mut parsed) = parsed else { continue };

        // `points_fit_bbox` alone is loopholed by a garbage header bbox so huge it
        // trivially contains anything — require the bbox itself to be page-scaled.
        let trusted_bbox =
            parsed.fits_bbox && bbox_is_page_scaled(&parsed.stroke.bbox, width, height);
        if trusted_bbox {
            // No point cap here: a trusted bbox with a big count is a real,
            // detailed stroke (see pysdocx quiz.sdocx handoff note).
            if looks_like_flat_synthetic_line(&parsed.stroke, extra_len) {
                let bbox = parsed.stroke.bbox;
                parsed.stroke.points = vec![
                    Point { x: bbox.x_min, y: bbox.y_min },
                    Point { x: bbox.x_max, y: bbox.y_max },
                ];
            }
            strokes.push(parsed.stroke);
        } else if parsed.n_points_field <= STROKE_MAX_POINTS
            && within_page_bounds(&parsed.stroke.points, width, height)
        {
            // The header bbox isn't trustworthy (e.g. ruler lines store a
            // different rectangle), but the decoded points form a coherent
            // on-page path — keep the geometry and recompute the bbox. The
            // point cap guards this evidence-from-points-alone path against a
            // misaligned decode fabricating a huge plausible-looking cloud.
            parsed.stroke.bbox = bbox_of(&parsed.stroke.points);
            strokes.push(parsed.stroke);
        }
        // else: genuinely off-page/garbage → drop
    }

    let mut elements = parse_page_elements(data, &objects, width, height);
    scan_sticky_notes(data, width, height, &mut elements);

    Ok(Page {
        uuid,
        width,
        height,
        content_bbox,
        background_color,
        template,
        strokes,
        elements,
    })
}

#[derive(Clone, Copy)]
enum StrokeLayout {
    Current,
    StartPointMinusThree,
}

fn parse_stroke(
    data: &[u8],
    off: usize,
    extra_len: usize,
    layout: StrokeLayout,
) -> Option<ParsedStroke> {
    let bbox = BoundingBox {
        x_min: read_f64(data, off)?,
        y_min: read_f64(data, off + 8)?,
        x_max: read_f64(data, off + 16)?,
        y_max: read_f64(data, off + 24)?,
    };

    let (meta_off, n_points_off, sp_off) = match layout {
        StrokeLayout::Current => (off + 32 + extra_len, 39, off + 73 + extra_len),
        StrokeLayout::StartPointMinusThree => (off + 32, 36, off + 70),
    };

    let data_len = read_u32(data, meta_off + 21)? as usize;
    let n_points = read_u16(data, meta_off + n_points_off)? as usize;
    let start_x = read_f64(data, sp_off)?;
    let start_y = read_f64(data, sp_off + 8)?;
    if !start_x.is_finite() || !start_y.is_finite() || n_points == 0 {
        return None;
    }

    let data_off = sp_off + 16;
    let data_end = data_off.checked_add(data_len)?;
    if data_end > data.len() {
        return None;
    }
    let data_blob = &data[data_off..data_end];

    let (points, n_coord_bytes) =
        decode_coordinates(data_blob, start_x, start_y, n_points.saturating_sub(1));
    if points.is_empty()
        || points
            .iter()
            .any(|point| !point.x.is_finite() || !point.y.is_finite())
    {
        return None;
    }

    let trailing = decode_trailing(data_blob, n_coord_bytes, points.len().saturating_sub(1));
    let fits_bbox = points_fit_bbox(&points, &bbox);

    Some(ParsedStroke {
        stroke: Stroke {
            bbox,
            points,
            pressures: trailing.pressures,
            timestamps: trailing.timestamps,
            tilt_x: trailing.tilt_x,
            tilt_y: trailing.tilt_y,
            color: trailing.color,
            pen_width: trailing.pen_width,
            tool_id: trailing.tool_id,
            tapered: trailing.tapered,
        },
        fits_bbox,
        n_points_field: n_points,
    })
}

fn read_i16(data: &[u8], offset: usize) -> Option<i16> {
    Some(i16::from_le_bytes(
        data.get(offset..offset + 2)?.try_into().ok()?,
    ))
}

fn read_u16(data: &[u8], offset: usize) -> Option<u16> {
    Some(u16::from_le_bytes(
        data.get(offset..offset + 2)?.try_into().ok()?,
    ))
}

fn read_u32(data: &[u8], offset: usize) -> Option<u32> {
    Some(u32::from_le_bytes(
        data.get(offset..offset + 4)?.try_into().ok()?,
    ))
}

fn read_f64(data: &[u8], offset: usize) -> Option<f64> {
    Some(f64::from_le_bytes(
        data.get(offset..offset + 8)?.try_into().ok()?,
    ))
}

/// Decode the page's stored **paper (background) color** from the `.page` header.
///
/// RE-validated (2026-07-09, `samples/test-background/` one-variable samples): the
/// paper color is a real header field — a `BGRA` quad with `alpha == 0xFF` — sitting
/// in the record `[u32 kind][BGRA paper_color][u32 display_width]`. The `kind` u32 is
/// 2 (or 3 on some devices); `display_width` is the device paper width. The record's
/// absolute offset varies with a variable-length header preamble (seen at 0x84 / 0xA4
/// / 0x13e / 0x15e), so it is located by that signature rather than a fixed offset —
/// the old fixed-offset heuristic (0x84/0x80/0xA4 by `base`) misread base-0x8c pages
/// as having no paper. The signature yields exactly one match on all 122 pages of the
/// 14-sample corpus + the 4 background test samples (the `Rosina` pink sample —
/// `(245,221,221)` — pins the field; every corpus note is a single light paper across
/// all its pages, e.g. `(252,252,252)` / `(230,230,230)`).
///
/// Offset `M` of the page's paper record `[BGRA (alpha 0xFF)][u32 display_width]`, or `None`.
///
/// Searches the header preamble `[0x7c, base)`. `0x7c` skips the fixed leading fields (uuid + the
/// two u32 canvas dims at 0x78/0x7c) so a spurious `..FF` inside them can't match. Primary gate:
/// `kind` (u32 at M-4) in 1..=8 with a plausible width — matches every corpus + background page.
/// Fallback: a record whose `display_width` equals the page width — for PDF-template / PDF-import
/// notes, whose header preamble puts a value outside 1..=8 where `kind` normally sits (e.g. 4000),
/// so the primary gate misses them although they carry the same `[BGRA][width]` record. Shared by
/// `page_background_color` and `page_pdf_template` (mirrors pysdocx `_locate_paper_record`).
fn locate_paper_record(data: &[u8], base: usize, page_width: u32) -> Option<usize> {
    // Bound by room for the paper record itself (`[BGRA][u32 width]`, i.e. M+8); the PDF fields
    // (M+16) are read separately by page_pdf_template, which returns None if the page is shorter.
    let hi = base.min(data.len().saturating_sub(8));
    for off in 0x7c..hi {
        if data[off + 3] != 0xFF {
            continue;
        }
        let kind = read_u32(data, off - 4)?;
        let display_width = read_u32(data, off + 4)?;
        if (1..=8).contains(&kind) && (256..=40_000).contains(&display_width) {
            return Some(off);
        }
    }
    (0x7c..hi).find(|&off| data[off + 3] == 0xFF && read_u32(data, off + 4) == Some(page_width))
}

fn page_background_color(data: &[u8], base: usize, page_width: u32) -> Option<crate::types::Color> {
    let m = locate_paper_record(data, base, page_width)?;
    Some(crate::types::Color {
        r: data[m + 2],
        g: data[m + 1],
        b: data[m],
    })
}

/// Decode a page's PDF-template / PDF-import reference `(media_index, page_index)`, or `None`.
///
/// Multi-page "Academic" templates (Notebook, Planner, …) and imported PDFs are not procedural
/// like the built-in backgrounds: the artwork is a real PDF embedded under `media/`, and each
/// `.page` references one of its pages in the 8 bytes right after the paper record `M`:
///
/// ```text
/// M+8  u16 flag            == 1 on every observed PDF page (a count? — assumed)
/// M+A  u16 media_index     -> media/<index>@<name>.pdf
/// M+C  u16 reserved        == 0 on PDF pages; == 1 on built-in pages (M+8 holds the id there)
/// M+E  u16 page_index      -> 0-based page within that PDF
/// ```
///
/// `flag == 1 && reserved == 0` separates PDF pages from built-in ones with zero counterexamples
/// across the 150-page corpus (mirrors pysdocx `page_pdf_template`). RE 2026-07-09 on the
/// Notebook&Planner Academic sample, cross-checked against the imported-PDF page in `quiz.sdocx`.
fn page_pdf_template(data: &[u8], base: usize, page_width: u32) -> Option<(u32, u32)> {
    let m = locate_paper_record(data, base, page_width)?;
    let flag = read_u16(data, m + 8)?;
    let reserved = read_u16(data, m + 0xC)?;
    if flag != 1 || reserved != 0 {
        return None;
    }
    let media_index = read_u16(data, m + 0xA)? as u32;
    let page_index = read_u16(data, m + 0xE)? as u32;
    Some((media_index, page_index))
}

fn page_template(data: &[u8], base: usize, page_width: u32) -> Option<PageTemplate> {
    // PDF-backed pages are detected by the marker (any `base`), so this also correctly classifies
    // imported-PDF pages that the built-in offsets below would misread as a template id.
    if let Some((media_index, page_index)) = page_pdf_template(data, base, page_width) {
        return Some(PageTemplate {
            id: page_index,
            source: PageTemplateSource::CustomPdf {
                media_index,
                page_index,
            },
        });
    }

    let id = match base {
        // Short built-in template page records store the template id in the compact header.
        0x90 => read_u32(data, 0x8C)?,
        _ if base >= 0xE7 => read_u32(data, 0xAC)?,
        _ => read_u32(data, 0xB4)?,
    };
    is_builtin_template_id(id).then_some(PageTemplate {
        id,
        source: PageTemplateSource::BuiltIn,
    })
}

fn is_builtin_template_id(id: u32) -> bool {
    id != 0 && id <= 0xFFFF
}

/// Upper bound on an object record so `parse_text_box_record`/`looks_like_image_record`
/// never scan into the next object (or the whole rest of a multi-MB page).
const MAX_OBJECT_RECORD_LEN: usize = 16 * 1024;

fn parse_page_elements(
    data: &[u8],
    objects: &[PageObject],
    width: u32,
    height: u32,
) -> Vec<PageElement> {
    let mut elements = Vec::new();

    for obj in objects {
        // Type-1 objects are strokes; their coordinate streams could otherwise
        // produce false marker/bbox matches, so never scan them for elements.
        if obj.raw_type == 1 {
            continue;
        }
        let blob = &data[obj.blob_off..obj.blob_end];

        // pysdocx `_classify_page_object` precedence: an image placement marker
        // claims the object even when its media index fails to decode — never
        // text- or shape-scan those blobs.
        if find_sub(blob, IMAGE_MARKER).is_some() {
            if let Some(uuid_off) = find_uuid_in(data, obj.blob_off, obj.blob_off + 96)
                && let Some(bbox) = find_object_bbox(data, uuid_off, width, height) {
                    let record_end = obj.blob_end.min(uuid_off + MAX_OBJECT_RECORD_LEN);
                    if let Some(media_index) = image_media_index(&data[uuid_off..record_end]) {
                        elements.push(PageElement::Image { bbox, media_index });
                    }
                }
            continue;
        }

        // Text boxes are raw type-2 objects whose blob decodes as text
        // (pysdocx `_classify_page_object`).
        if obj.raw_type == 2
            && let Some(text_box) = parse_text_box_object(blob) {
                elements.push(PageElement::TextBox(text_box));
                continue;
            }

        let mut shapes = Vec::new();
        crate::shape::parse_shapes_in_object(
            data,
            obj.blob_off,
            obj.blob_end,
            width,
            height,
            &mut shapes,
        );
        elements.extend(shapes.into_iter().map(PageElement::Shape));
    }

    elements
}

/// First ascii UUID starting in `[start, end)` (the UUID may extend past `end`).
fn find_uuid_in(data: &[u8], start: usize, end: usize) -> Option<usize> {
    let last = end.min(data.len().saturating_sub(36));
    (start..last).find(|&off| is_ascii_uuid(&data[off..off + 36]))
}

fn is_ascii_uuid(bytes: &[u8]) -> bool {
    bytes.len() == 36
        && bytes.iter().enumerate().all(|(i, &b)| match i {
            8 | 13 | 18 | 23 => b == b'-',
            _ => b.is_ascii_hexdigit(),
        })
}

fn find_object_bbox(data: &[u8], uuid_off: usize, width: u32, height: u32) -> Option<BoundingBox> {
    let search_end = (uuid_off + 128).min(data.len().saturating_sub(32));
    for offset in uuid_off + 36..=search_end {
        let bbox = BoundingBox {
            x_min: read_f64(data, offset)?,
            y_min: read_f64(data, offset + 8)?,
            x_max: read_f64(data, offset + 16)?,
            y_max: read_f64(data, offset + 24)?,
        };
        if plausible_bbox(bbox, width, height) {
            return Some(bbox);
        }
    }

    None
}

fn plausible_bbox(bbox: BoundingBox, width: u32, height: u32) -> bool {
    bbox.x_min.is_finite()
        && bbox.y_min.is_finite()
        && bbox.x_max.is_finite()
        && bbox.y_max.is_finite()
        && bbox.x_min >= 1.0
        && bbox.y_min >= 1.0
        && bbox.x_max > bbox.x_min
        && bbox.y_max > bbox.y_min
        && bbox.x_max <= width as f64 * 1.25
        && bbox.y_max <= height as f64 * 1.25
        && bbox.x_max - bbox.x_min > 8.0
        && bbox.y_max - bbox.y_min > 8.0
}

/// Imported-image placement marker inside an object record (see pysdocx
/// `scan_images`: `01 00 04 20`, u16 media index 6 bytes before, 4 x f64 bbox
/// 11 bytes after).
const IMAGE_MARKER: &[u8] = b"\x01\x00\x04\x20";
/// Preferred media reference: a u32 archive index right after this marker,
/// searched within 180 bytes of the placement marker (pysdocx
/// `_image_media_index`).
const IMAGE_MEDIA_REF_MARKER: &[u8] = b"\x06\x00\x3e\x00\x00\x00\x02\x00";

fn find_sub(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

/// Decode the GLOBAL media archive index referenced by an image record — the
/// `<index>@` prefix of the media member's basename. Returns `None` when the
/// record has no image placement marker (i.e. it is not an image record).
fn image_media_index(record: &[u8]) -> Option<usize> {
    let marker = find_sub(record, IMAGE_MARKER)?;
    let search_end = (marker + 180).min(record.len());
    if let Some(rel) = find_sub(&record[marker..search_end], IMAGE_MEDIA_REF_MARKER) {
        let off = marker + rel + IMAGE_MEDIA_REF_MARKER.len();
        if off + 4 <= record.len() {
            let idx = u32::from_le_bytes(record[off..off + 4].try_into().unwrap());
            return Some(idx as usize);
        }
    }
    let off = marker.checked_sub(6)?;
    Some(u16::from_le_bytes(record[off..off + 2].try_into().unwrap()) as usize)
}

// ---------------------------------------------------------------------------
// Text-box objects (pysdocx `parse_text_boxes_from_objects` and helpers).
//
// The box text uses the `06 00 <u16 kind> 00 00 <u32 char_count>` marker; the
// style runs right after it reuse note.note's local TLV families
// (`18 00 <tag> 00 | pad | u32 start | u32 end | u32 value | u32 enabled`,
// plus `14 00 14 00` for strikethrough), with offsets local to the box text.
// ---------------------------------------------------------------------------

/// `06 00 <u16 kind> 00 00 <u32 char_count>` then UTF-16LE text.
const TEXT_BOX_TEXT_PREFIX: [u8; 2] = [0x06, 0x00];
const TEXT_BOX_TEXT_MARKER_LEN: usize = 10;

// TLV style-run layout (pysdocx note.py RUN_*): 4-byte marker, 2 pad bytes,
// then u32 start / end / value / enabled.
const RUN_START_OFF: usize = 6;
const RUN_END_OFF: usize = 10;
const RUN_ENABLED_OFF: usize = 18;
const RUN_MARKER_LEN: usize = 22;

const BOLD_TAG: u16 = 0x05;
const ITALIC_TAG: u16 = 0x06;
const UNDERLINE_TAG: u16 = 0x07;
const COLOR_TAG: u16 = 0x01;
const FONT_TAG: u16 = 0x03;
const HIGHLIGHT_TAG: u16 = 0x11;
const STRIKETHROUGH_MARKER: [u8; 4] = [0x14, 0x00, 0x14, 0x00];

/// Rotation angle: gated by `field_flags & 0x1`, a plain f32 in degrees
/// (clockwise-positive on screen) at the common header's attributes offset
/// (pysdocx IMAGE_ANGLE_OFFSET/IMAGE_ANGLE_FIELD_FLAG — shared with images).
const ANGLE_FIELD_FLAG: u64 = 0x1;
const ANGLE_OFFSET: usize = OBJECT_BASE_HEADER_LEN;

/// Parse one raw type-2 object blob as a rich text box (pysdocx
/// `_text_box_rich_text` + object-level bbox/angle/frame-midpoints).
fn parse_text_box_object(blob: &[u8]) -> Option<RichTextBox> {
    let header = parse_object_header(blob)?;
    let (text_off, text, raw_char_len) = text_box_text(blob)?;
    let scan_start = text_off + raw_char_len * 2;
    let styles = scan_rich_text_styles(blob, scan_start, raw_char_len, text.chars().count());

    let rotation_degrees = object_rotation_degrees(blob, header.field_flags);
    let frame_midpoints = text_box_frame_midpoints(blob, &header);

    Some(RichTextBox {
        bbox: header.bbox,
        rotation_degrees,
        text,
        color: styles.colors.first().map(|c| c.color),
        highlight_color: styles.highlights.first().map(|c| c.color),
        underline: styles.runs.iter().any(|r| r.underline),
        font_size: styles.font_sizes.first().map(|f| f.size),
        runs: styles.runs,
        colors: styles.colors,
        highlights: styles.highlights,
        font_sizes: styles.font_sizes,
        frame_midpoints,
    })
}

/// Rotation angle in degrees for any object with a common header
/// (pysdocx `_image_rotation_deg`); `None` when unset or zero.
fn object_rotation_degrees(blob: &[u8], field_flags: u64) -> Option<f64> {
    if field_flags & ANGLE_FIELD_FLAG == 0 || ANGLE_OFFSET + 4 > blob.len() {
        return None;
    }
    let angle = f32::from_le_bytes(blob[ANGLE_OFFSET..ANGLE_OFFSET + 4].try_into().unwrap());
    if !angle.is_finite() {
        return None;
    }
    let deg = (angle as f64).rem_euclid(360.0);
    (deg != 0.0).then_some(deg)
}

// Inserted-object geometry wrapper right after the common header
// (pysdocx `_decode_payload_geometry`): u32 l0, u16 tag=6, u32 l1,
// 4-byte opcode, u32 point_count, then (f64 x, f64 y) points.
const PAYLOAD_GEOMETRY_TAG: u16 = 6;
const PAYLOAD_GEOMETRY_OPCODE: [u8; 4] = [0x01, 0x00, 0x01, 0x0C];
const PAYLOAD_GEOMETRY_HEADER_LEN: usize = 18;

/// The 4 stored edge-midpoints of a text-box frame, accepted only when their
/// centroid matches the header bbox center (pysdocx `_text_box_frame_midpoints`):
/// preferred source is the payload-geometry wrapper (4 points); the raw scan at
/// `total_size + 0x12` is the fallback for rotated boxes without one.
fn text_box_frame_midpoints(blob: &[u8], header: &ObjectHeader) -> Option<[Point; 4]> {
    let read4 = |start: usize| -> Option<[Point; 4]> {
        let mut pts = [Point { x: 0.0, y: 0.0 }; 4];
        for (i, pt) in pts.iter_mut().enumerate() {
            pt.x = read_f64(blob, start + i * 16)?;
            pt.y = read_f64(blob, start + i * 16 + 8)?;
            if !pt.x.is_finite() || !pt.y.is_finite() {
                return None;
            }
        }
        let cx = pts.iter().map(|p| p.x).sum::<f64>() / 4.0;
        let cy = pts.iter().map(|p| p.y).sum::<f64>() / 4.0;
        let bbox_cx = (header.bbox.x_min + header.bbox.x_max) / 2.0;
        let bbox_cy = (header.bbox.y_min + header.bbox.y_max) / 2.0;
        ((cx - bbox_cx).abs() <= 1.0 && (cy - bbox_cy).abs() <= 1.0).then_some(pts)
    };

    if let Some(points_off) = payload_geometry_4_points(blob, header)
        && let Some(pts) = read4(points_off) {
            return Some(pts);
        }
    if header.field_flags & ANGLE_FIELD_FLAG != 0 {
        return read4(header.total_size as usize + 0x12);
    }
    None
}

/// Offset of the payload-geometry wrapper's point array when it holds exactly
/// 4 points (the text-box frame case).
fn payload_geometry_4_points(blob: &[u8], header: &ObjectHeader) -> Option<usize> {
    let start = header.total_size as usize;
    if start + PAYLOAD_GEOMETRY_HEADER_LEN > blob.len() {
        return None;
    }
    if read_u16(blob, start + 4)? != PAYLOAD_GEOMETRY_TAG
        || blob[start + 10..start + 14] != PAYLOAD_GEOMETRY_OPCODE
    {
        return None;
    }
    let point_count = read_u32(blob, start + 14)? as usize;
    let points_start = start + PAYLOAD_GEOMETRY_HEADER_LEN;
    (point_count == 4 && points_start + 4 * 16 <= blob.len()).then_some(points_start)
}

/// Lexicographic "note-likeness" score for candidate decoded strings
/// (pysdocx `_text_score`).
fn text_score(text: &str) -> (usize, usize, usize) {
    let stripped = text.trim();
    if stripped.is_empty() {
        return (0, 0, 0);
    }
    let mut ascii_printable = 0;
    let mut letters = 0;
    let mut separators = 0;
    for ch in stripped.chars() {
        if ch == '\n' || (' '..='~').contains(&ch) {
            ascii_printable += 1;
        }
        if ch.is_alphabetic() {
            letters += 1;
        }
        if ch.is_whitespace() || ".,;:!?'-_/()".contains(ch) {
            separators += 1;
        }
    }
    (
        ascii_printable + letters + separators,
        ascii_printable,
        stripped.chars().count(),
    )
}

/// The box text: marker-based first (`_text_from_marker`), best-scored
/// printable UTF-16 run as fallback (`_text_box_text`). Returns
/// `(text_offset, text, raw_char_len)` — `raw_char_len` in u16 code units.
fn text_box_text(blob: &[u8]) -> Option<(usize, String, usize)> {
    if let Some(parsed) = text_from_marker(blob) {
        return Some(parsed);
    }
    // Fallback: best-scored printable UTF-16 run after the common header.
    let mut best: Option<(usize, String)> = None;
    let mut best_score = (0, 0, 0);
    let mut offset = OBJECT_BASE_HEADER_LEN;
    while offset + 6 <= blob.len() {
        let mut units: Vec<u16> = Vec::new();
        let mut end = offset;
        while end + 2 <= blob.len() {
            let unit = u16::from_le_bytes([blob[end], blob[end + 1]]);
            if unit != 0x0A && !(0x20..=0xD7FF).contains(&unit) {
                break;
            }
            units.push(unit);
            end += 2;
        }
        if units.len() >= 3
            && let Ok(text) = String::from_utf16(&units) {
                let text = text.trim_matches('\0').to_string();
                if !text.trim().is_empty() {
                    let score = text_score(&text);
                    if score > best_score {
                        best_score = score;
                        best = Some((offset, text));
                    }
                }
            }
        offset = if end > offset { end } else { offset + 2 };
    }
    let (off, text) = best?;
    let text = text.trim_end_matches('\n').to_string();
    let len = text.chars().count();
    Some((off, text, len))
}

/// All `06 00` text markers in the blob, best-scored decode wins
/// (pysdocx `_text_from_marker` + `_decode_text_box_marker`).
fn text_from_marker(blob: &[u8]) -> Option<(usize, String, usize)> {
    let mut best: Option<(usize, String, usize)> = None;
    let mut best_score = (0, 0, 0);
    let mut off = OBJECT_BASE_HEADER_LEN;
    while off + TEXT_BOX_TEXT_MARKER_LEN <= blob.len() {
        let Some(marker) = find_sub(&blob[off..], &TEXT_BOX_TEXT_PREFIX).map(|i| off + i) else {
            break;
        };
        if marker + TEXT_BOX_TEXT_MARKER_LEN > blob.len() {
            break;
        }
        if blob[marker + 4..marker + 6] == [0, 0] {
            let char_len = read_u32(blob, marker + 6)? as usize;
            if let Some(parsed) = decode_text_box_marker(blob, marker, char_len) {
                let score = text_score(&parsed.1);
                if score > best_score {
                    best_score = score;
                    best = Some(parsed);
                }
            }
        }
        off = marker + 1;
    }
    best
}

fn decode_text_box_marker(
    blob: &[u8],
    marker: usize,
    char_len: usize,
) -> Option<(usize, String, usize)> {
    let text_off = marker + TEXT_BOX_TEXT_MARKER_LEN;
    let end = text_off + char_len * 2;
    if char_len == 0 || char_len >= 10000 || end > blob.len() {
        return None;
    }
    let units: Vec<u16> = blob[text_off..end]
        .chunks_exact(2)
        .map(|c| u16::from_le_bytes([c[0], c[1]]))
        .collect();
    let raw_text = String::from_utf16(&units).ok()?;
    let text = raw_text.trim_end_matches(['\0', '\n']).to_string();
    if text.trim().is_empty() || text_score(&text).0 == 0 {
        return None;
    }
    Some((text_off, text, char_len))
}

/// All rich-text style families decoded from one TLV region.
pub(crate) struct RichTextStyles {
    pub(crate) runs: Vec<RichTextRun>,
    pub(crate) colors: Vec<ColorRun>,
    pub(crate) highlights: Vec<ColorRun>,
    pub(crate) font_sizes: Vec<FontSizeRun>,
}

/// Decode every style-run family from `data[scan_start..]`. Run indexes are
/// validated against `raw_len` (the stored character count, which may include
/// a stripped trailing newline) and then clamped to `text_len` — mirroring
/// pysdocx `_text_box_rich_text`'s scan + `rebase`. note.note's typed text
/// uses the same TLV families, so this is shared.
pub(crate) fn scan_rich_text_styles(
    data: &[u8],
    scan_start: usize,
    raw_len: usize,
    text_len: usize,
) -> RichTextStyles {
    // pysdocx `rebase`: clamp a raw run to the stripped text, dropping it when
    // nothing remains.
    let rebase = move |start: usize, end: usize| -> Option<(usize, usize)> {
        let end = end.min(text_len);
        (start < end).then_some((start, end))
    };
    let style_flag = |bold, italic, underline| RichTextRun {
        start: 0,
        end: 0,
        bold,
        italic,
        underline,
        strikethrough: false,
    };
    let mut runs = Vec::new();
    for (tag, proto) in [
        (BOLD_TAG, style_flag(true, false, false)),
        (ITALIC_TAG, style_flag(false, true, false)),
        (UNDERLINE_TAG, style_flag(false, false, true)),
    ] {
        for (start, end, _value, enabled) in style_runs(data, tag, raw_len, scan_start) {
            if enabled != 0
                && let Some((start, end)) = rebase(start, end) {
                    runs.push(RichTextRun {
                        start,
                        end,
                        ..proto.clone()
                    });
                }
        }
    }

    // Strikethrough runs chain: an enabled run counts only when its `end` is
    // the `start` of another record (pysdocx `_text_box_rich_text`).
    let strike_runs = marker_runs(data, &STRIKETHROUGH_MARKER, raw_len, scan_start);
    let strike_starts: std::collections::HashSet<usize> = strike_runs
        .iter()
        .filter(|&&(_s, _e, _v, en)| en <= 1)
        .map(|&(s, _e, _v, _en)| s)
        .collect();
    for (start, end, _value, enabled) in strike_runs {
        if enabled == 1 && strike_starts.contains(&end)
            && let Some((start, end)) = rebase(start, end) {
                runs.push(RichTextRun {
                    start,
                    end,
                    bold: false,
                    italic: false,
                    underline: false,
                    strikethrough: true,
                });
            }
    }

    let argb_runs = |tag: u16| -> Vec<ColorRun> {
        style_runs(data, tag, raw_len, scan_start)
            .into_iter()
            .filter(|&(_s, _e, _v, argb)| argb >> 24 == 0xFF)
            .filter_map(|(start, end, _value, argb)| {
                let (start, end) = rebase(start, end)?;
                Some(ColorRun {
                    start,
                    end,
                    color: Color {
                        r: (argb >> 16) as u8,
                        g: (argb >> 8) as u8,
                        b: argb as u8,
                    },
                })
            })
            .collect()
    };
    let colors = argb_runs(COLOR_TAG);
    let highlights = argb_runs(HIGHLIGHT_TAG);

    let font_sizes = style_runs(data, FONT_TAG, raw_len, scan_start)
        .into_iter()
        .filter_map(|(start, end, _value, enabled)| {
            let size = f32::from_le_bytes(enabled.to_le_bytes());
            if !size.is_finite() || !(4.0..=200.0).contains(&size) {
                return None;
            }
            let (start, end) = rebase(start, end)?;
            Some(FontSizeRun { start, end, size })
        })
        .collect();

    RichTextStyles {
        runs,
        colors,
        highlights,
        font_sizes,
    }
}

fn style_runs(
    data: &[u8],
    tag: u16,
    text_len: usize,
    scan_start: usize,
) -> Vec<(usize, usize, u32, u32)> {
    let marker = [0x18, 0x00, tag as u8, (tag >> 8) as u8];
    marker_runs(data, &marker, text_len, scan_start)
}

/// All local `(start, end, value, enabled)` TLV runs for one marker
/// (pysdocx `_text_box_marker_runs`).
fn marker_runs(
    data: &[u8],
    marker: &[u8; 4],
    text_len: usize,
    scan_start: usize,
) -> Vec<(usize, usize, u32, u32)> {
    let mut runs = Vec::new();
    let mut off = scan_start;
    while off + RUN_MARKER_LEN <= data.len() {
        let Some(hit) = find_sub(&data[off..], marker).map(|i| off + i) else {
            break;
        };
        if hit + RUN_MARKER_LEN <= data.len() && data[hit + 4..hit + 6] == [0, 0] {
            let start = read_u32(data, hit + RUN_START_OFF).unwrap() as usize;
            let end = read_u32(data, hit + RUN_END_OFF).unwrap() as usize;
            let value = read_u32(data, hit + RUN_START_OFF + 8).unwrap();
            let enabled = read_u32(data, hit + RUN_ENABLED_OFF).unwrap();
            if start < end && end <= text_len {
                runs.push((start, end, value, enabled));
            }
        }
        off = hit + 1;
    }
    runs
}

// ---------------------------------------------------------------------------
// Sticky-note (file-attachment) placements — pysdocx `scan_sticky_notes`.
//
// These live in whole-page attachment property bags anchored by the ascii
// marker `co_attach_file`, OUTSIDE the declared layer/object tree (the layer's
// object_count excludes them), so they are found by marker scan, not tree walk.
// Bag layout: a sequence of `<u32 len><ascii>` keys; the `co_attach_file` key
// is followed by `u32 media_index + u32 type_tag` instead of a string value,
// every other key by a `<u32 len><ascii>` value. A bag with any `skn_*` key is
// a sticky note; `skn_collapse_rect` holds its "x0,y0,x1,y1" placement.
// ---------------------------------------------------------------------------

const STICKY_NOTE_MARKER: &[u8] = b"co_attach_file";
const STICKY_NOTE_RECT_KEY: &str = "skn_collapse_rect";
const STICKY_NOTE_BG_KEY: &str = "skn_bg_color";
const ATTACHMENT_PROPERTY_BAG_MAX_SCAN: usize = 512;
const ATTACHMENT_PROPERTY_BAG_MAX_KEYS: usize = 16;

fn scan_sticky_notes(data: &[u8], width: u32, height: u32, elements: &mut Vec<PageElement>) {
    let mut off = 0usize;
    while let Some(rel) = find_sub(&data[off..], STICKY_NOTE_MARKER) {
        let marker_off = off + rel;
        off = marker_off + 1;
        if let Some(el) = parse_attachment_property_bag(data, marker_off, width, height) {
            elements.push(el);
        }
    }
}

/// `<u32 length><ascii bytes>` at `offset` (pysdocx `_read_len_prefixed_ascii`).
fn read_len_prefixed_ascii(data: &[u8], offset: usize) -> Option<(&str, usize)> {
    let length = read_u32(data, offset)? as usize;
    if length == 0 || length >= 1000 {
        return None;
    }
    let start = offset + 4;
    let end = start + length;
    let bytes = data.get(start..end)?;
    if !bytes.is_ascii() {
        return None;
    }
    Some((std::str::from_utf8(bytes).ok()?, end))
}

fn is_bag_key(key: &str) -> bool {
    (2..=64).contains(&key.len())
        && key
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_')
}

/// "x0,y0,x1,y1" → a page-plausible bbox (pysdocx `_parse_attachment_bbox`).
fn parse_attachment_bbox(text: &str, width: u32, height: u32) -> Option<BoundingBox> {
    let mut vals = [0f64; 4];
    let mut parts = text.split(',');
    for v in &mut vals {
        *v = parts.next()?.parse().ok()?;
    }
    if parts.next().is_some() || vals.iter().any(|v| !v.is_finite()) {
        return None;
    }
    let bbox = BoundingBox {
        x_min: vals[0].min(vals[2]),
        y_min: vals[1].min(vals[3]),
        x_max: vals[0].max(vals[2]),
        y_max: vals[1].max(vals[3]),
    };
    let (w, h) = (width as f64, height as f64);
    (-5.0 <= bbox.x_min
        && bbox.x_min < bbox.x_max
        && bbox.x_max <= w + 5.0
        && -5.0 <= bbox.y_min
        && bbox.y_min < bbox.y_max
        && bbox.y_max <= h + 5.0)
        .then_some(bbox)
}

/// Decode one attachment property bag anchored at a `co_attach_file` marker
/// (pysdocx `_scan_attachment_property_bag` + the sticky filter of
/// `scan_sticky_notes`). Returns a StickyNote element or None.
fn parse_attachment_property_bag(
    data: &[u8],
    marker_off: usize,
    width: u32,
    height: u32,
) -> Option<PageElement> {
    let bag_off = marker_off.checked_sub(4)?;
    if read_u32(data, bag_off)? as usize != STICKY_NOTE_MARKER.len() {
        return None;
    }

    let end_limit = data.len().min(bag_off + ATTACHMENT_PROPERTY_BAG_MAX_SCAN);
    let mut pos = bag_off;
    let mut media_index = None;
    let mut bbox = None;
    let mut bg_color = None;
    let mut is_sticky = false;

    for _ in 0..ATTACHMENT_PROPERTY_BAG_MAX_KEYS {
        let Some((key, next)) = read_len_prefixed_ascii(data, pos) else {
            break;
        };
        if !is_bag_key(key) {
            break;
        }
        is_sticky |= key.starts_with("skn_");
        pos = next;

        if key == "co_attach_file" {
            if pos + 8 > end_limit {
                return None;
            }
            media_index = Some(read_u32(data, pos)? as usize);
            pos += 8; // media_index + type_tag
        } else {
            let Some((value, next)) = read_len_prefixed_ascii(data, pos) else {
                break;
            };
            pos = next;
            if key == STICKY_NOTE_RECT_KEY {
                bbox = parse_attachment_bbox(value, width, height);
            } else if key == STICKY_NOTE_BG_KEY {
                // Android ARGB color int as decimal string (e.g. "-6482" =
                // 0xFFFFE6AE, the default sticky yellow).
                if let Ok(argb) = value.parse::<i64>() {
                    let argb = argb as u32;
                    if argb >> 24 == 0xFF {
                        bg_color = Some(Color {
                            r: (argb >> 16) as u8,
                            g: (argb >> 8) as u8,
                            b: argb as u8,
                        });
                    }
                }
            }
        }

        if pos + 4 > end_limit {
            break;
        }
    }

    Some(PageElement::StickyNote {
        bbox: bbox.filter(|_| is_sticky)?,
        media_index: media_index?,
        bg_color,
    })
}

#[cfg(test)]
mod tests {
    use super::{bbox_of, looks_like_flat_synthetic_line, parse_page, within_page_bounds};
    use crate::types::{BoundingBox, Color, PageTemplate, PageTemplateSource, Point, Stroke};

    fn stroke_with(bbox: BoundingBox, points: Vec<Point>) -> Stroke {
        Stroke {
            bbox,
            points,
            pressures: Vec::new(),
            timestamps: Vec::new(),
            tilt_x: Vec::new(),
            tilt_y: Vec::new(),
            color: None,
            pen_width: 57.37,
            tool_id: Some(0),
            tapered: false,
        }
    }

    #[test]
    fn detects_flat_synthetic_line() {
        // samples/Allsamsungnotes_260630_113259.sdocx, page e9561382, idx127:
        // bbox 343.7px wide, height exactly 1.0, but the decoded points only
        // span 7.7px — the bbox is the real line, not the decoded points.
        let bbox = BoundingBox {
            x_min: 137.7,
            y_min: 180.7,
            x_max: 481.4,
            y_max: 181.7,
        };
        let points = vec![Point { x: 137.7, y: 180.7 }, Point { x: 145.4, y: 180.7 }];
        let stroke = stroke_with(bbox, points);
        assert!(looks_like_flat_synthetic_line(&stroke, 48));
        // Wrong extra_len -> not treated as this variant.
        assert!(!looks_like_flat_synthetic_line(&stroke, 36));
    }

    #[test]
    fn rejects_normal_strokes_as_flat_synthetic_line() {
        // A real short horizontal stroke whose decoded points DO span the
        // bbox must not be reinterpreted.
        let bbox = BoundingBox {
            x_min: 0.0,
            y_min: 0.0,
            x_max: 10.0,
            y_max: 1.0,
        };
        let points = vec![Point { x: 0.0, y: 0.0 }, Point { x: 10.0, y: 1.0 }];
        let stroke = stroke_with(bbox, points);
        assert!(!looks_like_flat_synthetic_line(&stroke, 48));

        // Tall bbox (not flat) -> never this variant even with extra_len 48.
        let tall_bbox = BoundingBox {
            x_min: 0.0,
            y_min: 0.0,
            x_max: 10.0,
            y_max: 50.0,
        };
        let short_points = vec![Point { x: 0.0, y: 0.0 }, Point { x: 1.0, y: 1.0 }];
        let tall_stroke = stroke_with(tall_bbox, short_points);
        assert!(!looks_like_flat_synthetic_line(&tall_stroke, 48));
    }

    #[test]
    fn within_page_bounds_accepts_onpage_rejects_garbage() {
        let onpage = [Point { x: 100.0, y: 200.0 }, Point { x: 150.0, y: 40.0 }];
        assert!(within_page_bounds(&onpage, 1600, 2262));

        // A garbage start point from a misread layout lands far off-page.
        let garbage = [Point { x: 1e266, y: 5.0 }, Point { x: 10.0, y: 20.0 }];
        assert!(!within_page_bounds(&garbage, 1600, 2262));

        // NaN and single-point paths are rejected.
        assert!(!within_page_bounds(
            &[
                Point {
                    x: f64::NAN,
                    y: 1.0
                },
                Point { x: 2.0, y: 3.0 }
            ],
            1600,
            2262
        ));
        assert!(!within_page_bounds(&[Point { x: 1.0, y: 1.0 }], 1600, 2262));
    }

    #[test]
    fn bbox_of_computes_min_max() {
        let b = bbox_of(&[
            Point { x: 10.0, y: 50.0 },
            Point { x: 30.0, y: 5.0 },
            Point { x: 20.0, y: 80.0 },
        ]);
        assert_eq!(
            (b.x_min, b.y_min, b.x_max, b.y_max),
            (10.0, 5.0, 30.0, 80.0)
        );
    }

    #[test]
    fn kept_strokes_lie_within_their_bbox() {
        // Every stroke we keep must be decoded with the layout that places its
        // points inside the stroke's own bounding box. Before the bbox-aware
        // layout selection, ~3-4% of strokes here decoded to garbage
        // coordinates (off-canvas or collapsed on the origin).
        let doc = crate::parse("../../samples/handwritten.sdocx").expect("parse sample");
        let mut checked = 0;
        for page in &doc.pages {
            for stroke in &page.strokes {
                let tol = 8.0;
                let inside = stroke
                    .points
                    .iter()
                    .filter(|p| {
                        p.x >= stroke.bbox.x_min - tol
                            && p.x <= stroke.bbox.x_max + tol
                            && p.y >= stroke.bbox.y_min - tol
                            && p.y <= stroke.bbox.y_max + tol
                    })
                    .count();
                assert!(
                    inside * 5 >= stroke.points.len() * 4,
                    "stroke points fall outside their bbox: {}/{} inside",
                    inside,
                    stroke.points.len(),
                );
                checked += 1;
            }
        }
        assert!(checked > 0, "sample produced no strokes to check");
    }

    #[test]
    fn parses_page_header_background_color() {
        // Paper color record signature (RE 2026-07-09): [u32 kind][BGRA alpha=FF]
        // [u32 display_width], located within [0x7c, base). `base` must reach past
        // the record.
        let mut data = vec![0; 0xB0];
        data[0x00..0x04].copy_from_slice(&0xB0_u32.to_le_bytes()); // base
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1527_u32.to_le_bytes());
        data[0xA0..0xA4].copy_from_slice(&2_u32.to_le_bytes()); // kind
        data[0xA4..0xA8].copy_from_slice(&[0xDD, 0xDD, 0xF5, 0xFF]); // BGRA
        data[0xA8..0xAC].copy_from_slice(&1080_u32.to_le_bytes()); // display_width

        let page = parse_page(&data).unwrap();

        assert_eq!(
            page.background_color,
            Some(Color {
                r: 0xF5,
                g: 0xDD,
                b: 0xDD,
            })
        );
    }

    /// RE parity on real one-variable samples: the paper color is decoded from the
    /// `.page` header and equals the paper the note was created with (proven by the
    /// pink `Rosina` sample). Skips cleanly when the samples are absent.
    #[test]
    fn decodes_paper_color_from_test_background_samples() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../samples/test-background");
        let cases = [
            ("Default-Liscio_260709_125314.sdocx", (252, 252, 252)),
            ("Bianca-Liscio_260709_125449.sdocx", (230, 230, 230)),
            ("Rosina-Liscio_260709_125531.sdocx", (245, 221, 221)),
            ("Bianca-quadretti_260709_125637.sdocx", (230, 230, 230)),
            // Explicit DARK paper is stored the same way, as a dark RGB.
            ("Nera-Liscio_260709_140421.sdocx", (1, 1, 1)),
        ];
        let mut checked = 0;
        for (name, (r, g, b)) in cases {
            let path = dir.join(name);
            if !path.exists() {
                eprintln!("skipping: {name} not present");
                continue;
            }
            let mut reader = crate::open(&path).expect("open sample");
            // Every page of a note carries the same single paper color.
            for i in 0..reader.page_count() {
                let bytes = reader.page_bytes(i).expect("page bytes");
                let page = parse_page(&bytes).expect("parse page");
                assert_eq!(
                    page.background_color,
                    Some(Color { r, g, b }),
                    "{name} page {i}"
                );
                checked += 1;
            }
        }
        if checked == 0 {
            eprintln!("no test-background samples present");
        }
    }

    #[test]
    fn parses_page_template_id() {
        let mut data = vec![0; 0x200];
        data[0x00..0x04].copy_from_slice(&0xE7_u32.to_le_bytes());
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1527_u32.to_le_bytes());
        data[0xA0..0xA4].copy_from_slice(&2_u32.to_le_bytes()); // paper-color kind
        data[0xA4..0xA8].copy_from_slice(&[0xDD, 0xDA, 0xCB, 0xFF]);
        data[0xA8..0xAC].copy_from_slice(&1080_u32.to_le_bytes()); // display_width
        data[0xAC..0xB0].copy_from_slice(&1_u32.to_le_bytes()); // built-in template id
        data[0xB0..0xB4].copy_from_slice(&1_u32.to_le_bytes()); // reserved u32 (== 1 on built-in)

        let page = parse_page(&data).unwrap();

        assert_eq!(
            page.template,
            Some(PageTemplate {
                id: 1,
                source: PageTemplateSource::BuiltIn,
            })
        );
    }

    #[test]
    fn parses_short_page_template_id() {
        let mut data = vec![0; 0x200];
        data[0x00..0x04].copy_from_slice(&0x90_u32.to_le_bytes());
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1527_u32.to_le_bytes());
        data[0x80..0x84].copy_from_slice(&2_u32.to_le_bytes()); // paper-color kind
        data[0x84..0x88].copy_from_slice(&[0xDD, 0xDA, 0xCB, 0xFF]);
        data[0x88..0x8C].copy_from_slice(&1080_u32.to_le_bytes()); // display_width
        data[0x8C..0x90].copy_from_slice(&10_u32.to_le_bytes());

        let page = parse_page(&data).unwrap();

        assert_eq!(
            page.template,
            Some(PageTemplate {
                id: 10,
                source: PageTemplateSource::BuiltIn,
            })
        );
    }

    #[test]
    fn parses_custom_pdf_page_template() {
        // PDF-backed page (Academic template / imported PDF): the paper record is followed by
        // [u16 flag=1][u16 media_index][u16 reserved=0][u16 page_index]. Detected by the marker
        // regardless of `base`, so it also fixes imported-PDF pages the built-in offsets misread.
        let mut data = vec![0; 0x200];
        data[0x00..0x04].copy_from_slice(&0xA6_u32.to_le_bytes());
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1528_u32.to_le_bytes());
        data[0x7C..0x80].copy_from_slice(&2_u32.to_le_bytes()); // paper-color kind
        data[0x80..0x84].copy_from_slice(&[0xDD, 0xDA, 0xCB, 0xFF]);
        data[0x84..0x88].copy_from_slice(&1080_u32.to_le_bytes()); // display_width
        data[0x88..0x8A].copy_from_slice(&1_u16.to_le_bytes()); // flag
        data[0x8A..0x8C].copy_from_slice(&2_u16.to_le_bytes()); // pdf_media_index
        data[0x8C..0x8E].copy_from_slice(&0_u16.to_le_bytes()); // reserved
        data[0x8E..0x90].copy_from_slice(&3_u16.to_le_bytes()); // pdf_page_index (0-based)

        let page = parse_page(&data).unwrap();

        assert_eq!(
            page.template,
            Some(PageTemplate {
                id: 3,
                source: PageTemplateSource::CustomPdf {
                    media_index: 2,
                    page_index: 3,
                },
            })
        );
    }

    #[test]
    fn parses_older_page_template_id_offset_as_absent_when_zero() {
        let mut data = vec![0; 0x200];
        data[0x00..0x04].copy_from_slice(&0xE3_u32.to_le_bytes());
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1527_u32.to_le_bytes());
        data[0xA0..0xA4].copy_from_slice(&2_u32.to_le_bytes()); // paper-color kind
        data[0xA4..0xA8].copy_from_slice(&[0xFC, 0xFC, 0xFC, 0xFF]);
        data[0xA8..0xAC].copy_from_slice(&1080_u32.to_le_bytes()); // display_width
        data[0xAC..0xB0].copy_from_slice(&1_u32.to_le_bytes()); // newer-offset id (ignored here)
        data[0xB0..0xB4].copy_from_slice(&1_u32.to_le_bytes()); // reserved u32 (== 1, not a PDF page)
        data[0xB4..0xB8].copy_from_slice(&0_u32.to_le_bytes()); // older-offset id == 0 -> absent

        let page = parse_page(&data).unwrap();

        assert_eq!(page.template, None);
    }
}
