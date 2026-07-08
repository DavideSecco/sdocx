//! Inserted-shape decoding (shape tool + line/arrow tool).
//!
//! Byte-for-byte port of pysdocx's shape parsing (`pysdocx/page.py`:
//! `_parse_shape_marker`, `decode_outline`, `flatten_outline`, `_read_vertex_list`,
//! `_shape_color_before_marker`, `_nearest_shape_color`, `_shape_width`,
//! `_parse_arrow_object`) — keep the two in lockstep when either side changes.
//!
//! Every marker-based shape carries its true outline as a serialized vector path in
//! the object trailer, right after `01 04 04 01 00 00 00 <u32 type_code>
//! <bbox 4×f64> <12-byte header>` (i.e. at marker+55). The path is a sequence of
//! segments `<u8 tag><tag_pts × (f64 x, f64 y)>` with a ONE-BYTE tag: 1=MoveTo
//! (1 pt), 2=LineTo (1 pt), 4=CubicBezierTo (3 pts). Only ellipse (1) and
//! rounded-rect (64) have a degenerate path (a lone MoveTo); they keep the
//! vertex-list `<u32 count><count × (f64 x, f64 y)>` that precedes the marker.
//!
//! The line/arrow tool is a distinct, markerless object: a 2-point shaft right
//! after `01 00 01 0c 02 00 00 00`, plus two arrowhead flag bytes a fixed distance
//! past the shaft points.

use crate::types::{BoundingBox, Color, OutlineOp, Point, Shape, ShapeKind};

/// `01 04 04 01 00 00 00` — precedes `<u32 type_code><bbox 4×f64>` in every
/// marker-based shape.
pub(crate) const SHAPE_TYPE_MARKER: &[u8] = b"\x01\x04\x04\x01\x00\x00\x00";
/// The pen line width is the f32 right after this marker in the shape trailer.
const SHAPE_WIDTH_MARKER: &[u8] = b"\x0c\x00\x00\x00";
const SHAPE_TRAILER_WINDOW: usize = 220;
/// marker(7) + type_code(4) + bbox(32) + header(12).
const SHAPE_OUTLINE_OFFSET: usize = 55;
/// ⚠ Heuristic window: the BGRA stroke color sits just before the marker (after the
/// vertex list); scanned backward, closest match wins (see pysdocx page.py).
const SHAPE_COLOR_BACK_WINDOW: usize = 160;
/// ⚠ Heuristic window for the forward color scan used by line/arrow objects.
const SHAPE_COLOR_WINDOW: usize = 80;
const SHAPE_MIN_VERTICES: u32 = 2;
const SHAPE_MAX_VERTICES: u32 = 64;
/// Flattening resolution for cubic Bezier outline segments (pysdocx BEZIER_PER_SEG).
const BEZIER_PER_SEG: usize = 16;
const MAX_OUTLINE_POINTS: usize = 4000;

/// ⚠ Heuristic: a smooth-freeform (code 90) path is closed when its endpoints meet
/// within this fraction of the bbox diagonal. A genuinely closed path closes
/// EXACTLY (ratio 0.0); every open curve measured >= 0.356 (incl. the spiral, the
/// tightest case) — see pysdocx page.py SHAPE_OPEN_RATIO.
const SHAPE_OPEN_RATIO: f64 = 0.05;

/// Shaft marker of the markerless line/arrow object: 2 f64 points follow.
pub(crate) const ARROW_SHAFT_MARKER: &[u8] = b"\x01\x00\x01\x0c\x02\x00\x00\x00";
/// Arrowhead flag bytes, relative to the first shaft coordinate: 1 = draw a head at
/// points[0] / points[1]. A plain line has neither, a single arrow has head_end, a
/// double arrow has both.
const ARROW_HEAD_START_OFFSET: usize = 76;
const ARROW_HEAD_END_OFFSET: usize = 78;

