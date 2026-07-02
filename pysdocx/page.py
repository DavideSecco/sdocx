"""Parse a .page file's layer/object tree and strokes.

Ported from crates/sdocx/src/page.rs (parse_page / parse_stroke) — the
notebooks' original parse_strokes() only knew the base layout and not the
extra_len attribute block or the StartPointMinusThree variant, which is why
it desyncs on some benchmark pages. The Python reference now walks the stored
layer/object tree first, then decodes only true stroke objects.
"""

import math
import re
import struct

from pysdocx.ink import decode_coordinates, decode_trailing

OBJECT_ENTRY_LEN = 7  # raw_type(u8) + child_count(i16) + blob_size(u32)
OBJECT_BASE_HEADER_LEN = 105
OBJECT_BBOX_OFFSET = 68
STROKE_OBJECT_BASE_TOTAL_SIZE = 121

# Inserted-shape objects (rect/ellipse/line/regular polygon) store their outline as
# absolute f64 vertices, NOT delta-encoded paths, so the normal stroke parser can't read
# them (and desyncs on a page full of them — e.g. benchmark page f5b90a84, 0/52). They are
# laid out as [u32 count][count x (f64 x, f64 y)] with a BGRA color marker right after the
# vertices. scan_shapes() finds them by that signature.
SHAPE_MIN_VERTICES = 2
SHAPE_MAX_VERTICES = 64
SHAPE_COLOR_WINDOW = 80

# Every marker-based shape carries its true outline as a serialized vector path in the object
# trailer, right after `01 04 04 01 00 00 00 <u32 type_code> <bbox 4×f64> <12-byte header>`
# (i.e. at marker+55). The path is a sequence of segments `<u8 tag><tag_pts × (f64 x, f64 y)>`
# with a ONE-BYTE tag: 1=MoveTo (1 pt), 2=LineTo (1 pt), 4=CubicBezierTo (3 pts). Earlier
# attempts assumed 4-byte tags with 8-aligned doubles and couldn't align it (the "3-byte
# padding" mystery) — the tags are single bytes, which shifts every double. Decoding this gives
# each shape's REAL (rotated / degree-of-freedom-deformed) vertices, so triangle/rect/hexagon/
# rhombus/trapezoid/pentagon/star/cross/heart and freeform all render from their true outline
# instead of a canonical primitive. Verified on OnlyShapesblack_new p8, OnlyShapesblack_173146
# and benchmark p3. Only ellipse (1) and rounded-rect (64) have a degenerate path (a lone
# MoveTo); they keep the vertex-list approach (ellipse_from_points / oriented_corners).
SHAPE_TYPE_MARKER = b"\x01\x04\x04\x01\x00\x00\x00"
SHAPE_WIDTH_MARKER = b"\x0c\x00\x00\x00"
SHAPE_TRAILER_WINDOW = 220
SHAPE_OUTLINE_OFFSET = 55  # marker(7) + type_code(4) + bbox(32) + header(12)
SHAPE_COLOR_BACK_WINDOW = 160  # BGRA color sits just before the marker (after the vertex list)
OUTLINE_SEG_POINTS = {1: 1, 2: 1, 4: 3}  # MoveTo, LineTo, CubicBezierTo
BEZIER_PER_SEG = 16  # flattening resolution for cubic segments
SHAPE_TYPES = {
    1: "ellipse",
    2: "triangle",
    4: "rectangle",
    6: "hexagon",
    8: "rhombus",
    9: "trapezoid",
    11: "pentagon",
    13: "star",
    17: "cross",
    23: "heart",  # NOT arrow — the top-row code-23 objects are hearts (bbox y 82-299 on p8)
    64: "rounded_rect",
    88: "freeform",  # angular, open
    89: "freeform",  # angular, closed
    90: "freeform_smooth",
}

# Types whose stored outline path is degenerate (lone MoveTo) — render from the vertex list.
DEGENERATE_OUTLINE_TYPES = frozenset({1, 64})

# A smooth freeform (code 90) shape whose first and last points are far apart (relative to its
# diagonal) was drawn open (arc / spiral) rather than closed; no explicit flag was found near the
# type marker, so we test geometrically. With the real outline path (not the old vertex list), a
# genuinely closed path closes EXACTLY (ratio == 0.0, verified on benchmark p3's blue/red blobs
# and p8's closed smooth shapes), while every open curve — including a spiral, whose end can land
# close to its own earlier coils — measures >= 0.356. So the threshold only needs to separate
# "the path closes on itself" from "it doesn't"; 0.6 was tuned for the old geometry and let the
# spiral (0.356) through as closed.
SHAPE_OPEN_RATIO = 0.05

# Imported-image placement records carry the 4-byte marker `01 00 04 20`, with the media
# index as a u16 6 bytes before it and the placement bbox (4 x f64) 11 bytes after it.
# Confirmed on benchmark page 73920cee: media[7] (the imported jpg) at (71,395)-(943,940).
# The normal stroke loop desyncs before reaching this record (which is why the Rust viewer,
# whose element scan starts from the post-stroke offset, misses the image) — so we scan the
# whole page independently.
IMAGE_MARKER = b"\x01\x00\x04\x20"
IMAGE_MEDIA_INDEX_BACK = 6  # u16 media index this many bytes before the marker
IMAGE_BBOX_FWD = 11  # 4 x f64 bbox this many bytes after the marker
IMAGE_MEDIA_REF_MARKER = b"\x06\x00\x3e\x00\x00\x00\x02\x00"
TEXT_BOX_TEXT_MARKER = b"\x06\x00\xbf\x00\x00\x00"

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


