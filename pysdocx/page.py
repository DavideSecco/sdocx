"""Parse a .page file's strokes.

Ported from crates/sdocx/src/page.rs (parse_page / parse_stroke) — the
notebooks' original parse_strokes() only knew the base layout and not the
extra_len attribute block or the StartPointMinusThree variant, which is why
it desyncs on some benchmark pages. Keep this in sync with page.rs; it is the
validated reference implementation.
"""

import math
import struct

from pysdocx.ink import decode_coordinates, decode_trailing

PRE_STROKE_RECORD_LEN = 71
STROKE_HEADER_LEN = 89  # bbox(32) + meta(41) + start(16)
EXTRA_LEN_BIAS = 0x79  # byte value at record+3 when no extras are present

# Inserted-shape objects (rect/ellipse/line/regular polygon) store their outline as
# absolute f64 vertices, NOT delta-encoded paths, so the normal stroke parser can't read
# them (and desyncs on a page full of them — e.g. benchmark page f5b90a84, 0/52). They are
# laid out as [u32 count][count x (f64 x, f64 y)] with a BGRA color marker right after the
# vertices. scan_shapes() finds them by that signature.
SHAPE_MIN_VERTICES = 2
SHAPE_MAX_VERTICES = 64
SHAPE_COLOR_WINDOW = 80

# Imported-image placement records carry the 4-byte marker `01 00 04 20`, with the media
# index as a u16 6 bytes before it and the placement bbox (4 x f64) 11 bytes after it.
# Confirmed on benchmark page 73920cee: media[7] (the imported jpg) at (71,395)-(943,940).
# The normal stroke loop desyncs before reaching this record (which is why the Rust viewer,
# whose element scan starts from the post-stroke offset, misses the image) — so we scan the
# whole page independently.
IMAGE_MARKER = b"\x01\x00\x04\x20"
IMAGE_MEDIA_INDEX_BACK = 6  # u16 media index this many bytes before the marker
IMAGE_BBOX_FWD = 11  # 4 x f64 bbox this many bytes after the marker

# Page background templates. The builtin template id lives at a base-dependent offset in the
# page header (see page_template(), ported from crates/sdocx/src/page.rs::page_template). Only
# id 5 = squared grid ("quadretti") is confirmed from the benchmark ground truth (all 6 pages
# are id 5); other ids (lined/plain/etc.) stay "plain" until we have samples to map them.
GRID_TEMPLATE_IDS = frozenset({5})

# Grid cell size in page coordinates (page is 1600x2262). Measured from the ground-truth photos
# in samples/allsamsungnotes_gt/: the photos share the page aspect ratio exactly (no crop), and
# the grid spacing is a consistent 58px in the 905px-wide images -> 58 * 1600/905 ≈ 102.5, the
# same vertically and horizontally, across p1/p3/p5. Not found encoded near the template id in
# the header, so we use this fixed measured value.
GRID_SPACING = 102.5

# Grid origin (page coords of the first vertical/horizontal line). Measured from the GT photos:
# vertical lines start flush at x=0 (0,103,206,...) but horizontal lines start ~44px down
# (44,146,249,...) — the template has a small top margin, not a symmetric offset. Rendering the
# grid from y=0 (no offset) put the first line too high and left too little space above the top
# line of text; using this origin matches the photos.
GRID_ORIGIN = (0.0, 44.0)


def _read_u16(data: bytes, offset: int) -> int | None:
    if offset + 2 > len(data):
        return None
    return struct.unpack_from("<H", data, offset)[0]


def _read_u32(data: bytes, offset: int) -> int | None:
    if offset + 4 > len(data):
        return None
    return struct.unpack_from("<I", data, offset)[0]


def _read_f64(data: bytes, offset: int) -> float | None:
    if offset + 8 > len(data):
        return None
    return struct.unpack_from("<d", data, offset)[0]