/// pysdocx SHAPE_TYPES: raw type_code → family. Unmapped codes render as `Polygon`
/// from their decoded outline.
fn shape_kind(type_code: u32) -> ShapeKind {
    match type_code {
        1 => ShapeKind::Ellipse,
        2 => ShapeKind::Triangle,
        4 => ShapeKind::Rectangle,
        6 => ShapeKind::Hexagon,
        8 => ShapeKind::Rhombus,
        9 => ShapeKind::Trapezoid,
        11 => ShapeKind::Pentagon,
        13 => ShapeKind::Star,
        17 => ShapeKind::Cross,
        23 => ShapeKind::Heart,
        64 => ShapeKind::RoundedRect,
        88 | 89 => ShapeKind::Freeform, // 88 = angular open, 89 = angular closed
        90 => ShapeKind::FreeformSmooth,
        _ => ShapeKind::Polygon,
    }
}

/// Types whose stored outline path is degenerate (lone MoveTo) — use the vertex list.
fn has_degenerate_outline(type_code: u32) -> bool {
    matches!(type_code, 1 | 64)
}

fn read_u32(data: &[u8], off: usize) -> Option<u32> {
    Some(u32::from_le_bytes(data.get(off..off + 4)?.try_into().ok()?))
}

fn read_f32(data: &[u8], off: usize) -> Option<f32> {
    Some(f32::from_le_bytes(data.get(off..off + 4)?.try_into().ok()?))
}

fn read_f64(data: &[u8], off: usize) -> Option<f64> {
    Some(f64::from_le_bytes(data.get(off..off + 8)?.try_into().ok()?))
}