def _bbox_is_page_scaled(bbox: tuple[float, float, float, float], width: int, height: int) -> bool:
    """The stroke-header bbox itself is a plausible page-sized rectangle (generous 2x margin).

    `points_fit_bbox` only checks that points fall inside the given bbox, so a misdecoded record
    whose header bbox is astronomically large (seen: ~1e150) trivially "contains" any points —
    it's accepted as fits_bbox=True even though the bbox is garbage. This closes that loophole."""
    if not all(math.isfinite(v) for v in bbox):
        return False
    x_min, y_min, x_max, y_max = bbox
    mx, my = width * 2, height * 2
    return -mx <= x_min <= x_max <= width + mx and -my <= y_min <= y_max <= height + my


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


# Sanity cap for parsed stroke payloads. Object sizes now provide record boundaries, so this is
# only a validity guard.
STROKE_MAX_POINTS = 4000

# Raw object bytes are build/version dependent and do not match the external RE project's table
# on our Samsung Notes samples. Treat this as a conservative fallback only; _classify_page_object
# prefers payload markers, which are what identify shape/image/drawing reliably in our corpus.
RAW_OBJECT_TYPE_NAMES = {
    1: "stroke",
    2: "object_2",
    3: "object_3",
    4: "container",
    7: "object_7",
    8: "object_8",
    11: "pdf",
    13: "object_13",
    14: "object_14",
    15: "stroke_v2",
    20: "table",
    22: "object_22",
    23: "object_23",
}


def _printable_utf16_runs(data: bytes, start: int = 0, min_chars: int = 3) -> list[tuple[int, str]]:
    runs: list[tuple[int, str]] = []
    i = start
    while i + 2 <= len(data):
        unit = struct.unpack_from("<H", data, i)[0]
        if unit == 0x0A or 0x20 <= unit <= 0xD7FF:
            j = i
            chars = []
            while j + 2 <= len(data):
                unit = struct.unpack_from("<H", data, j)[0]
                if not (unit == 0x0A or 0x20 <= unit <= 0xD7FF):
                    break
                chars.append(chr(unit))
                j += 2
            text = "".join(chars)
            if len(text) >= min_chars and any(ch.isalnum() for ch in text):
                runs.append((i, text))
            i = j + 2
        else:
            i += 2
    return runs


def _text_score(text: str) -> tuple[int, int, int]:
    stripped = text.strip()
    if not stripped:
        return (0, 0, 0)
    ascii_printable = sum(1 for ch in stripped if ch == "\n" or 0x20 <= ord(ch) <= 0x7E)
    letters = sum(1 for ch in stripped if ch.isalpha())
    separators = sum(1 for ch in stripped if ch.isspace() or ch in ".,;:!?'-_/()")
    return (ascii_printable + letters + separators, ascii_printable, len(stripped))


def _text_from_marker(blob: bytes) -> tuple[int, str] | None:
    off = OBJECT_BASE_HEADER_LEN
    while True:
        marker = blob.find(TEXT_BOX_TEXT_MARKER, off)
        if marker < 0:
            return None
        len_off = marker + len(TEXT_BOX_TEXT_MARKER)
        if len_off + 4 > len(blob):
            return None
        char_len = struct.unpack_from("<I", blob, len_off)[0]
        text_off = len_off + 4
        end = text_off + char_len * 2
        if 0 < char_len < 10000 and end <= len(blob):
            text = blob[text_off:end].decode("utf-16-le", errors="replace").rstrip("\x00\n")
            if text.strip():
                return text_off, text
        off = marker + 1


def _text_box_text(blob: bytes) -> tuple[int, str] | None:
    parsed = _text_from_marker(blob)
    if parsed is not None:
        return parsed

    runs = _printable_utf16_runs(blob, OBJECT_BASE_HEADER_LEN, min_chars=3)
    if not runs:
        return None
    off, text = max(runs, key=lambda item: _text_score(item[1]))
    text = text.strip("\x00")
    if not text.strip():
        return None
    return off, text.rstrip("\n")


def _read_utf16_string(data: bytes, offset: int) -> tuple[str, int] | None:
    if offset + 2 > len(data):
        return None
    char_len = struct.unpack_from("<h", data, offset)[0]
    if char_len < 0:
        return None
    start = offset + 2
    end = start + char_len * 2
    if end > len(data):
        return None
    return data[start:end].decode("utf-16-le", errors="replace"), end


def _read_utf8_string(data: bytes, offset: int) -> tuple[str, int] | None:
    if offset + 2 > len(data):
        return None
    byte_len = struct.unpack_from("<h", data, offset)[0]
    if byte_len < 0:
        return None
    start = offset + 2
    end = start + byte_len
    if end > len(data):
        return None
    return data[start:end].split(b"\x00", 1)[0].decode("utf-8", errors="replace"), end