def points_fit_bbox(points: list[tuple[float, float]], bbox: tuple[float, float, float, float]) -> bool:
    """A correctly-decoded stroke's points fall inside its bounding box (>= 80%, 4px tolerance)."""
    TOL = 4.0
    x_min, y_min, x_max, y_max = bbox
    if not points or not all(math.isfinite(v) for v in bbox) or x_max < x_min or y_max < y_min:
        return False
    inside = sum(
        1
        for x, y in points
        if x_min - TOL <= x <= x_max + TOL and y_min - TOL <= y <= y_max + TOL
    )
    return inside * 5 >= len(points) * 4


def within_page_bounds(points: list[tuple[float, float]], width: int, height: int) -> bool:
    """All points finite and on-page (generous 10% margin), distinguishing a real decode from garbage."""
    if len(points) < 2:
        return False
    mx = max(width * 0.1, 50.0)
    my = max(height * 0.1, 50.0)
    return all(
        math.isfinite(x) and math.isfinite(y) and -mx <= x <= width + mx and -my <= y <= height + my
        for x, y in points
    )


def bbox_of(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


# Strokes with extra_len == 48 are a distinct "flat synthetic line" variant
# (confirmed on samples/Allsamsungnotes_260630_113259.sdocx, page e9561382,
# the "EVIDENZIATORE/PENNARELLO LINEA DRITTA" — straight-line highlighter/
# marker — labeled groups): bbox height is always exactly 1.0 px and the
# coordinate-delta-decoded points cover only a small fraction of the bbox
# width, in all 5 instances found across every sample checked, no
# counterexamples. The bbox itself (already correct — these strokes pass
# `fits_bbox` without needing recovery) is the real line; the decoded
# points are not the path to render, for reasons not yet understood (the
# delta magnitudes don't look like coordinate noise — see
# backlog-ruler-line-precision in memory for the investigation).
FLAT_LINE_EXTRA_LEN = 48
FLAT_LINE_MAX_HEIGHT = 1.5
FLAT_LINE_MAX_DECODED_FRACTION = 0.5


def looks_like_flat_synthetic_line(parsed: dict) -> bool:
    bbox = parsed["bbox"]
    bbox_width = bbox[2] - bbox[0]
    bbox_height = bbox[3] - bbox[1]
    if parsed["extra_len"] != FLAT_LINE_EXTRA_LEN or bbox_height > FLAT_LINE_MAX_HEIGHT or bbox_width <= 0:
        return False
    points = parsed["points"]
    decoded_len = math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1])
    return decoded_len < FLAT_LINE_MAX_DECODED_FRACTION * bbox_width


# Object records (imported images, freehand drawings, tables, sticky-memos) are interleaved with
# strokes in the record stream but don't follow the stroke layout, so the stroke parser misreads
# their length and jumps to a bogus offset — desyncing the stream and losing every following
# stroke (e.g. the "PROMEMORIA ADESIVO"/"TABELLA" labels on benchmark page 73920cee, and the shape
# caption on f5b90a84). When a record fails to parse as a stroke, we resync by scanning forward for
# the next offset that parses as a *clean* stroke (bbox-consistent, on-page, sane point/byte
# counts). This only ever triggers on pages that already desync — pages that parse cleanly (p1/p2,
# the pen/highlighter samples) need zero resyncs and are byte-for-byte unchanged.
STROKE_RESYNC_MAX_SCAN = 40000
STROKE_RESYNC_MAX_POINTS = 4000
STROKE_RESYNC_MIN_DATA_LEN = 8
STROKE_RESYNC_MAX_DATA_LEN = 20000