fn find_sub(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

fn on_page(x: f64, y: f64, width: u32, height: u32) -> bool {
    x.is_finite()
        && y.is_finite()
        && (-50.0..=width as f64 + 50.0).contains(&x)
        && (-50.0..=height as f64 + 50.0).contains(&y)
}

/// Decode the serialized vector path at `off` into `(tag, points)` segments.
/// Stops at the first byte that isn't a known tag or a point that falls off-page
/// (the natural end of the path).
fn decode_outline(data: &[u8], off: usize, width: u32, height: u32) -> Vec<(u8, Vec<(f64, f64)>)> {
    let mut segments = Vec::new();
    let mut n_points = 0usize;
    let mut o = off;
    while n_points < MAX_OUTLINE_POINTS && o < data.len() {
        let tag = data[o];
        let npt = match tag {
            1 | 2 => 1, // MoveTo / LineTo
            4 => 3,     // CubicBezierTo
            _ => break,
        };
        if o + 1 + npt * 16 > data.len() {
            break;
        }
        let mut seg = Vec::with_capacity(npt);
        for k in 0..npt {
            let x = read_f64(data, o + 1 + k * 16).unwrap();
            let y = read_f64(data, o + 1 + k * 16 + 8).unwrap();
            if !on_page(x, y, width, height) {
                return segments;
            }
            seg.push((x, y));
        }
        segments.push((tag, seg));
        n_points += npt;
        o += 1 + npt * 16;
    }
    segments
}

/// Sample a cubic Bezier at `per_seg` points (endpoint excluded; the caller adds it).
fn cubic(p0: (f64, f64), p1: (f64, f64), p2: (f64, f64), p3: (f64, f64), out: &mut Vec<(f64, f64)>) {
    for i in 0..BEZIER_PER_SEG {
        let t = i as f64 / BEZIER_PER_SEG as f64;
        let mt = 1.0 - t;
        let (a, b, c, d) = (mt * mt * mt, 3.0 * mt * mt * t, 3.0 * mt * t * t, t * t * t);
        out.push((
            a * p0.0 + b * p1.0 + c * p2.0 + d * p3.0,
            a * p0.1 + b * p1.1 + c * p2.1 + d * p3.1,
        ));
    }
}

/// Flatten decoded segments into a plain point list ready to draw.
fn flatten_outline(segments: &[(u8, Vec<(f64, f64)>)]) -> Vec<(f64, f64)> {
    let mut points: Vec<(f64, f64)> = Vec::new();
    for (tag, seg) in segments {
        if *tag == 4 && !points.is_empty() {
            let anchor = *points.last().unwrap();
            cubic(anchor, seg[0], seg[1], seg[2], &mut points);
            points.push(seg[2]);
        } else {
            // MoveTo / LineTo (or a leading cubic with no anchor yet)
            points.extend_from_slice(seg);
        }
    }
    points
}

/// Read the `<u32 count><count × (f64 x, f64 y)>` vertex list that precedes the type
/// marker, scanning backward for the nearest count-prefixed run of on-page doubles.
fn read_vertex_list(data: &[u8], marker: usize, width: u32, height: u32) -> Option<Vec<(f64, f64)>> {
    let mut best = None;
    let start = marker.saturating_sub(1200);
    for off in start..marker.saturating_sub(4) {
        let Some(count) = read_u32(data, off) else { continue };
        if !(SHAPE_MIN_VERTICES..=SHAPE_MAX_VERTICES).contains(&count)
            || off + 4 + count as usize * 16 > marker
        {
            continue;
        }
        let mut points = Vec::with_capacity(count as usize);
        let mut ok = true;
        for k in 0..count as usize {
            let x = read_f64(data, off + 4 + k * 16).unwrap();
            let y = read_f64(data, off + 4 + k * 16 + 8).unwrap();
            if !on_page(x, y, width, height) {
                ok = false;
                break;
            }
            points.push((x, y));
        }
        // Require >= 3 distinct points (rounded to 0.1) so a run of zero padding
        // can't masquerade as a vertex list.
        if ok && distinct_rounded(&points) >= 3 {
            best = Some(points); // keep the last (closest to the marker)
        }
    }
    best
}

fn distinct_rounded(points: &[(f64, f64)]) -> usize {
    let mut keys: Vec<(i64, i64)> = points
        .iter()
        .map(|&(x, y)| ((x * 10.0).round() as i64, (y * 10.0).round() as i64))
        .collect();
    keys.sort_unstable();
    keys.dedup();
    keys.len()
}

/// A BGRA color (alpha 0xFF, zero byte before, not pure white) at `i`.
fn bgra_at(data: &[u8], i: usize) -> Option<Color> {
    if i >= 1
        && i + 3 < data.len()
        && data[i + 3] == 0xFF
        && data[i - 1] == 0x00
        && (data[i], data[i + 1], data[i + 2]) != (0xFF, 0xFF, 0xFF)
    {
        Some(Color { r: data[i + 2], g: data[i + 1], b: data[i] })
    } else {
        None
    }
}

/// The shape's stroke color sits just before the type marker, right after the vertex
/// list. Scanning forward past the marker would pick up a different (default) color,
/// so scan backward and keep the occurrence closest to the marker.
fn shape_color_before_marker(data: &[u8], marker: usize) -> Option<Color> {
    let mut best = None;
    for i in marker.saturating_sub(SHAPE_COLOR_BACK_WINDOW).max(1)..marker.saturating_sub(3) {
        if let Some(c) = bgra_at(data, i) {
            best = Some(c); // keep the last (closest)
        }
    }
    best
}

/// Forward color scan for line/arrow objects (color follows the shaft). Keeps the
/// LAST match in the window: when a channel is exactly 0xFF, the zero-padding byte
/// right before the true marker forms a spurious one-byte-early match; the real
/// marker always follows immediately after.
fn nearest_shape_color(data: &[u8], off: usize) -> Option<Color> {
    let end = (off + SHAPE_COLOR_WINDOW).min(data.len().saturating_sub(4));
    let mut best = None;
    for i in off..end {
        if let Some(c) = bgra_at(data, i) {
            best = Some(c);
        }
    }
    best
}

/// Pen line width: the f32 after the `0c 00 00 00` marker in the shape trailer.
fn shape_width(data: &[u8], marker: usize) -> Option<f32> {
    let trailer = &data[marker.min(data.len())..(marker + SHAPE_TRAILER_WINDOW).min(data.len())];
    let k = find_sub(trailer, SHAPE_WIDTH_MARKER)?;
    let candidate = read_f32(data, marker + k + SHAPE_WIDTH_MARKER.len())?;
    (candidate.is_finite() && (0.1..=200.0).contains(&candidate)).then_some(candidate)
}

/// Whether a path is closed: its endpoints are near each other relative to the bbox
/// diagonal (see SHAPE_OPEN_RATIO).
fn shape_is_closed(points: &[(f64, f64)], bbox: &BoundingBox) -> bool {
    let mut diagonal = (bbox.x_max - bbox.x_min).hypot(bbox.y_max - bbox.y_min);
    if diagonal == 0.0 {
        diagonal = 1.0;
    }
    let (first, last) = (points[0], points[points.len() - 1]);
    (first.0 - last.0).hypot(first.1 - last.1) / diagonal < SHAPE_OPEN_RATIO
}

fn to_points(points: Vec<(f64, f64)>) -> Vec<Point> {
    points.into_iter().map(|(x, y)| Point { x, y }).collect()
}

fn to_point((x, y): (f64, f64)) -> Point {
    Point { x, y }
}

/// Map decoded segments 1:1 onto `OutlineOp` — no anchor-tracking needed (unlike
/// `flatten_outline`, which needs the running point to sample a cubic): each
/// segment already carries its own coordinates verbatim.
fn to_outline_ops(segments: &[(u8, Vec<(f64, f64)>)]) -> Vec<OutlineOp> {
    segments
        .iter()
        .filter_map(|(tag, seg)| match tag {
            1 => Some(OutlineOp::MoveTo(to_point(seg[0]))),
            2 => Some(OutlineOp::LineTo(to_point(seg[0]))),
            4 => Some(OutlineOp::CurveTo(to_point(seg[0]), to_point(seg[1]), to_point(seg[2]))),
            _ => None,
        })
        .collect()
}

/// Decode one marker-based shape at absolute offset `marker` (pysdocx
/// `_parse_shape_marker`). Returns `None` when the bbox isn't a plausible on-page
/// rect or no usable outline/vertex list is found.
pub(crate) fn parse_shape_marker(data: &[u8], marker: usize, width: u32, height: u32) -> Option<Shape> {
    if marker + 11 + 32 > data.len() {
        return None;
    }
    let type_code = read_u32(data, marker + 7)?;
    let bbox = BoundingBox {
        x_min: read_f64(data, marker + 11)?,
        y_min: read_f64(data, marker + 19)?,
        x_max: read_f64(data, marker + 27)?,
        y_max: read_f64(data, marker + 35)?,
    };
    let finite = bbox.x_min.is_finite() && bbox.y_min.is_finite() && bbox.x_max.is_finite() && bbox.y_max.is_finite();
    if !(finite
        && -5.0 <= bbox.x_min
        && bbox.x_min < bbox.x_max
        && bbox.x_max <= width as f64 + 5.0
        && -5.0 <= bbox.y_min
        && bbox.y_min < bbox.y_max
        && bbox.y_max <= height as f64 + 5.0)
    {
        return None;
    }

    let color = shape_color_before_marker(data, marker);
    let pen_width = shape_width(data, marker);

    let mut outline: Option<Vec<OutlineOp>> = None;
    let points = if has_degenerate_outline(type_code) {
        read_vertex_list(data, marker, width, height)?
    } else {
        let segments = decode_outline(data, marker + SHAPE_OUTLINE_OFFSET, width, height);
        let flat = flatten_outline(&segments);
        if flat.len() < 3 {
            // not a usable outline — try the vertex list
            read_vertex_list(data, marker, width, height)?
        } else {
            outline = Some(to_outline_ops(&segments));
            flat
        }
    };
    if points.is_empty() {
        return None;
    }

    // 88 = angular open, 89 = angular closed (explicit); smooth (90) keeps the
    // geometric test (a closed blob can have distant endpoints); everything else is
    // a closed primitive.
    let closed = match type_code {
        88 => false,
        90 => shape_is_closed(&points, &bbox),
        _ => true,
    };

    Some(Shape {
        kind: shape_kind(type_code),
        type_code: Some(type_code),
        bbox,
        points: to_points(points),
        outline,
        color,
        pen_width,
        closed,
        head_start: false,
        head_end: false,
    })
}

/// Decode a markerless line/arrow object within `[obj_start, obj_end)` (pysdocx
/// `_parse_arrow_object`). Returns `None` when the blob is a marker-based shape or
/// carries no on-page shaft.
pub(crate) fn parse_arrow_object(
    data: &[u8],
    obj_start: usize,
    obj_end: usize,
    width: u32,
    height: u32,
) -> Option<Shape> {
    let obj = &data[obj_start.min(data.len())..obj_end.min(data.len())];
    if find_sub(obj, SHAPE_TYPE_MARKER).is_some() {
        return None; // a marker-based shape (incl. hearts), not a line/arrow
    }
    let j = find_sub(obj, ARROW_SHAFT_MARKER)?;
    let shaft_off = obj_start + j + ARROW_SHAFT_MARKER.len();
    let x0 = read_f64(data, shaft_off)?;
    let y0 = read_f64(data, shaft_off + 8)?;
    let x1 = read_f64(data, shaft_off + 16)?;
    let y1 = read_f64(data, shaft_off + 24)?;
    let in_page = |x: f64, y: f64| {
        x.is_finite() && y.is_finite() && (1.0..=width as f64).contains(&x) && (1.0..=height as f64).contains(&y)
    };
    if !(in_page(x0, y0) && in_page(x1, y1)) {
        return None;
    }
    let flag_at = |off: usize| shaft_off + off < data.len() && data[shaft_off + off] == 1;
    Some(Shape {
        kind: ShapeKind::Arrow,
        type_code: None,
        bbox: BoundingBox {
            x_min: x0.min(x1),
            y_min: y0.min(y1),
            x_max: x0.max(x1),
            y_max: y0.max(y1),
        },
        points: vec![Point { x: x0, y: y0 }, Point { x: x1, y: y1 }],
        outline: None,
        color: nearest_shape_color(data, shaft_off + 32),
        pen_width: shape_width(data, shaft_off + 32),
        closed: false,
        head_start: flag_at(ARROW_HEAD_START_OFFSET),
        head_end: flag_at(ARROW_HEAD_END_OFFSET),
    })
}

/// Decode every shape in one object blob (pysdocx `parse_shapes_from_objects` inner
/// loop): all marker-based shapes first; a line/arrow only when no marker parsed.
pub(crate) fn parse_shapes_in_object(
    data: &[u8],
    blob_off: usize,
    blob_end: usize,
    width: u32,
    height: u32,
    out: &mut Vec<Shape>,
) {
    let blob = &data[blob_off.min(data.len())..blob_end.min(data.len())];
    let mut found_marker_shape = false;
    let mut off = 0usize;
    while let Some(rel) = find_sub(&blob[off..], SHAPE_TYPE_MARKER) {
        let marker = blob_off + off + rel;
        off += rel + 1;
        if let Some(shape) = parse_shape_marker(data, marker, width, height) {
            out.push(shape);
            found_marker_shape = true;
        }
    }
    if !found_marker_shape {
        if let Some(arrow) = parse_arrow_object(data, blob_off, blob_end, width, height) {
            out.push(arrow);
        }
    }
}