def _parse_object_header(blob: bytes) -> dict | None:
    """Parse the common object header at the start of an object blob.

    The layer stream gives reliable object boundaries: `raw_type, child_count, size, blob`.
    The blob then starts with Samsung's common object header. In the current samples the bbox
    starts at byte 68 and variable data at byte 105, but this reader still follows the flag
    lengths so future variants are easier to spot in diagnostics.
    """
    if len(blob) < OBJECT_BASE_HEADER_LEN:
        return None

    try:
        pos = 0
        total_size = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        data_type = struct.unpack_from("<h", blob, pos)[0]
        pos += 2
        var_data_offset = struct.unpack_from("<I", blob, pos)[0]
        pos += 4

        flag_len = blob[pos]
        pos += 1
        flags = int.from_bytes(blob[pos : min(pos + flag_len, len(blob))], "little")
        pos += flag_len

        field_len = blob[pos]
        pos += 1
        field_flags = int.from_bytes(blob[pos : min(pos + field_len, len(blob))], "little")
        pos += field_len

        format_version = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        uuid_result = _read_utf8_string(blob, pos)
        if uuid_result is None:
            return None
        uuid, pos = uuid_result

        modified_time = struct.unpack_from("<q", blob, pos)[0]
        pos += 8
        bbox = struct.unpack_from("<4d", blob, pos)
        pos += 32
        timestamp = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        resizable = bool(blob[pos])
        pos += 1

        return {
            "total_size": total_size,
            "data_type": data_type,
            "var_data_offset": var_data_offset,
            "flag_len": flag_len,
            "flags": flags,
            "field_len": field_len,
            "field_flags": field_flags,
            "format_version": format_version,
            "uuid": uuid,
            "modified_time": modified_time,
            "bbox": bbox,
            "timestamp": timestamp,
            "resizable": resizable,
            "attributes_offset": pos,
        }
    except (IndexError, struct.error):
        return None


def _classify_page_object(raw_type: int, blob: bytes) -> str:
    if raw_type == 1:
        return "stroke"
    if IMAGE_MARKER in blob:
        return "image"
    if raw_type == 2 and _text_box_text(blob) is not None:
        return "text_box"
    if SHAPE_TYPE_MARKER in blob or ARROW_SHAFT_MARKER in blob:
        return "shape"
    if DRAWING_MARKER in blob:
        return "drawing"
    return RAW_OBJECT_TYPE_NAMES.get(raw_type, f"type_{raw_type}")


def _parse_stroke_object(data: bytes, blob_off: int, blob: bytes, width: int, height: int) -> tuple[dict | None, str]:
    header = _parse_object_header(blob)
    if header is None:
        return None, "dropped_bad_object_header"

    extra_len = max(header["total_size"] - STROKE_OBJECT_BASE_TOTAL_SIZE, 0)
    stroke_off = blob_off + OBJECT_BBOX_OFFSET
    current = parse_stroke(data, stroke_off, extra_len, "current")
    shifted = parse_stroke(data, stroke_off, extra_len, "shifted")
    parsed = _select_layout(current, shifted)

    # HANDOFF NOTE (2026-07-02, Claude, on top of the tree-parser rewrite): this used to be
    #   accepted = parsed is not None and parsed["n_points_field"] <= STROKE_MAX_POINTS and (...)
    # i.e. the point-count cap applied unconditionally, to BOTH acceptance paths below. That
    # dropped a real stroke: samples/quiz.sdocx has one legitimate object with 23038 points (dense
    # scribbling on a 1812x15372 scrollable page) whose header bbox is fully trustworthy
    # (fits_bbox=True AND _bbox_is_page_scaled=True) — decoded correctly, just large. The
    # unconditional cap rejected it anyway, so that page came out 3227/3228 instead of 3228/3228.
    #
    # The fix: STROKE_MAX_POINTS now guards ONLY the second branch below (the within_page_bounds
    # fallback, used when the header bbox can't be trusted and we fall back to the *decoded
    # points* alone as evidence). That's the branch where a garbage/misaligned decode could still
    # fabricate a plausible-looking-but-huge point cloud, so a sanity cap earns its keep there.
    # When the header bbox itself is trustworthy (bbox-consistent AND page-scaled), a large point
    # count is just evidence of a real, detailed stroke — not a decode failure — so it's no longer
    # gated by STROKE_MAX_POINTS in the `trusted_bbox` branch.
    #
    # Verified with `python -m pysdocx stroke-table` across every file in samples/ (11 files):
    # zero MISMATCH anywhere after this change (quiz.sdocx was the only failure before, now
    # 3228/3228). Do NOT revert to the unconditional cap without re-checking quiz.sdocx first.
    trusted_bbox = parsed is not None and parsed["fits_bbox"] and _bbox_is_page_scaled(parsed["bbox"], width, height)
    accepted = parsed is not None and (
        trusted_bbox
        or (parsed["n_points_field"] <= STROKE_MAX_POINTS and within_page_bounds(parsed["points"], width, height))
    )
    if not accepted:
        return parsed, "dropped_invalid_stroke_payload"

    if trusted_bbox:
        if looks_like_flat_synthetic_line(parsed):
            x0, y0, x1, y1 = parsed["bbox"]
            parsed["points"] = [(x0, y0), (x1, y1)]
            outcome = "kept_flat_line"
        else:
            outcome = "kept"
    else:
        parsed["bbox"] = bbox_of(parsed["points"])
        outcome = "kept_recovered_bbox"

    parsed["object_header"] = header
    parsed["object_blob_off"] = blob_off
    return parsed, outcome