def _clean_stroke_at(data: bytes, record_off: int, width: int, height: int) -> dict | None:
    """Parse the record at `record_off`; return it only if it's an unambiguously clean stroke."""
    if record_off + PRE_STROKE_RECORD_LEN + STROKE_HEADER_LEN > len(data):
        return None
    extra_len_byte = data[record_off + 3] if record_off + 3 < len(data) else EXTRA_LEN_BIAS
    extra_len = max(extra_len_byte - EXTRA_LEN_BIAS, 0)
    off = record_off + PRE_STROKE_RECORD_LEN
    parsed = _select_layout(
        parse_stroke(data, off, extra_len, "current"),
        parse_stroke(data, off, extra_len, "shifted"),
    )
    if (
        parsed is not None
        and parsed["fits_bbox"]
        and within_page_bounds(parsed["points"], width, height)
        and 2 <= parsed["n_points_field"] <= STROKE_RESYNC_MAX_POINTS
        and STROKE_RESYNC_MIN_DATA_LEN < parsed["data_len"] < STROKE_RESYNC_MAX_DATA_LEN
    ):
        return parsed
    return None


def _next_stroke_record_off(data: bytes, start: int, width: int, height: int) -> int | None:
    """Scan forward from `start` for the next offset that parses as a clean stroke record."""
    record_off = start
    end = min(len(data), start + STROKE_RESYNC_MAX_SCAN)
    while record_off <= end:
        if _clean_stroke_at(data, record_off, width, height) is not None:
            return record_off
        record_off += 1
    return None


def parse_stroke(data: bytes, off: int, extra_len: int, layout: str) -> dict | None:
    """Decode one stroke record at `off` under the given layout ('current' or 'shifted')."""
    bbox_vals = [_read_f64(data, off + k) for k in (0, 8, 16, 24)]
    if any(v is None for v in bbox_vals):
        return None
    bbox = tuple(bbox_vals)

    if layout == "current":
        meta_off, n_points_off, sp_off, next_record_adjust = off + 32 + extra_len, 39, off + 73 + extra_len, 0
    else:  # "shifted" == StrokeLayout::StartPointMinusThree
        meta_off, n_points_off, sp_off, next_record_adjust = off + 32, 36, off + 70, 3

    data_len = _read_u32(data, meta_off + 21)
    n_points = _read_u16(data, meta_off + n_points_off)
    start_x = _read_f64(data, sp_off)
    start_y = _read_f64(data, sp_off + 8)
    if data_len is None or not n_points or start_x is None or start_y is None:
        return None
    if not math.isfinite(start_x) or not math.isfinite(start_y):
        return None

    data_off = sp_off + 16
    data_end = data_off + data_len
    if data_end > len(data):
        return None
    data_blob = data[data_off:data_end]

    points, n_coord_bytes = decode_coordinates(data_blob, start_x, start_y, max(n_points - 1, 0))
    if not points or any(not math.isfinite(x) or not math.isfinite(y) for x, y in points):
        return None

    trailing = decode_trailing(data_blob, n_coord_bytes, max(len(points) - 1, 0))
    fits_bbox = points_fit_bbox(points, bbox)

    return {
        "bbox": bbox,
        "points": points,
        "data_blob": data_blob,
        "n_coord_bytes": n_coord_bytes,
        "extra_len": extra_len,
        "n_points_field": n_points,
        "data_len": data_len,
        "layout": layout,
        "fits_bbox": fits_bbox,
        "next_record_off": data_end + next_record_adjust,
        **trailing,
    }


def _select_layout(current: dict | None, shifted: dict | None) -> dict | None:
    """Same selection rule as Rust: prefer the layout whose points are bbox-consistent."""
    if current and shifted:
        if current["fits_bbox"] and not shifted["fits_bbox"]:
            return current
        if shifted["fits_bbox"] and not current["fits_bbox"]:
            return shifted
        if current["fits_bbox"] and shifted["fits_bbox"]:
            return shifted if len(shifted["points"]) > len(current["points"]) else current
        return current  # neither consistent; advance the stream with `current`
    return current or shifted


def is_builtin_template_id(template_id: int) -> bool:
    """A builtin template id is nonzero and fits in 16 bits (same rule as Rust)."""
    return template_id != 0 and template_id <= 0xFFFF


