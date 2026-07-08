use crate::decode::{decode_coordinates, decode_trailing};
use crate::error::{Error, Result};
use crate::types::{
    BoundingBox, Color, Page, PageElement, PageTemplate, PageTemplateSource, Point, RichTextBox,
    RichTextRun, Stroke,
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

/// Validate the common object header at the start of a blob and return its
/// `total_size` field (mirrors pysdocx `_parse_object_header`; only total_size
/// is needed for stroke decoding — it yields `extra_len`).
fn object_header_total_size(blob: &[u8]) -> Option<u32> {
    if blob.len() < OBJECT_BASE_HEADER_LEN {
        return None;
    }
    let total_size = read_u32(blob, 0)?;
    let mut pos = 4 + 2 + 4; // total_size + data_type + var_data_offset
    let flag_len = *blob.get(pos)? as usize;
    pos += 1 + flag_len;
    let field_len = *blob.get(pos)? as usize;
    pos += 1 + field_len;
    pos += 4; // format_version
    let uuid_byte_len = read_i16(blob, pos)?;
    if uuid_byte_len < 0 {
        return None;
    }
    pos += 2 + uuid_byte_len as usize;
    pos += 8 + 32 + 4 + 1; // modified_time + bbox + timestamp + resizable
    (pos <= blob.len()).then_some(total_size)
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

    let background_color = page_background_color(data, base);
    let template = background_color.and_then(|_| page_template(data, base));

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
        let Some(total_size) = object_header_total_size(blob) else {
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

    let elements = parse_page_elements(data, &objects, width, height);

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

fn page_background_color(data: &[u8], base: usize) -> Option<crate::types::Color> {
    let offset = match base {
        0x90 => 0x84,
        0xA6 => 0x80,
        _ => 0xA4,
    };
    if data.len() >= offset + 4 && data[offset + 3] == 0xFF {
        Some(crate::types::Color {
            r: data[offset + 2],
            g: data[offset + 1],
            b: data[offset],
        })
    } else {
        None
    }
}

fn page_template(data: &[u8], base: usize) -> Option<PageTemplate> {
    match base {
        // Short built-in template page records store the template id in the compact header.
        0x90 => {
            let id = read_u32(data, 0x8C)?;
            is_builtin_template_id(id).then_some(PageTemplate {
                id,
                source: PageTemplateSource::BuiltIn,
            })
        }
        // Custom downloaded templates are backed by media PDFs. The compact header stores the
        // zero-based PDF page index in the high 16 bits of this field.
        0xA6 => {
            let page_index = read_u32(data, 0x8C)? >> 16;
            Some(PageTemplate {
                id: page_index,
                source: PageTemplateSource::CustomPdf { page_index },
            })
        }
        _ => {
            let id = if base >= 0xE7 {
                read_u32(data, 0xAC)?
            } else {
                read_u32(data, 0xB4)?
            };
            is_builtin_template_id(id).then_some(PageTemplate {
                id,
                source: PageTemplateSource::BuiltIn,
            })
        }
    }
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
        // Anchor on the object's ascii UUID (inside the common header), keeping
        // the uuid-relative record logic identical to the old whole-buffer scan
        // — just scoped to this object's blob. Shape objects don't need this
        // anchor (their bbox comes from the shape marker itself), so a missing
        // uuid/bbox only skips the text/image path, not the whole object.
        if let Some(uuid_off) = find_uuid_in(data, obj.blob_off, obj.blob_off + 96) {
            if let Some(bbox) = find_object_bbox(data, uuid_off, width, height) {
                let record_end = obj.blob_end.min(uuid_off + MAX_OBJECT_RECORD_LEN);
                let record = &data[uuid_off..record_end];

                if let Some(text_box) = parse_text_box_record(record, bbox) {
                    elements.push(PageElement::TextBox(text_box));
                    continue;
                }
                if let Some(media_index) = image_media_index(record) {
                    elements.push(PageElement::Image { bbox, media_index });
                    continue;
                }
            }
        }

        // pysdocx `_classify_page_object` precedence: an image placement marker
        // claims the object even when its media index fails to decode — never
        // shape-scan those blobs.
        let blob = &data[obj.blob_off..obj.blob_end];
        if find_sub(blob, IMAGE_MARKER).is_some() {
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

fn parse_text_box_record(record: &[u8], bbox: BoundingBox) -> Option<RichTextBox> {
    let (text, text_end) = first_utf16_text(record)?;
    let styles = &record[text_end..];
    let color = tlv_color(styles, 0x01);
    let highlight_color = tlv_color(styles, 0x11);
    let underline = tlv_u32(styles, 0x07).is_some_and(|value| value != 0)
        || tlv_u32(styles, 0x06).is_some_and(|value| value != 0);
    let font_size = tlv_f32(styles, 0x03);
    let rotation_degrees = infer_rotation_degrees(record, bbox);
    let runs = parse_rich_text_runs(styles, text.chars().count());

    Some(RichTextBox {
        bbox,
        rotation_degrees,
        text,
        color,
        highlight_color,
        underline,
        font_size,
        runs,
    })
}

fn first_utf16_text(data: &[u8]) -> Option<(String, usize)> {
    let mut offset = 0;
    while offset + 6 <= data.len() {
        // Decode the maximal printable run [offset, end) once. The printable set
        // is BMP-only (0x0A + 0x20..=0xD7FF, no surrogates), so one u16 == one
        // char and code-unit indexes are char indexes.
        let mut units: Vec<u16> = Vec::new();
        let mut end = offset;
        while end + 2 <= data.len() {
            let unit = u16::from_le_bytes([data[end], data[end + 1]]);
            if unit != 0x0A && !(0x20..=0xD7FF).contains(&unit) {
                break;
            }
            units.push(unit);
            end += 2;
        }
        // Find the earliest start within the run whose text is note-like (>=3
        // non-whitespace chars, >=75% ASCII alnum/punct). Suffix counts make this
        // O(run) — the old code re-decoded + re-allocated a String for every start,
        // which is O(run^2) and cost seconds on text-heavy pages.
        let m = units.len();
        if m >= 3 {
            let mut nonws = 0i64;
            let mut common = 0i64;
            let mut first_ok: Option<usize> = None;
            for k in (0..m).rev() {
                if let Some(c) = char::from_u32(units[k] as u32) {
                    if !c.is_whitespace() {
                        nonws += 1;
                        if c.is_ascii_alphanumeric() || c.is_ascii_punctuation() {
                            common += 1;
                        }
                    }
                }
                if nonws >= 3 && common * 4 >= nonws * 3 {
                    first_ok = Some(k);
                }
            }
            if let Some(k) = first_ok {
                let text = String::from_utf16(&units[k..]).ok()?;
                return Some((text, end));
            }
        }
        offset = if end > offset { end } else { offset + 2 };
    }
    None
}

fn tlv_color(data: &[u8], tag: u16) -> Option<Color> {
    let marker = [0x18, 0x00, tag as u8, (tag >> 8) as u8];
    for offset in 0..data.len().saturating_sub(22) {
        if data[offset..offset + 4] == marker && data[offset + 21] == 0xFF {
            return Some(Color {
                r: data[offset + 20],
                g: data[offset + 19],
                b: data[offset + 18],
            });
        }
    }
    None
}

fn tlv_u32(data: &[u8], tag: u16) -> Option<u32> {
    let marker = [0x18, 0x00, tag as u8, (tag >> 8) as u8];
    for offset in 0..data.len().saturating_sub(22) {
        if data[offset..offset + 4] == marker {
            return read_u32(data, offset + 18);
        }
    }
    None
}

fn tlv_f32(data: &[u8], tag: u16) -> Option<f32> {
    let marker = [0x18, 0x00, tag as u8, (tag >> 8) as u8];
    for offset in 0..data.len().saturating_sub(24) {
        if data[offset..offset + 4] == marker {
            for value_offset in [18, 20, 24] {
                let value = f32::from_le_bytes(
                    data[offset + value_offset..offset + value_offset + 4]
                        .try_into()
                        .ok()?,
                );
                if value.is_finite() && (4.0..=96.0).contains(&value) {
                    return Some(value);
                }
            }
        }
    }
    None
}

fn parse_rich_text_runs(data: &[u8], text_len: usize) -> Vec<RichTextRun> {
    let mut runs = Vec::new();
    collect_style_runs(data, text_len, 0x05, true, false, &mut runs);
    collect_style_runs(data, text_len, 0x06, false, true, &mut runs);
    runs
}

fn collect_style_runs(
    data: &[u8],
    text_len: usize,
    tag: u16,
    bold: bool,
    italic: bool,
    runs: &mut Vec<RichTextRun>,
) {
    let marker = [0x18, 0x00, tag as u8, (tag >> 8) as u8];
    for offset in 0..data.len().saturating_sub(18) {
        if data[offset..offset + 4] != marker {
            continue;
        }
        let Some(start) = read_u32(data, offset + 6).map(|value| value as usize) else {
            continue;
        };
        let Some(end) = read_u32(data, offset + 10).map(|value| value as usize) else {
            continue;
        };
        let enabled = read_u32(data, offset + 18).is_some_and(|value| value != 0);
        if enabled && start < end && end <= text_len {
            runs.push(RichTextRun {
                start,
                end,
                bold,
                italic,
            });
        }
    }
}

fn infer_rotation_degrees(record: &[u8], bbox: BoundingBox) -> Option<f64> {
    let mut points = Vec::new();
    for offset in 0..record.len().saturating_sub(16) {
        let x = read_f64(record, offset)?;
        let y = read_f64(record, offset + 8)?;
        if x.is_finite()
            && y.is_finite()
            && x >= bbox.x_min - bbox.x_max
            && x <= bbox.x_max + bbox.x_max
            && y >= bbox.y_min - bbox.y_max
            && y <= bbox.y_max + bbox.y_max
        {
            points.push((x, y));
        }
    }
    for pair in points.windows(2) {
        let dx = pair[1].0 - pair[0].0;
        let dy = pair[1].1 - pair[0].1;
        let distance = dx.hypot(dy);
        if distance > 40.0 {
            let degrees = dy.atan2(dx).to_degrees();
            if degrees.abs() > 5.0 && degrees.abs() < 85.0 {
                return Some(degrees);
            }
        }
    }
    None
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
        let mut data = vec![0; 0xA8];
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1527_u32.to_le_bytes());
        data[0xA4..0xA8].copy_from_slice(&[0xDD, 0xDD, 0xF5, 0xFF]);

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

    #[test]
    fn parses_page_template_id() {
        let mut data = vec![0; 0x200];
        data[0x00..0x04].copy_from_slice(&0xE7_u32.to_le_bytes());
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1527_u32.to_le_bytes());
        data[0xA4..0xA8].copy_from_slice(&[0xDD, 0xDA, 0xCB, 0xFF]);
        data[0xAC..0xB0].copy_from_slice(&1_u32.to_le_bytes());

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
        data[0x84..0x88].copy_from_slice(&[0xDD, 0xDA, 0xCB, 0xFF]);
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
        let mut data = vec![0; 0x200];
        data[0x00..0x04].copy_from_slice(&0xA6_u32.to_le_bytes());
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1528_u32.to_le_bytes());
        data[0x80..0x84].copy_from_slice(&[0xDD, 0xDA, 0xCB, 0xFF]);
        data[0x8C..0x90].copy_from_slice(&(3_u32 << 16).to_le_bytes());

        let page = parse_page(&data).unwrap();

        assert_eq!(
            page.template,
            Some(PageTemplate {
                id: 3,
                source: PageTemplateSource::CustomPdf { page_index: 3 },
            })
        );
    }

    #[test]
    fn parses_older_page_template_id_offset_as_absent_when_zero() {
        let mut data = vec![0; 0x200];
        data[0x00..0x04].copy_from_slice(&0xE3_u32.to_le_bytes());
        data[0x16..0x1A].copy_from_slice(&1080_u32.to_le_bytes());
        data[0x1A..0x1E].copy_from_slice(&1527_u32.to_le_bytes());
        data[0xA4..0xA8].copy_from_slice(&[0xFC, 0xFC, 0xFC, 0xFF]);
        data[0xAC..0xB0].copy_from_slice(&1_u32.to_le_bytes());
        data[0xB4..0xB8].copy_from_slice(&0_u32.to_le_bytes());

        let page = parse_page(&data).unwrap();

        assert_eq!(page.template, None);
    }
}