def _stroke_attempt(idx: int, parsed: dict, outcome: str, obj: dict) -> dict:
    return {
        "idx": idx,
        "object_idx": obj["idx"],
        "object_type": obj["raw_type"],
        "object_off": obj["off"],
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


def _parse_objects(data: bytes, pos: int, count: int, width: int, height: int, depth: int = 0) -> tuple[list[dict], int]:
    objects: list[dict] = []
    for idx in range(count):
        if pos + OBJECT_ENTRY_LEN > len(data):
            break
        off = pos
        raw_type = data[pos]
        child_count = struct.unpack_from("<h", data, pos + 1)[0]
        blob_size = struct.unpack_from("<I", data, pos + 3)[0]
        blob_off = pos + OBJECT_ENTRY_LEN
        blob_end = blob_off + blob_size
        if blob_end > len(data):
            break

        blob = data[blob_off:blob_end]
        header = _parse_object_header(blob)
        obj = {
            "idx": idx,
            "off": off,
            "blob_off": blob_off,
            "end": blob_end,
            "raw_type": raw_type,
            "type": _classify_page_object(raw_type, blob),
            "child_count": child_count,
            "size": blob_size,
            "header": header,
            "bbox": header["bbox"] if header else None,
            "children": [],
        }
        pos = blob_end
        if child_count > 0 and depth < 16:
            obj["children"], pos = _parse_objects(data, pos, child_count, width, height, depth + 1)
        objects.append(obj)
    return objects, pos


def _iter_objects(objects: list[dict]):
    for obj in objects:
        yield obj
        yield from _iter_objects(obj["children"])


def parse_page_tree(data: bytes, width: int, height: int, base: int) -> dict:
    """Parse the layer/object tree using stored object sizes instead of stroke resync."""
    if base + 4 > len(data):
        return {"layers": [], "object_count": 0}

    pos = base
    layer_count, current_layer_index = struct.unpack_from("<HH", data, pos)
    pos += 4

    layers: list[dict] = []
    object_count = 0
    for layer_idx in range(layer_count):
        if pos + 4 > len(data):
            break
        layer_prefix = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        layer_off = pos
        if pos + 12 > len(data):
            break
        next_offset = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        flag1, flag2, flag3, content_flags = struct.unpack_from("<BBBB", data, pos)
        pos += 4
        layer_flags = struct.unpack_from("<I", data, pos)[0]
        pos += 4

        layer_uuid = ""
        modified_time = None
        if content_flags & 0x01:
            pos += 1
        if content_flags & 0x02:
            pos += 4
        if content_flags & 0x04:
            result = _read_utf16_string(data, pos)
            if result is None:
                break
            _, pos = result
        if content_flags & 0x08:
            result = _read_utf16_string(data, pos)
            if result is None:
                break
            layer_uuid, pos = result
        if content_flags & 0x10:
            if pos + 8 > len(data):
                break
            modified_time = struct.unpack_from("<q", data, pos)[0]
            pos += 8
        if content_flags & 0x20:
            pos += 4

        if pos + 4 > len(data):
            break
        layer_object_count = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        objects, pos = _parse_objects(data, pos, layer_object_count, width, height)
        object_count += sum(1 for _ in _iter_objects(objects))

        layer_hash = None
        if pos + 32 <= len(data):
            layer_hash = data[pos : pos + 32].hex()
            pos += 32

        layers.append({
            "idx": layer_idx,
            "off": layer_off,
            "prefix": layer_prefix,
            "next_offset": next_offset,
            "flags": (flag1, flag2, flag3),
            "content_flags": content_flags,
            "layer_flags": layer_flags,
            "uuid": layer_uuid,
            "modified_time": modified_time,
            "object_count": layer_object_count,
            "objects": objects,
            "hash": layer_hash,
            "current": layer_idx == current_layer_index,
        })

    return {"layers": layers, "object_count": object_count, "current_layer_index": current_layer_index}


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
    """Parse a .page file's header + layer/object tree + strokes.

    The layer stream stores deterministic object boundaries (`type, child_count, size, blob`).
    Older code treated that same stream as a flat stroke list and resynced byte-by-byte whenever
    it hit an interleaved object. We now walk the object tree first and decode only raw type-1
    objects as strokes, so mixed pages don't lose handwriting between non-stroke records.
    """
    if len(data) < 0xA0:
        raise ValueError("page file too short for header")

    base = struct.unpack_from("<I", data, 0x00)[0]
    width = struct.unpack_from("<I", data, 0x16)[0]
    height = struct.unpack_from("<I", data, 0x1A)[0]

    uuid_char_len = struct.unpack_from("<H", data, 0x26)[0]
    uuid_bytes = data[0x28 : 0x28 + uuid_char_len * 2]
    uuid = uuid_bytes.decode("utf-16-le", errors="replace")

    content_bbox = struct.unpack_from("<4d", data, 0x80)

    tree = parse_page_tree(data, width, height, base)

    strokes = []
    attempts = []
    stroke_count = 0
    idx = 0
    for layer in tree["layers"]:
        for obj in _iter_objects(layer["objects"]):
            if obj["raw_type"] != 1:
                continue
            stroke_count += 1
            parsed, outcome = _parse_stroke_object(
                data, obj["blob_off"], data[obj["blob_off"] : obj["end"]], width, height
            )
            if parsed is None or not outcome.startswith("kept"):
                continue
            strokes.append(parsed)
            attempts.append(_stroke_attempt(idx, parsed, outcome, obj))
            idx += 1

    return {
        "uuid": uuid,
        "base": base,
        "width": width,
        "height": height,
        "template": page_template(data),
        "content_bbox": content_bbox,
        "layers": tree["layers"],
        "object_count": tree["object_count"],
        "stroke_count": stroke_count,
        "attempted": len(attempts),
        "kept": len(strokes),
        "strokes": strokes,
        "shapes": parse_shapes_from_objects(data, width, height, tree["layers"]),
        "images": scan_images_from_objects(data, width, height, tree["layers"]),
        "drawings": scan_drawings_from_objects(data, width, height, tree["layers"]),
        "text_boxes": parse_text_boxes_from_objects(data, tree["layers"]),
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
        media_index, media_index_off, media_index_size = _image_media_index(data, i, len(data))
        bbox = struct.unpack_from("<4d", data, i + IMAGE_BBOX_FWD)
        x_min, y_min, x_max, y_max = bbox
        if (
            all(math.isfinite(v) for v in bbox)
            and 0 <= x_min < x_max <= width + 5
            and 0 <= y_min < y_max <= height + 5
            and x_max - x_min > 20
            and y_max - y_min > 20
        ):
            images.append({
                "media_index": media_index,
                "media_index_off": media_index_off,
                "media_index_size": media_index_size,
                "bbox": bbox,
                "off": i,
            })
    return images


def _image_media_index(data: bytes, marker: int, limit: int) -> tuple[int, int, int]:
    search_end = min(limit, marker + 180)
    ref = data.find(IMAGE_MEDIA_REF_MARKER, marker, search_end)
    if ref >= 0 and ref + len(IMAGE_MEDIA_REF_MARKER) + 4 <= limit:
        off = ref + len(IMAGE_MEDIA_REF_MARKER)
        return struct.unpack_from("<I", data, off)[0], off, 4
    off = marker - IMAGE_MEDIA_INDEX_BACK
    return struct.unpack_from("<H", data, off)[0], off, 2


def scan_images_from_objects(data: bytes, width: int, height: int, layers: list[dict]) -> list[dict]:
    """Find imported-image placements inside parsed object blobs."""
    images: list[dict] = []
    for layer in layers:
        for obj in _iter_objects(layer["objects"]):
            if obj["type"] != "image":
                continue
            blob = data[obj["blob_off"] : obj["end"]]
            off = 0
            while True:
                rel = blob.find(IMAGE_MARKER, off)
                if rel < 0:
                    break
                off = rel + 1
                i = obj["blob_off"] + rel
                if i - IMAGE_MEDIA_INDEX_BACK < obj["blob_off"] or i + IMAGE_BBOX_FWD + 32 > obj["end"]:
                    continue
                media_index, media_index_off, media_index_size = _image_media_index(data, i, obj["end"])
                bbox = struct.unpack_from("<4d", data, i + IMAGE_BBOX_FWD)
                x_min, y_min, x_max, y_max = bbox
                if (
                    all(math.isfinite(v) for v in bbox)
                    and 0 <= x_min < x_max <= width + 5
                    and 0 <= y_min < y_max <= height + 5
                    and x_max - x_min > 20
                    and y_max - y_min > 20
                ):
                    images.append({
                        "media_index": media_index,
                        "media_index_off": media_index_off,
                        "media_index_size": media_index_size,
                        "bbox": bbox,
                        "off": i,
                        "object_idx": obj["idx"],
                        "object_off": obj["off"],
                    })
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
        media_index_off = i + 4
        media_index = struct.unpack_from("<I", data, media_index_off)[0]
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
            drawings.append({
                "media_index": media_index,
                "media_index_off": media_index_off,
                "media_index_size": 4,
                "bbox": bbox,
                "off": i,
            })
    return drawings


def _valid_drawing_bbox(bbox: tuple[float, float, float, float], width: int, height: int) -> bool:
    x_min, y_min, x_max, y_max = bbox
    return (
        all(math.isfinite(v) for v in bbox)
        and 1 <= x_min < x_max <= width * 1.1
        and 1 <= y_min < y_max <= height * 1.1
        and x_max - x_min > 60
        and y_max - y_min > 60
    )


def scan_drawings_from_objects(
    data: bytes,
    width: int,
    height: int,
    layers: list[dict],
    raster_indices: set[int] | None = None,
) -> list[dict]:
    """Find drawing placements inside parsed object blobs, using the object bbox as placement."""
    drawings: list[dict] = []
    for layer in layers:
        for obj in _iter_objects(layer["objects"]):
            if obj["type"] != "drawing":
                continue
            blob = data[obj["blob_off"] : obj["end"]]
            rel = blob.find(DRAWING_MARKER)
            if rel < 0:
                continue
            i = obj["blob_off"] + rel
            if i + 8 + DRAWING_HASH_LEN > obj["end"]:
                continue
            media_index_off = i + 4
            media_index = struct.unpack_from("<I", data, media_index_off)[0]
            if raster_indices is not None and media_index not in raster_indices:
                continue
            if len(set(data[i + 8 : i + 8 + DRAWING_HASH_LEN])) < DRAWING_HASH_MIN_DISTINCT:
                continue
            bbox = obj["bbox"]
            if bbox is None or not _valid_drawing_bbox(bbox, width, height):
                bbox = None
                for b in range(max(i - DRAWING_BBOX_BACK_MAX, obj["blob_off"]), i - DRAWING_BBOX_BACK_MIN):
                    candidate = [_read_f64(data, b + k) for k in (0, 8, 16, 24)]
                    if any(v is None for v in candidate):
                        continue
                    candidate_bbox = tuple(candidate)
                    if _valid_drawing_bbox(candidate_bbox, width, height):
                        bbox = candidate_bbox
            if bbox is not None:
                drawings.append({
                    "media_index": media_index,
                    "media_index_off": media_index_off,
                    "media_index_size": 4,
                    "bbox": bbox,
                    "off": i,
                    "object_idx": obj["idx"],
                    "object_off": obj["off"],
                })
    return drawings


def parse_text_boxes_from_objects(data: bytes, layers: list[dict]) -> list[dict]:
    text_boxes: list[dict] = []
    for layer in layers:
        for obj in _iter_objects(layer["objects"]):
            if obj["type"] != "text_box":
                continue
            blob = data[obj["blob_off"] : obj["end"]]
            parsed = _text_box_text(blob)
            if parsed is None:
                continue
            text_off, text = parsed
            text_boxes.append({
                "text": text,
                "text_off": obj["blob_off"] + text_off,
                "bbox": obj["bbox"],
                "object_idx": obj["idx"],
                "object_off": obj["off"],
            })
    return text_boxes


def _nearest_shape_color(data: bytes, off: int) -> tuple[int, int, int] | None:
    """Find a BGRA color (alpha 0xFF) right after a shape's vertices, within a small window.

    Keeps the LAST match in the window, not the first: when a color channel is exactly 0xFF
    (e.g. pure red `36 36 ff ff`), the zero-padding byte right before the true marker forms a
    spurious one-byte-early match (`00 36 36 ff` reads as the wrong color `#363600`). The real
    marker always follows immediately after, so the latest match in the window is the right one
    (mirrors `_shape_color_before_marker`'s backward "closest wins" rule)."""
    end = min(off + SHAPE_COLOR_WINDOW, len(data) - 4)
    best = None
    for i in range(off, end):
        if (
            data[i + 3] == 0xFF
            and i >= 1
            and data[i - 1] == 0x00
            and (data[i], data[i + 1], data[i + 2]) != (0xFF, 0xFF, 0xFF)
        ):
            best = (data[i + 2], data[i + 1], data[i])  # BGRA -> (r, g, b)
    return best


def _shape_color_before_marker(data: bytes, marker: int) -> tuple[int, int, int] | None:
    """The shape's stroke color (BGRA, alpha 0xFF) sits just before the type marker, right after
    the vertex list. Scanning forward past the marker would pick up a different (default) color,
    so we scan backward and keep the occurrence closest to the marker. Verified on benchmark p3
    (2×#252525, #0028b8, #d41111, 2×#1a693a — matches ground truth)."""
    best = None
    for i in range(max(marker - SHAPE_COLOR_BACK_WINDOW, 1), marker - 3):
        if (
            data[i + 3] == 0xFF
            and data[i - 1] == 0x00
            and (data[i], data[i + 1], data[i + 2]) != (0xFF, 0xFF, 0xFF)
        ):
            best = (data[i + 2], data[i + 1], data[i])  # BGRA -> (r, g, b); keep the last (closest)
    return best


def decode_outline(data: bytes, off: int, width: int, height: int, max_points: int = 4000) -> list:
    """Decode the serialized vector path at `off` into `[(tag, [(x, y), ...]), ...]`.

    Segments are `<u8 tag><OUTLINE_SEG_POINTS[tag] × (f64 x, f64 y)>` with 1-byte tags
    (1=MoveTo, 2=LineTo, 4=CubicBezierTo). Stops at the first byte that isn't a known tag or a
    point that falls off-page (the natural end of the path)."""
    segments: list = []
    n_points = 0
    o = off
    while n_points < max_points and o < len(data):
        tag = data[o]
        npt = OUTLINE_SEG_POINTS.get(tag)
        if npt is None or o + 1 + npt * 16 > len(data):
            break
        seg: list[tuple[float, float]] = []
        for k in range(npt):
            x = struct.unpack_from("<d", data, o + 1 + k * 16)[0]
            y = struct.unpack_from("<d", data, o + 1 + k * 16 + 8)[0]
            if not (math.isfinite(x) and math.isfinite(y) and -50 <= x <= width + 50 and -50 <= y <= height + 50):
                return segments
            seg.append((x, y))
        segments.append((tag, seg))
        n_points += npt
        o += 1 + npt * 16
    return segments


def _cubic(p0, p1, p2, p3, per_seg):
    """Sample a cubic Bezier at `per_seg` points (endpoint excluded; the next segment adds it)."""
    out = []
    for i in range(per_seg):
        t = i / per_seg
        mt = 1 - t
        a, b, c, d = mt**3, 3 * mt**2 * t, 3 * mt * t**2, t**3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def flatten_outline(segments, per_seg: int = BEZIER_PER_SEG) -> list:
    """Flatten decode_outline segments into a plain point list ready to draw: LineTo points are
    appended directly, CubicBezierTo segments are sampled with the previous point as the anchor."""
    points: list[tuple[float, float]] = []
    for tag, seg in segments:
        if tag == 4 and points:
            points.extend(_cubic(points[-1], seg[0], seg[1], seg[2], per_seg))
            points.append(seg[2])
        else:  # MoveTo / LineTo (or a leading cubic with no anchor yet)
            points.extend(seg)
    return points


def _read_vertex_list(data: bytes, marker: int, width: int, height: int) -> list | None:
    """Read the `<u32 count><count × (f64 x, f64 y)>` vertex list that precedes the type marker.

    Used only for ellipse (8 boundary points) and rounded-rect (4 edge-midpoints), whose outline
    path is degenerate. Scans backward for the nearest count-prefixed run of on-page doubles."""
    best = None
    for off in range(max(marker - 1200, 0), marker - 4):
        count = struct.unpack_from("<I", data, off)[0]
        if not (SHAPE_MIN_VERTICES <= count <= SHAPE_MAX_VERTICES) or off + 4 + count * 16 > marker:
            continue
        points: list[tuple[float, float]] = []
        ok = True
        for k in range(count):
            x = struct.unpack_from("<d", data, off + 4 + k * 16)[0]
            y = struct.unpack_from("<d", data, off + 4 + k * 16 + 8)[0]
            if not (math.isfinite(x) and math.isfinite(y) and -50 <= x <= width + 50 and -50 <= y <= height + 50):
                ok = False
                break
            points.append((x, y))
        if ok and len({(round(x, 1), round(y, 1)) for x, y in points}) >= 3:
            best = points  # keep the last (closest to the marker)
    return best


def _shape_width(data: bytes, marker: int) -> float | None:
    """Pen line width: the f32 after the `0c 00 00 00` marker in the shape trailer."""
    trailer = data[marker : marker + SHAPE_TRAILER_WINDOW]
    k = trailer.find(SHAPE_WIDTH_MARKER)
    if 0 <= k and marker + k + 4 + 4 <= len(data):
        candidate = struct.unpack_from("<f", data, marker + k + len(SHAPE_WIDTH_MARKER))[0]
        if candidate == candidate and 0.1 <= candidate <= 200.0:
            return candidate
    return None


def _parse_shape_marker(data: bytes, marker: int, width: int, height: int) -> dict | None:
    if marker + 11 + 32 > len(data):
        return None
    type_code = struct.unpack_from("<I", data, marker + 7)[0]
    bbox = struct.unpack_from("<4d", data, marker + 11)
    x_min, y_min, x_max, y_max = bbox
    if not (
        all(math.isfinite(v) for v in bbox)
        and -5 <= x_min < x_max <= width + 5
        and -5 <= y_min < y_max <= height + 5
    ):
        return None

    shape_type = SHAPE_TYPES.get(type_code, "polygon")
    color = _shape_color_before_marker(data, marker)
    pen_width = _shape_width(data, marker)

    if type_code in DEGENERATE_OUTLINE_TYPES:
        points = _read_vertex_list(data, marker, width, height)
    else:
        points = flatten_outline(decode_outline(data, marker + SHAPE_OUTLINE_OFFSET, width, height))
        if len(points) < 3:  # not a usable outline — try the vertex list
            points = _read_vertex_list(data, marker, width, height)
    if not points:
        return None

    # 88 = angular open, 89 = angular closed (explicit); smooth (90) keeps the geometric test
    # (a closed blob can have distant endpoints); everything else is a closed primitive.
    if type_code == 88:
        closed = False
    elif type_code == 90:
        closed = _shape_is_closed(points, bbox)
    else:
        closed = True

    return {
        "off": marker,
        "points": points,
        "color": color or (37, 37, 37),
        "type_code": type_code,
        "type": shape_type,
        "bbox": (x_min, y_min, x_max, y_max),
        "width": pen_width,
        "closed": closed,
    }


def scan_shapes(data: bytes, width: int, height: int) -> list[dict]:
    """Back-compat wrapper: the shape point-lists as `{off, points, color}` (see parse_shapes).

    Kept for the public API; parse_shapes is now anchored on the type marker (more robust and it
    also finds hearts, whose 2-point bbox list the old vertex-list scan rejected)."""
    return [
        {"off": s["off"], "points": s["points"], "color": s["color"]}
        for s in parse_shapes(data, width, height)
        if s["type"] != "arrow"
    ]


def parse_shapes(data: bytes, width: int, height: int) -> list[dict]:
    """Marker-anchored inserted shapes with their true outline, type, bbox, color and pen width.

    Anchored on the `01 04 04 01 00 00 00` type marker, which reliably locates every shape
    (including hearts). For each: `type_code`/`type` (SHAPE_TYPES), `bbox` (4×f64 at marker+11),
    `color` (scanned backward, `_shape_color_before_marker`), `width`, and `points` = the real
    flattened outline path (decode_outline/flatten_outline). Ellipse and rounded-rect have a
    degenerate path, so they fall back to the vertex list for ellipse_from_points/oriented_corners.
    Arrows (markerless) are appended by scan_arrows. Each entry:
    `{off, points, color, type_code, type, bbox, width, closed}`.
    """
    shapes: list[dict] = []
    off = 0
    while True:
        marker = data.find(SHAPE_TYPE_MARKER, off)
        if marker < 0:
            break
        off = marker + 1
        shape = _parse_shape_marker(data, marker, width, height)
        if shape is not None:
            shapes.append(shape)

    shapes.extend(scan_arrows(data, width, height))
    return shapes


def _shape_is_closed(points, bbox) -> bool:
    """Whether a shape's path is closed: its first and last points are near each other relative to
    the bbox diagonal. Canonical primitives read as closed; only open freeform curves come out False."""
    x0, y0, x1, y1 = bbox
    diagonal = math.hypot(x1 - x0, y1 - y0) or 1.0
    first, last = points[0], points[-1]
    return math.hypot(first[0] - last[0], first[1] - last[1]) / diagonal < SHAPE_OPEN_RATIO


# The line/arrow tool is a distinct, markerless object (no `01 04 04 01` type code): a 2-point
# shaft (start -> end) right after the sub-header `01 00 01 0c 02 00 00 00`, plus two arrowhead
# flags a fixed distance past the shaft points — head_end at shaft+76, head_start at shaft+78.
# A plain line has neither, a single arrow has head_end, a double arrow has both. (The old code
# mistook the code-23 HEART marker for arrows; hearts are now decoded as shapes.) We enumerate
# uuid-delimited objects and keep the markerless ones carrying the shaft. Confirmed on
# OnlyShapesblack_new p8 (3 single + 2 double arrows) and OnlyShapesblack_173146 p1 (3 plain
# lines); 0 on benchmark p3/p4 (their only arrow is inside the freehand DISEGNO raster).
ARROW_SHAFT_MARKER = b"\x01\x00\x01\x0c\x02\x00\x00\x00"
# Bytes relative to the first shaft coordinate. head_start=1 puts an arrowhead at the start point
# (points[0]); head_end=1 at the end point (points[-1]). A single arrow sets head_start only (its
# head is at points[0], verified against the GT on p8); a double arrow sets both; a line neither.
ARROW_HEAD_START_OFFSET = 76
ARROW_HEAD_END_OFFSET = 78
UUID_RE = re.compile(rb"[0-9a-f]{8}-[0-9a-f]{4}-11f1-[0-9a-f]{4}-[0-9a-f]{12}")


def _parse_arrow_object(data: bytes, obj_start: int, obj_end: int, width: int, height: int) -> dict | None:
    obj = data[obj_start:obj_end]
    if SHAPE_TYPE_MARKER in obj:  # a marker-based shape (incl. hearts), not a line/arrow
        return None
    j = obj.find(ARROW_SHAFT_MARKER)
    if j < 0:
        return None
    shaft_off = obj_start + j + len(ARROW_SHAFT_MARKER)
    coords = [_read_f64(data, shaft_off + 8 * i) for i in range(4)]
    if any(c is None for c in coords):
        return None
    x0, y0, x1, y1 = coords
    if not (all(math.isfinite(c) for c in coords)
            and 1 <= x0 <= width and 1 <= y0 <= height and 1 <= x1 <= width and 1 <= y1 <= height):
        return None
    points = [(x0, y0), (x1, y1)]
    head_end = shaft_off + ARROW_HEAD_END_OFFSET < len(data) and data[shaft_off + ARROW_HEAD_END_OFFSET] == 1
    head_start = shaft_off + ARROW_HEAD_START_OFFSET < len(data) and data[shaft_off + ARROW_HEAD_START_OFFSET] == 1
    color = _nearest_shape_color(data, shaft_off + 32)  # line/arrow color follows the shaft
    pen_width = _shape_width(data, shaft_off + 32)
    return {
        "off": obj_start + j,
        "points": points,
        "color": color or (37, 37, 37),
        "type_code": None,
        "type": "arrow",
        "bbox": (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
        "width": pen_width,
        "head_start": head_start,
        "head_end": head_end,
        "closed": False,
    }


def scan_arrows(data: bytes, width: int, height: int) -> list[dict]:
    """Find line/arrow shapes: `{points: [(x0, y0), (x1, y1)], color, bbox, type: 'arrow', width,
    head_start, head_end}`.

    `points` is start->end (the real shaft). `head_end`/`head_start` say whether to draw an
    arrowhead at P1 / P0 — a plain line has neither, a single arrow has `head_end`, a double
    arrow has both."""
    arrows: list[dict] = []
    bounds = [m.start() for m in UUID_RE.finditer(data)]
    bounds.append(len(data))
    for k in range(len(bounds) - 1):
        arrow = _parse_arrow_object(data, bounds[k], bounds[k + 1], width, height)
        if arrow is not None:
            arrows.append(arrow)
    return arrows


def parse_shapes_from_objects(data: bytes, width: int, height: int, layers: list[dict]) -> list[dict]:
    """Parse shape/line objects from deterministic object blobs."""
    shapes: list[dict] = []
    for layer in layers:
        for obj in _iter_objects(layer["objects"]):
            if obj["type"] != "shape":
                continue
            blob = data[obj["blob_off"] : obj["end"]]
            found_marker_shape = False
            off = 0
            while True:
                rel = blob.find(SHAPE_TYPE_MARKER, off)
                if rel < 0:
                    break
                off = rel + 1
                shape = _parse_shape_marker(data, obj["blob_off"] + rel, width, height)
                if shape is None:
                    continue
                shape["object_idx"] = obj["idx"]
                shape["object_off"] = obj["off"]
                shapes.append(shape)
                found_marker_shape = True
            if found_marker_shape:
                continue
            arrow = _parse_arrow_object(data, obj["blob_off"], obj["end"], width, height)
            if arrow is not None:
                arrow["object_idx"] = obj["idx"]
                arrow["object_off"] = obj["off"]
                shapes.append(arrow)
    return shapes