def page_template(data: bytes) -> dict | None:
    """Read the page background template: `{id, kind, source}` or None if absent.

    Ported from crates/sdocx/src/page.rs::page_template. The id's offset depends on `base`
    (`u32 @0x00`): base==0x90 -> `u32 @0x8C` (compact builtin header); base==0xA6 ->
    `u32 @0x8C >> 16` (custom PDF template, value is the zero-based PDF page index); otherwise
    `u32 @0xAC` if base>=0xE7 else `u32 @0xB4`. `kind` is "grid" for known grid ids
    (GRID_TEMPLATE_IDS), else "plain". Verified to yield id 5 on all 6 benchmark pages.
    """
    base = _read_u32(data, 0x00)
    if base is None:
        return None

    if base == 0x90:
        template_id = _read_u32(data, 0x8C)
        source = "builtin_short"
    elif base == 0xA6:
        raw = _read_u32(data, 0x8C)
        if raw is None:
            return None
        template_id = raw >> 16
        return {"id": template_id, "kind": "plain", "source": "custom_pdf"}
    else:
        template_id = _read_u32(data, 0xAC if base >= 0xE7 else 0xB4)
        source = "builtin"

    if template_id is None or not is_builtin_template_id(template_id):
        return None
    kind = "grid" if template_id in GRID_TEMPLATE_IDS else "plain"
    return {"id": template_id, "kind": kind, "source": source}


def parse_page(data: bytes) -> dict:
    """Parse a .page file's header + strokes, returning per-stroke diagnostics for every attempt."""
    if len(data) < 0xA0:
        raise ValueError("page file too short for header")

    base = struct.unpack_from("<I", data, 0x00)[0]
    width = struct.unpack_from("<I", data, 0x16)[0]
    height = struct.unpack_from("<I", data, 0x1A)[0]

    uuid_char_len = struct.unpack_from("<H", data, 0x26)[0]
    uuid_bytes = data[0x28 : 0x28 + uuid_char_len * 2]
    uuid = uuid_bytes.decode("utf-16-le", errors="replace")

    content_bbox = struct.unpack_from("<4d", data, 0x80)

    sc_off = base + 0x66
    if sc_off + 4 > len(data):
        raise ValueError("page file too short for stroke count")
    stroke_count = struct.unpack_from("<I", data, sc_off)[0]

    strokes = []
    attempts = []
    resyncs = 0
    record_off = base + 0xB5 - PRE_STROKE_RECORD_LEN

    idx = 0
    guard = 0
    max_iterations = stroke_count * 3 + 16  # allow room for resyncs; bounds the loop
    while len(strokes) < stroke_count and guard < max_iterations:
        guard += 1
        extra_len_byte = data[record_off + 3] if record_off + 3 < len(data) else EXTRA_LEN_BIAS
        extra_len = max(extra_len_byte - EXTRA_LEN_BIAS, 0)

        off = record_off + PRE_STROKE_RECORD_LEN
        if off + STROKE_HEADER_LEN + extra_len > len(data):
            break

        current = parse_stroke(data, off, extra_len, "current")
        shifted = parse_stroke(data, off, extra_len, "shifted")
        parsed = _select_layout(current, shifted)

        accepted = parsed is not None and (
            parsed["fits_bbox"] or within_page_bounds(parsed["points"], width, height)
        )
        if not accepted:
            # This record isn't a stroke (an interleaved object, or garbage from a prior desync).
            # Resync onto the next clean stroke record instead of trusting its bogus length.
            resync_off = _next_stroke_record_off(data, record_off + 1, width, height)
            if resync_off is None:
                break
            record_off = resync_off
            resyncs += 1
            continue

        record_off = parsed["next_record_off"]

        outcome = "dropped"
        if parsed["fits_bbox"]:
            if looks_like_flat_synthetic_line(parsed):
                x0, y0, x1, y1 = parsed["bbox"]
                parsed["points"] = [(x0, y0), (x1, y1)]
                outcome = "kept_flat_line"
            else:
                outcome = "kept"
            strokes.append(parsed)
        else:
            parsed["bbox"] = bbox_of(parsed["points"])
            strokes.append(parsed)
            outcome = "kept_recovered_bbox"

        attempts.append(
            {
                "idx": idx,
                "extra_len": parsed["extra_len"],
                "layout": parsed["layout"],
                "n_points_field": parsed["n_points_field"],
                "n_points_decoded": len(parsed["points"]),
                "pen_width": parsed["pen_width"],
                "tool_id": parsed["tool_id"],
                "broad_pen": parsed["broad_pen"],
                "color": parsed["color"],
                "bbox": parsed["bbox"],
                "n_coord_bytes": parsed["n_coord_bytes"],
                "data_len": parsed["data_len"],
                "outcome": outcome,
            }
        )
        idx += 1

    return {
        "uuid": uuid,
        "base": base,
        "width": width,
        "height": height,
        "template": page_template(data),
        "content_bbox": content_bbox,
        "stroke_count": stroke_count,
        "attempted": len(attempts),
        "resyncs": resyncs,
        "kept": len(strokes),
        "strokes": strokes,
        "shapes": scan_shapes(data, width, height),
        "images": scan_images(data, width, height),
        "attempts": attempts,
    }


def scan_images(data: bytes, width: int, height: int) -> list[dict]:
    """Find imported-image placements: `{media_index, bbox: (x_min, y_min, x_max, y_max), off}`.

    Each placement is a `01 00 04 20` marker with a u16 media index just before it and a
    4 x f64 on-page bbox just after (see IMAGE_* offsets). The media index maps to a
    `media/<index>@...` file in the archive (use `pysdocx.load_media_by_index`). Verified to
    find exactly the one image on benchmark page 73920cee and nothing on any other sample.
    """
    images: list[dict] = []
    off = 0
    while True:
        i = data.find(IMAGE_MARKER, off)
        if i < 0:
            break
        off = i + 1
        if i - IMAGE_MEDIA_INDEX_BACK < 0 or i + IMAGE_BBOX_FWD + 32 > len(data):
            continue
        media_index = struct.unpack_from("<H", data, i - IMAGE_MEDIA_INDEX_BACK)[0]
        bbox = struct.unpack_from("<4d", data, i + IMAGE_BBOX_FWD)
        x_min, y_min, x_max, y_max = bbox
        if (
            all(math.isfinite(v) for v in bbox)
            and 0 <= x_min < x_max <= width + 5
            and 0 <= y_min < y_max <= height + 5
            and x_max - x_min > 20
            and y_max - y_min > 20
        ):
            images.append({"media_index": media_index, "bbox": bbox, "off": i})
    return images


# Freehand "drawing" objects (Samsung's drawing/AR-doodle tool) are placed differently from
# imported images: instead of the `01 00 04 20` image marker, the drawing's ascii-uuid object
# record carries `05 00 00 00 [u32 media_index] [32-byte object hash]`, with the placement bbox
# (4 x f64) a short distance before it. The referenced media is a rasterized .jpg preview of the
# drawing. Confirmed on benchmark page 73920cee: media[4] at (71,44)-(947,351), the blue scribble
# ("DISEGNO"). A bare `05 00 00 00` is common in stroke data, so we require the media index to
# resolve to a real raster image (caller passes `raster_indices`) and the following 32 bytes to
# look like a hash (many distinct byte values), which removes all false positives across samples.
DRAWING_MARKER = b"\x05\x00\x00\x00"
DRAWING_HASH_LEN = 32
DRAWING_HASH_MIN_DISTINCT = 24
DRAWING_BBOX_BACK_MIN = 40
DRAWING_BBOX_BACK_MAX = 140


def scan_drawings(data: bytes, width: int, height: int, raster_indices: set[int]) -> list[dict]:
    """Find freehand-drawing placements: `{media_index, bbox: (x_min, y_min, x_max, y_max), off}`.

    `raster_indices` is the set of media indices that are jpg/png (see
    `pysdocx.raster_media_indices`) — only those are accepted, which rejects the many incidental
    `05 00 00 00` byte runs inside stroke data. Complements `scan_images` (which finds imported
    images by their own `01 00 04 20` marker); the two never report the same media.
    """
    drawings: list[dict] = []
    off = 0
    while True:
        i = data.find(DRAWING_MARKER, off)
        if i < 0:
            break
        off = i + 1
        if i + 8 + DRAWING_HASH_LEN > len(data):
            continue
        media_index = struct.unpack_from("<I", data, i + 4)[0]
        if media_index not in raster_indices:
            continue
        if len(set(data[i + 8 : i + 8 + DRAWING_HASH_LEN])) < DRAWING_HASH_MIN_DISTINCT:
            continue
        bbox = None
        for b in range(max(i - DRAWING_BBOX_BACK_MAX, 0), i - DRAWING_BBOX_BACK_MIN):
            candidate = [_read_f64(data, b + k) for k in (0, 8, 16, 24)]
            if any(v is None for v in candidate):
                continue
            x_min, y_min, x_max, y_max = candidate
            if (
                all(math.isfinite(v) for v in candidate)
                and 1 <= x_min < x_max <= width * 1.1
                and 1 <= y_min < y_max <= height * 1.1
                and x_max - x_min > 60
                and y_max - y_min > 60
            ):
                bbox = (x_min, y_min, x_max, y_max)  # keep the last (closest) plausible bbox
        if bbox is not None:
            drawings.append({"media_index": media_index, "bbox": bbox, "off": i})
    return drawings


def _nearest_shape_color(data: bytes, off: int) -> tuple[int, int, int] | None:
    """Find a BGRA color (alpha 0xFF) right after a shape's vertices, within a small window."""
    end = min(off + SHAPE_COLOR_WINDOW, len(data) - 4)
    for i in range(off, end):
        if (
            data[i + 3] == 0xFF
            and i >= 1
            and data[i - 1] == 0x00
            and (data[i], data[i + 1], data[i + 2]) != (0xFF, 0xFF, 0xFF)
        ):
            return (data[i + 2], data[i + 1], data[i])  # BGRA -> (r, g, b)
    return None


def scan_shapes(data: bytes, width: int, height: int) -> list[dict]:
    """Find inserted-shape objects: `[u32 count][count x (f64 x, f64 y)]` + a BGRA color.

    Returns a list of `{points: [(x, y), ...], color: (r, g, b), off: int}`. Transform
    matrices and degenerate artifacts are rejected by requiring a color, a non-degenerate
    on-page bounding box away from the origin, and at least 3 distinct vertices — verified
    to yield zero false positives across all sample files (only benchmark page f5b90a84
    produces shapes).
    """
    shapes: list[dict] = []
    off = 0
    n = len(data)
    while off + 4 <= n:
        count = struct.unpack_from("<I", data, off)[0]
        if SHAPE_MIN_VERTICES <= count <= SHAPE_MAX_VERTICES and off + 4 + count * 16 <= n:
            points: list[tuple[float, float]] = []
            ok = True
            for k in range(count):
                x = struct.unpack_from("<d", data, off + 4 + k * 16)[0]
                y = struct.unpack_from("<d", data, off + 4 + k * 16 + 8)[0]
                if not (math.isfinite(x) and math.isfinite(y) and -50 <= x <= width + 50 and -50 <= y <= height + 50):
                    ok = False
                    break
                points.append((x, y))
            if ok:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                distinct = len({(round(x, 1), round(y, 1)) for x, y in points})
                color = _nearest_shape_color(data, off + 4 + count * 16)
                if (
                    color is not None
                    and distinct >= 3
                    and max(xs) - min(xs) > 20
                    and max(ys) - min(ys) > 20
                    and min(xs) > 5
                    and min(ys) > 5
                ):
                    shapes.append({"off": off, "points": points, "color": color})
                    off += 4 + count * 16
                    continue
        off += 1
    return shapes
