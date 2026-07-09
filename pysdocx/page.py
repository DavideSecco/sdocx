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
from pysdocx.note import (
    BOLD_TAG,
    COLOR_TAG,
    FONT_TAG,
    HIGHLIGHT_TAG,
    ITALIC_TAG,
    RUN_ENABLED_OFF,
    RUN_END_OFF,
    RUN_MARKER_LEN,
    RUN_START_OFF,
    RUN_VALUE_OFF,
    STRIKETHROUGH_MARKER,
    STYLE_MARKER_PREFIX,
    UNDERLINE_TAG,
)

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

# Role of the decoded payload-geometry point list for each marker-based shape family. This is a
# structural interpretation of the wrapper points, not a rendering source of truth: the rendered outline
# still comes from the shape marker's path when available.
SHAPE_PAYLOAD_GEOMETRY_ROLES = {
    1: "outline_vertices",  # ellipse: 8 boundary/control vertices
    2: "vertices_with_edge_midpoints",  # triangle: vertex, midpoint, vertex, ...
    4: "frame_edge_midpoints",
    6: "outline_vertices",
    8: "outline_vertices",
    9: "frame_edge_midpoints",
    11: "outline_vertices",
    13: "outer_vertices",
    17: "frame_edge_midpoints",
    23: "bezier_control_points",
    64: "frame_edge_midpoints",
    88: "freeform_vertices",
    89: "freeform_vertices",
    90: "bezier_control_points",
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

# A rotated image object carries a `field_flags` bit (0x1, alongside 0x40000 — both newly set
# vs. an unrotated placement's 0xe000) and, right at the common header's `attributes_offset`
# (== OBJECT_BASE_HEADER_LEN == 105, confirmed stable across every image object in every sample),
# a plain little-endian f32 holding the rotation angle IN DEGREES, clockwise-positive on screen
# (matplotlib's rotate_deg_around is counterclockwise-positive in data space, but our y-axis is
# inverted for page rendering, which flips the visual sense back to clockwise — see render.py).
# For an unrotated placement this same offset just lands in the middle of other fields (timestamp/
# resizable), giving a near-zero garbage float, so ANGLE_FLAG doubles as the reliable gate.
#
# Cracked and verified against samples/OnlyImages_260702_190147.sdocx (9 hand-labeled images: 3
# groups of 3, GT photo samples/OnlyImages_260702_190147/photo_2026-07-02_19-05-02.jpg), whose
# labels were 0/28/53, 0/90/180, 0/332/254 degrees. Decoded values were 0(unrotated)/29/53,
# 0/90/180, 0/-28(=332 mod 360)/254 — i.e. exact matches on 5 of 6 non-zero angles and 1 off by
# 1 degree (hand-drawn protractor label, not a real mismatch). Also cross-checked against
# samples/Associationpages&stickynote&images&audio_260701_183225.sdocx page 5 (the file that
# first flagged "extra ~20 bytes" before this sample existed): its two rotated placements decode
# to exactly -45.0 and 90.0, matching that file's "~45°/~90°" visual estimate exactly.
IMAGE_ANGLE_OFFSET = OBJECT_BASE_HEADER_LEN  # == 105
IMAGE_ANGLE_FIELD_FLAG = 0x1

# Decoded common-header `field_flags` bits. Every distinct field_flags value in the current 13-sample
# corpus reconstructs its `total_size` from a purely additive model over these bits (baseline 121 for
# stroke/text_box, 122 for the media/shape family), with zero counterexamples:
#   FIELD_FLAG_ANGLE     0x1     +4 bytes   rotation-angle f32 at offset 105 (see IMAGE_ANGLE_* above)
#   FIELD_FLAG_EXTRA_KEY 0x20    +32 bytes  a named attribute block; its key is literally the ASCII string
#                                           "extra_key_stroke_shape" (a u16-length-prefixed string after a
#                                           constant `02 01 00` head), i.e. this stroke is a shape's ink.
#                                           Confirmed identical on 40/40 objects that set the bit.
#   FIELD_FLAG_HDR_EXT   0x40000 +16 bytes  a header extension: [u32 counter][u32 seq][u32 page_width]
#                                           [u32 page_height] — the trailing width/height match the page
#                                           header on 1690/1690 objects; `seq`/`counter`
#                                           semantics NOT settled (seq near-constant per note; counter not
#                                           a unique id) — see _decode_header_ext +
#                                           docs/format/container/page/object-header.md.
# FIELD_FLAG_MEDIA_FAMILY (0x8000) is a family discriminator, not a size contributor: it is set on every
# image/shape/drawing object and on no stroke/text_box object across the corpus. FIELD_FLAG_BASE_PRESENT
# bits (0x2000|0x4000) are set on every object seen so far, so they read as "record present" base bits.
# The +16 and +32 blocks are stored in `total_size`-bit order (extra_key before hdr_ext), so when BOTH
# 0x20 and 0x40000 are set the hdr_ext sits 32 bytes after the extra_key block.
FIELD_FLAG_ANGLE = 0x1
FIELD_FLAG_EXTRA_KEY = 0x20
FIELD_FLAG_MEDIA_FAMILY = 0x8000
FIELD_FLAG_HDR_EXT = 0x40000
FIELD_FLAG_BASE_PRESENT = 0x2000 | 0x4000
HDR_EXT_LEN = 16
EXTRA_KEY_BLOCK_LEN = 32
EXTRA_KEY_MARKER = b"extra_key"
EXTRA_KEY_STROKE_SHAPE = b"extra_key_stroke_shape"
TEXT_BOX_TEXT_PREFIX = b"\x06\x00"
TEXT_BOX_TEXT_MARKER_LEN = 10  # 06 00 <u16 kind> 00 00 <u32 char_count>

# Non-stroke inserted objects start their payload with a small geometry wrapper immediately after
# the common object header: `[u32 L0][u16 tag=6][u32 L1][01 00 01 0c][u32 point_count]` followed by
# `point_count` f64 coordinate pairs. For marker-based shapes and images, the later semantic marker
# sits at `total_size + L0 + 10` / `total_size + L1 + 49`; for text boxes the UTF-16 text marker sits
# 172 bytes after the geometry block's L1-relative start. Exposed as diagnostics because it gives us
# a formal anchor for frame geometry instead of scattered offset constants.
PAYLOAD_GEOMETRY_TAG = 6
PAYLOAD_GEOMETRY_OPCODE = b"\x01\x00\x01\x0c"
PAYLOAD_GEOMETRY_HEADER_LEN = 18
PAYLOAD_GEOMETRY_MIN_POINTS = 1
PAYLOAD_GEOMETRY_MAX_POINTS = 64
PAYLOAD_GEOMETRY_MARKER_L0_DELTA = 10
PAYLOAD_GEOMETRY_MARKER_L1_DELTA = 49
PAYLOAD_GEOMETRY_TEXT_MARKER_L1_DELTA = 172

# Sticky-note (file-attachment) placements on a page are a property-bag object type that isn't
# reachable via the normal layer-object-count-driven tree walk: on the sample where this was
# found (Associationpages...sdocx, page 6ffea07a / logical page 4), the LAYER'S OWN declared
# `object_count` field reads 0 (confirmed, not a walker bug), yet the page's raw bytes contain 2
# real sticky-note placements *outside* that count — same situation as markerless arrows, so the
# same whole-page-scan fix applies (see scan_arrows). Layout: ASCII property bag,
# `<u32 key_len><ascii key>` pairs. The "co_attach_file" key's value breaks the general pattern:
# the u32 right after the key IS the media index itself (not a byte-length prefix), followed by
# a u32 "type tag" (observed value 2, meaning unknown, unused here). Every other key in the bag
# (seen: "skn_bg_color", "skn_collapse_rect") follows the normal `<u32 len><ascii value>` shape;
# "skn_collapse_rect"'s value is a CSV bbox string "x0,y0,x1,y1" in page coordinates. Verified:
# media index 8 -> media/8@stickymemo_...sdocx (the "big" sticky memo) at bbox ~(25,28)-(105,108)
# (top-left corner); media index 6 -> media/6@stickymemo_...sdocx (the "small" one) at bbox
# ~(1320,1870)-(1400,1950) (bottom-right corner) — both anchored to this same page.
STICKY_NOTE_MARKER = b"co_attach_file"
STICKY_NOTE_RECT_KEY = b"skn_collapse_rect"
ATTACHMENT_PROPERTY_BAG_MAX_SCAN = 512
ATTACHMENT_PROPERTY_BAG_MAX_KEYS = 16

# Page background templates. The builtin template id lives at a base-dependent offset in the
# page header (see page_template(), ported from crates/sdocx/src/page.rs::page_template). Both
# id 5 (benchmark, all 6 pages) and id 4 (OnlyTextTypeWritten_squared) are confirmed squared
# grids from the ground truth; other ids (lined/plain/etc.) stay "plain" until we map them.
GRID_TEMPLATE_IDS = frozenset({4, 5})

# Grid cell size in page coordinates (page is 1600x2262). The pitch is NOT stored in the .page
# file (searched the header, and the squared page is only ~340 bytes) — it is a property of the
# template id itself, so we map each measured id to its pitch. Both measured from the 905px-wide
# GT photos which span the page width with no crop: id 5 = 58px -> 58*1600/905 ≈ 102.5; id 4 =
# 41px -> 41*1600/905 ≈ 72.5, same vertically and horizontally. Unknown grid ids fall back to 102.5.
GRID_SPACING = 102.5
GRID_SPACING_BY_ID = {5: 102.5, 4: 72.5}

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


def _decode_text_box_marker(blob: bytes, marker: int, char_len: int) -> tuple[int, str, int] | None:
    text_off = marker + TEXT_BOX_TEXT_MARKER_LEN
    end = text_off + char_len * 2
    if not (0 < char_len < 10000) or end > len(blob):
        return None
    try:
        raw_text = blob[text_off:end].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    text = raw_text.rstrip("\x00\n")
    if not text.strip():
        return None
    if _text_score(text)[0] <= 0:
        return None
    return text_off, text, char_len


def _text_from_marker(blob: bytes) -> tuple[int, str, int] | None:
    best: tuple[int, str, int] | None = None
    best_score = (0, 0, 0)
    off = OBJECT_BASE_HEADER_LEN
    while True:
        marker = blob.find(TEXT_BOX_TEXT_PREFIX, off)
        if marker < 0:
            return best
        if marker + TEXT_BOX_TEXT_MARKER_LEN > len(blob):
            return best
        if blob[marker + 4 : marker + 6] == b"\x00\x00":
            char_len = struct.unpack_from("<I", blob, marker + 6)[0]
            parsed = _decode_text_box_marker(blob, marker, char_len)
            if parsed is not None:
                score = _text_score(parsed[1])
                if score > best_score:
                    best = parsed
                    best_score = score
        off = marker + 1


def _text_box_text(blob: bytes) -> tuple[int, str, int] | None:
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
    return off, text.rstrip("\n"), len(text.rstrip("\n"))


def _text_box_marker_runs(
    blob: bytes, marker: bytes, text_len: int, start: int = OBJECT_BASE_HEADER_LEN
) -> list[tuple[int, int, int, int]]:
    """All local `(start, end, value, enabled)` TLV runs for a text-box object.

    Text-box styling lives INSIDE the page object blob, immediately after the box text itself,
    but uses the same TLV shape as note.note's typed text: `18 00 <tag> 00 | pad | u32 start |
    u32 end | u32 value | u32 enabled`, with offsets local to the box's own text. Verified on
    samples/OnlyTextTypeWritten_260701_180427.sdocx page a48f4f92: object 2 carries a font run
    + default-color run over 0..82, plus bold 37..47 and italic 52..59 / 79..81 right after the
    decoded UTF-16LE text payload.
    """
    runs = []
    off = blob.find(marker, start)
    while off != -1:
        if off + RUN_MARKER_LEN <= len(blob) and blob[off + 4 : off + 6] == b"\x00\x00":
            start_idx = struct.unpack_from("<I", blob, off + RUN_START_OFF)[0]
            end_idx = struct.unpack_from("<I", blob, off + RUN_END_OFF)[0]
            value = struct.unpack_from("<I", blob, off + RUN_VALUE_OFF)[0]
            enabled = struct.unpack_from("<I", blob, off + RUN_ENABLED_OFF)[0]
            if start_idx < end_idx <= text_len:
                runs.append((start_idx, end_idx, value, enabled))
        off = blob.find(marker, off + 1)
    return runs


def _text_box_style_runs(blob: bytes, tag: int, text_len: int, start: int) -> list[tuple[int, int, int, int]]:
    marker = STYLE_MARKER_PREFIX + bytes([tag & 0xFF, tag >> 8])
    return _text_box_marker_runs(blob, marker, text_len, start)


def _text_box_rich_text(blob: bytes) -> dict | None:
    parsed = _text_box_text(blob)
    if parsed is None:
        return None
    text_off, text, raw_text_len = parsed
    lead_trim = 0
    text_len = len(text)
    scan_start = text_off + raw_text_len * 2

    def rebase(start: int, end: int) -> tuple[int, int] | None:
        s, e = start - lead_trim, end - lead_trim
        e = min(e, text_len)
        if e <= 0 or s >= text_len or s >= e:
            return None
        return max(s, 0), e

    runs: list[dict] = []
    for tag, key in ((BOLD_TAG, "bold"), (ITALIC_TAG, "italic"), (UNDERLINE_TAG, "underline")):
        for start, end, _value, enabled in _text_box_style_runs(blob, tag, raw_text_len, scan_start):
            if enabled:
                rb = rebase(start, end)
                if rb is not None:
                    runs.append({"start": rb[0], "end": rb[1], "style": key})

    strike_runs = _text_box_marker_runs(blob, STRIKETHROUGH_MARKER, raw_text_len, scan_start)
    strike_starts = {s for s, _e, _v, en in strike_runs if en in (0, 1)}
    for start, end, _value, enabled in strike_runs:
        if enabled == 1 and end in strike_starts:
            rb = rebase(start, end)
            if rb is not None:
                runs.append({"start": rb[0], "end": rb[1], "style": "strikethrough"})

    colors: list[dict] = []
    for start, end, _value, enabled in _text_box_style_runs(blob, COLOR_TAG, raw_text_len, scan_start):
        argb = enabled
        if (argb >> 24) == 0xFF:
            rb = rebase(start, end)
            if rb is not None:
                colors.append({
                    "start": rb[0],
                    "end": rb[1],
                    "color": ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF),
                })

    highlights: list[dict] = []
    for start, end, _value, enabled in _text_box_style_runs(blob, HIGHLIGHT_TAG, raw_text_len, scan_start):
        argb = enabled
        if (argb >> 24) == 0xFF:
            rb = rebase(start, end)
            if rb is not None:
                highlights.append({
                    "start": rb[0],
                    "end": rb[1],
                    "color": ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF),
                })

    font_size = None
    font_sizes: list[dict] = []
    font_runs = _text_box_style_runs(blob, FONT_TAG, raw_text_len, scan_start)
    for start, end, _value, enabled in font_runs:
        raw_f = struct.pack("<I", enabled)
        candidate = struct.unpack("<f", raw_f)[0]
        rb = rebase(start, end)
        if rb is not None and candidate == candidate and 4.0 <= candidate <= 200.0:
            font_sizes.append({"start": rb[0], "end": rb[1], "font_size": candidate})
            if font_size is None:
                font_size = candidate

    return {
        "text": text,
        "text_off": text_off,
        "runs": runs,
        "colors": colors,
        "highlights": highlights,
        "font_size": font_size,
        "font_sizes": font_sizes,
    }


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


def _decode_header_ext(blob: bytes, field_flags: int) -> dict | None:
    """Decode the 16-byte header extension gated by FIELD_FLAG_HDR_EXT (0x40000).

    Layout `[u32 counter][u32 seq][u32 page_width][u32 page_height]`. The trailing width/height match
    the page header on every object that carries the block (1690/1690 in the corpus), which is what
    validates the decode. `seq` and `counter` semantics are NOT settled: `seq` is a small value (~415072..
    415139) that is near-constant WITHIN a note (e.g. 579 objects spanning a spread of 1) and only bumps
    occasionally, so it reads as a save-time/session/app-global counter, NOT a per-object counter; `counter`
    repeats within a file (e.g. 200 objects, 152 unique), so it is NOT a unique per-object id. Both are
    exposed raw pending a firmer characterization (see docs/format/container/page/object-header.md). If an extra_key
    block (0x20) is present, it is stored first and shifts this extension by 32 bytes.
    """
    if not (field_flags & FIELD_FLAG_HDR_EXT):
        return None
    start = OBJECT_BASE_HEADER_LEN + (4 if field_flags & FIELD_FLAG_ANGLE else 0)
    if field_flags & FIELD_FLAG_EXTRA_KEY:
        start += EXTRA_KEY_BLOCK_LEN
    if start + HDR_EXT_LEN > len(blob):
        return None
    counter, seq, page_width, page_height = struct.unpack_from("<4I", blob, start)
    return {
        "off": start,
        "counter": counter,
        "seq": seq,
        "page_width": page_width,
        "page_height": page_height,
    }


def _decode_extra_key_block(blob: bytes, field_flags: int) -> dict | None:
    """Decode the 32-byte named attribute block gated by FIELD_FLAG_EXTRA_KEY (0x20).

    Confirmed on all 40 objects that set the bit: the block starts at the common attributes
    offset, after the optional rotation f32, and contains `02 01 00`, a u16 byte length, the
    NUL-terminated ASCII key `extra_key_stroke_shape`, and a trailing u32 that is always 1 in
    the current corpus. The trailing value is exposed raw because flag-vs-count semantics are
    still unresolved.
    """
    if not (field_flags & FIELD_FLAG_EXTRA_KEY):
        return None
    start = OBJECT_BASE_HEADER_LEN + (4 if field_flags & FIELD_FLAG_ANGLE else 0)
    if start + EXTRA_KEY_BLOCK_LEN > len(blob):
        return None

    head = blob[start : start + 3]
    key_len = struct.unpack_from("<H", blob, start + 3)[0]
    key_start = start + 5
    key_end = key_start + key_len
    trailing_off = start + 28
    if key_end > len(blob) or trailing_off + 4 > len(blob):
        return None

    raw_key = blob[key_start:key_end]
    key = raw_key.rstrip(b"\x00").decode("ascii", errors="replace")
    trailing = struct.unpack_from("<I", blob, trailing_off)[0]
    return {
        "off": start,
        "head": head.hex(),
        "head_ok": head == b"\x02\x01\x00",
        "key_len": key_len,
        "key": key,
        "trailing": trailing,
    }


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
            "ext_block": _decode_header_ext(blob, field_flags),
            "extra_key_block": _decode_extra_key_block(blob, field_flags),
        }
    except (IndexError, struct.error):
        return None


# field_flags bits mapped to a decoded feature name; see the FIELD_FLAG_* comment block above for the
# corpus evidence behind each. Any bit NOT listed here is surfaced as an explicit unknown so we never
# silently imply we understand it.
_FIELD_FLAG_FEATURES = (
    (FIELD_FLAG_ANGLE, "rotation_angle_f32_at_105"),
    (FIELD_FLAG_EXTRA_KEY, "extra_key_stroke_shape"),
    (FIELD_FLAG_MEDIA_FAMILY, "media_shape_family"),
    (FIELD_FLAG_HDR_EXT, "header_ext_16b"),
)
_FIELD_FLAG_KNOWN_MASK = FIELD_FLAG_BASE_PRESENT
for _bit, _name in _FIELD_FLAG_FEATURES:
    _FIELD_FLAG_KNOWN_MASK |= _bit


def _object_header_profile(raw_type: int, obj_type: str, header: dict | None) -> dict | None:
    """Summarize the common object-header variant, separating decoded facts from guesses.

    The `(total_size, field_flags)` signature is stable across the current sample corpus, and every
    field_flags bit observed there now has a decoded meaning (see `_FIELD_FLAG_FEATURES` and the
    FIELD_FLAG_* constants). Any bit we have NOT explained is still surfaced in `unknown_bits`, so a
    new corpus that sets a novel bit shows up immediately instead of being silently absorbed.
    """
    if header is None:
        return None

    field_flags = header["field_flags"]
    known_features = [name for bit, name in _FIELD_FLAG_FEATURES if field_flags & bit]
    if field_flags & FIELD_FLAG_BASE_PRESENT:
        known_features.append("base_present_bits")
    unknown_bits = [
        f"0x{1 << i:x}"
        for i in range(field_flags.bit_length())
        if (field_flags & (1 << i)) and not (_FIELD_FLAG_KNOWN_MASK & (1 << i))
    ]

    family = "base"
    if header["total_size"] > STROKE_OBJECT_BASE_TOTAL_SIZE or (field_flags & FIELD_FLAG_HDR_EXT):
        family = "extended"
    if field_flags & FIELD_FLAG_ANGLE:
        family += "_rotated"

    return {
        "signature": f"{header['total_size']}/0x{field_flags:x}",
        "family": family,
        "raw_type": raw_type,
        "object_type": obj_type,
        "known_features": known_features,
        "unknown_bits": unknown_bits,
    }


def _decode_payload_geometry(blob: bytes, header: dict | None) -> dict | None:
    """Decode the inserted-object geometry wrapper after the common object header."""
    if header is None:
        return None
    start = header["total_size"]
    if start + PAYLOAD_GEOMETRY_HEADER_LEN > len(blob):
        return None

    l0 = _read_u32(blob, start)
    tag = _read_u16(blob, start + 4)
    l1 = _read_u32(blob, start + 6)
    if l0 is None or tag != PAYLOAD_GEOMETRY_TAG or l1 is None:
        return None
    if blob[start + 10 : start + 14] != PAYLOAD_GEOMETRY_OPCODE:
        return None
    point_count = _read_u32(blob, start + 14)
    if point_count is None or not (PAYLOAD_GEOMETRY_MIN_POINTS <= point_count <= PAYLOAD_GEOMETRY_MAX_POINTS):
        return None

    points_start = start + PAYLOAD_GEOMETRY_HEADER_LEN
    points_end = points_start + point_count * 16
    if points_end > len(blob):
        return None

    points = []
    for idx in range(point_count):
        x = _read_f64(blob, points_start + idx * 16)
        y = _read_f64(blob, points_start + idx * 16 + 8)
        if x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
            return None
        points.append((x, y))

    bbox = header.get("bbox")
    centroid = (
        sum(x for x, _y in points) / len(points),
        sum(y for _x, y in points) / len(points),
    )
    bbox_centroid_match = None
    if bbox is not None and len(points) >= 2 and all(math.isfinite(v) for v in bbox):
        bx = (bbox[0] + bbox[2]) / 2.0
        by = (bbox[1] + bbox[3]) / 2.0
        bbox_centroid_match = abs(centroid[0] - bx) <= 1.0 and abs(centroid[1] - by) <= 1.0

    markers: dict[str, dict] = {}
    for name, marker in (
        ("shape", SHAPE_TYPE_MARKER),
        ("image", IMAGE_MARKER),
    ):
        rel = blob.find(marker, start)
        if rel >= 0:
            markers[name] = {
                "rel": rel,
                "l0_delta": rel - (start + l0 + PAYLOAD_GEOMETRY_MARKER_L0_DELTA),
                "l1_delta": rel - (start + l1 + PAYLOAD_GEOMETRY_MARKER_L1_DELTA),
            }

    text = _text_from_marker(blob)
    if text is not None:
        marker_rel = text[0] - TEXT_BOX_TEXT_MARKER_LEN
        markers["text"] = {
            "rel": marker_rel,
            "l0_delta": marker_rel - (start + l0 + PAYLOAD_GEOMETRY_MARKER_L0_DELTA),
            "l1_delta": marker_rel - (start + l1 + PAYLOAD_GEOMETRY_TEXT_MARKER_L1_DELTA),
        }

    return {
        "off": start,
        "l0": l0,
        "tag": tag,
        "l1": l1,
        "point_count": point_count,
        "points_off": points_start,
        "points": points,
        "centroid": centroid,
        "bbox_centroid_match": bbox_centroid_match,
        "markers": markers,
    }


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
        obj["header_profile"] = _object_header_profile(raw_type, obj["type"], header)
        obj["payload_geometry"] = _decode_payload_geometry(blob, header)
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
    result = {"id": template_id, "kind": kind, "source": source}
    if kind == "grid":
        result["spacing"] = GRID_SPACING_BY_ID.get(template_id, GRID_SPACING)
    return result


# A .page file ends with a 32-byte content hash immediately followed by the ASCII signature
# "Page for SAMSUNG S-Pen SDK" (26 bytes) — the per-page analog of end_tag.bin's
# "Document for S-Pen SDK". This 32-byte hash is what pageIdInfo.dat copies into its per-page
# record (`page_hash`), which is why that manifest hash is not a digest of the raw .page member:
# it is this stored footer hash, mirrored. Anchored to the signature so it is robust to the file
# length. Confirmed on all 48 corpus pages (hash at data[-58:-26], signature at data[-26:]).
PAGE_FOOTER_SIGNATURE = b"Page for SAMSUNG S-Pen SDK"


def page_background_color(data: bytes) -> tuple[int, int, int] | None:
    """Decode the page's stored paper (background) color from the `.page` header.

    RE-validated (2026-07-09, `samples/test-background/` one-variable samples): the paper color is
    a `BGRA` quad (alpha == 0xFF) inside the record `[u32 kind][BGRA][u32 display_width]` — `kind`
    is 2 (3 on some devices), `display_width` is the device paper width. Its absolute offset varies
    with a variable-length header preamble (0x84 / 0xa4 / 0x13e / 0x15e seen), so it is located by
    that signature within `[0x7c, base)`, not a fixed offset. Exactly one match on all 122 pages of
    the corpus + the 4 background samples (the `Rosina` pink `(245,221,221)` pins the field). Unlike
    `bg_color_from_note` (which is empty on the corpus), this is the authoritative paper source.
    """
    if len(data) < 4:
        return None
    base = struct.unpack_from("<I", data, 0)[0]
    hi = min(base, len(data) - 8)
    for off in range(0x7C, hi):
        if data[off + 3] != 0xFF:
            continue
        kind = struct.unpack_from("<I", data, off - 4)[0]
        width = struct.unpack_from("<I", data, off + 4)[0]
        if 1 <= kind <= 8 and 256 <= width <= 40000:
            return (data[off + 2], data[off + 1], data[off])
    return None


def parse_page_footer(data: bytes) -> dict | None:
    """Decode the .page footer: the 32-byte content hash + trailing SDK signature.

    Returns `{signature, valid_signature, page_hash, hash_off}` where `page_hash` is the hex
    digest that pageIdInfo.dat stores for this page. Anchored to PAGE_FOOTER_SIGNATURE at EOF.
    """
    sig_off = data.rfind(PAGE_FOOTER_SIGNATURE)
    if sig_off < 0 or sig_off < 32:
        return None
    hash_off = sig_off - 32
    return {
        "signature": data[sig_off:].decode("ascii", errors="replace"),
        "valid_signature": data[sig_off:] == PAGE_FOOTER_SIGNATURE,
        "page_hash": data[hash_off:sig_off].hex(),
        "hash_off": hash_off,
    }


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
        "footer": parse_page_footer(data),
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
        "attachment_placements": scan_attachment_placements(data, width, height),
        "sticky_notes": scan_sticky_notes(data, width, height),
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


def _image_rotation_deg(header: dict | None, blob: bytes) -> float:
    """Rotation angle in degrees (clockwise-positive on screen, 0..360) for an image object.

    See IMAGE_ANGLE_OFFSET/IMAGE_ANGLE_FIELD_FLAG above. Only trust the f32 when the header's
    field_flags actually carries the "rotation present" bit — otherwise that offset just lands
    in unrelated fixed fields (timestamp/resizable) and returning 0.0 is correct."""
    if header is None or not (header["field_flags"] & IMAGE_ANGLE_FIELD_FLAG):
        return 0.0
    if IMAGE_ANGLE_OFFSET + 4 > len(blob):
        return 0.0
    angle = struct.unpack_from("<f", blob, IMAGE_ANGLE_OFFSET)[0]
    if not math.isfinite(angle):
        return 0.0
    return angle % 360.0


def scan_images_from_objects(data: bytes, width: int, height: int, layers: list[dict]) -> list[dict]:
    """Find imported-image placements inside parsed object blobs."""
    images: list[dict] = []
    for layer in layers:
        for obj in _iter_objects(layer["objects"]):
            if obj["type"] != "image":
                continue
            blob = data[obj["blob_off"] : obj["end"]]
            angle_deg = _image_rotation_deg(obj["header"], blob)
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
                        "angle_deg": angle_deg,
                        "payload_geometry": obj.get("payload_geometry"),
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
    """Extract in-page text boxes with their local rich-text runs.

    Unlike the document-wide typed text in note.note, these live directly in each page object
    blob. The text itself uses the `06 00 <u16 kind> 00 00 <u32 char_count>` marker, while style
    runs immediately after it reuse the same local TLV families as note.note (`18 00 <tag> 00`
    and, if ever present, `14 00 14 00` for strikethrough). This is text/object styling only;
    paragraph metadata such as numbered/bulleted/todo prefixes, checked-state and alignment lives
    in note.note's paragraph-indexed records (see pysdocx.note), not in these page object blobs.
    """
    text_boxes: list[dict] = []
    for layer in layers:
        for obj in _iter_objects(layer["objects"]):
            if obj["type"] != "text_box":
                continue
            blob = data[obj["blob_off"] : obj["end"]]
            parsed = _text_box_rich_text(blob)
            if parsed is None:
                continue
            text_boxes.append({
                **parsed,
                "text_off": obj["blob_off"] + parsed["text_off"],
                "bbox": obj["bbox"],
                "angle_deg": _image_rotation_deg(obj["header"], blob),
                "frame_midpoints": _text_box_frame_midpoints(obj, blob),
                "payload_geometry": obj.get("payload_geometry"),
                "object_idx": obj["idx"],
                "object_off": obj["off"],
            })
    return text_boxes


def _text_box_frame_midpoints(obj: dict, blob: bytes) -> list[tuple[float, float]] | None:
    """Candidate 4 edge-midpoints of a rotated text-box frame.

    On the `_squared` sample's rotated text boxes (16° and 90°), the object payload region right
    after the common header contains 4 `(x, y)` pairs as little-endian f64 values starting at
    `header["total_size"] + 0x12`. Their centroid matches the decoded bbox center exactly, and
    their radii match `bbox_h/2` and `bbox_w/2`, which strongly suggests these are the frame's
    stored edge-midpoints. The plain horizontal box lacks this longer rotated-object payload.

    This is still reverse-engineered structure, not yet a fully-explained semantic field, so we
    expose it only when the geometry is self-consistent with the decoded bbox.
    """
    header = obj.get("header")
    bbox = obj.get("bbox")
    geometry = obj.get("payload_geometry")
    if geometry and geometry.get("point_count") == 4:
        pts = geometry["points"]
        if bbox is not None and _points_centroid_matches_bbox(pts, bbox):
            return pts

    if header is None or bbox is None or header["total_size"] + 0x12 + 8 * 8 > len(blob):
        return None
    if not (header.get("field_flags", 0) & IMAGE_ANGLE_FIELD_FLAG):
        return None

    start = header["total_size"] + 0x12
    pts = []
    for i in range(4):
        x = struct.unpack_from("<d", blob, start + i * 16)[0]
        y = struct.unpack_from("<d", blob, start + i * 16 + 8)[0]
        pts.append((x, y))
    if not all(math.isfinite(v) for pt in pts for v in pt):
        return None

    x0, y0, x1, y1 = bbox
    cx = sum(x for x, _y in pts) / 4.0
    cy = sum(y for _x, y in pts) / 4.0
    bbox_cx = (x0 + x1) / 2.0
    bbox_cy = (y0 + y1) / 2.0
    if abs(cx - bbox_cx) > 1.0 or abs(cy - bbox_cy) > 1.0:
        return None

    return pts


def _points_centroid_matches_bbox(
    points: list[tuple[float, float]],
    bbox: tuple[float, float, float, float],
    tolerance: float = 1.0,
) -> bool:
    if not points or not all(math.isfinite(v) for pt in points for v in pt):
        return False
    if not all(math.isfinite(v) for v in bbox):
        return False
    x0, y0, x1, y1 = bbox
    cx = sum(x for x, _y in points) / len(points)
    cy = sum(y for _x, y in points) / len(points)
    return abs(cx - (x0 + x1) / 2.0) <= tolerance and abs(cy - (y0 + y1) / 2.0) <= tolerance


def _read_len_prefixed_ascii(data: bytes, offset: int) -> tuple[str, int] | None:
    """`<u32 length><ascii bytes>` at `offset`; returns `(text, end_offset)` or None."""
    if offset + 4 > len(data):
        return None
    length = struct.unpack_from("<I", data, offset)[0]
    start = offset + 4
    end = start + length
    if not (0 < length < 1000) or end > len(data):
        return None
    try:
        return data[start:end].decode("ascii"), end
    except UnicodeDecodeError:
        return None


def _parse_attachment_bbox(text: str, width: int, height: int) -> tuple[float, float, float, float] | None:
    parts = text.split(",")
    if len(parts) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in parts)
    except ValueError:
        return None
    bbox = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    if not (
        all(math.isfinite(v) for v in bbox)
        and -5 <= bbox[0] < bbox[2] <= width + 5
        and -5 <= bbox[1] < bbox[3] <= height + 5
    ):
        return None
    return bbox


def _scan_attachment_property_bag(data: bytes, marker_off: int, width: int, height: int) -> dict | None:
    """Decode one whole-page attachment property bag anchored by `co_attach_file`.

    These records are still discovered by marker because they live outside the declared page
    object count, but once found we parse them as a structured sequence of keys/values instead of
    only extracting the sticky-note rectangle.
    """
    if marker_off < 4 or struct.unpack_from("<I", data, marker_off - 4)[0] != len(STICKY_NOTE_MARKER):
        return None

    bag_off = marker_off - 4
    pos = bag_off
    end_limit = min(len(data), bag_off + ATTACHMENT_PROPERTY_BAG_MAX_SCAN)
    keys: list[str] = []
    properties: dict[str, object] = {}
    media_index = None
    attach_type_tag = None
    bbox = None

    for _ in range(ATTACHMENT_PROPERTY_BAG_MAX_KEYS):
        result = _read_len_prefixed_ascii(data, pos)
        if result is None:
            break
        key, pos = result
        if not re.fullmatch(r"[A-Za-z0-9_]{2,64}", key):
            break
        keys.append(key)

        if key == STICKY_NOTE_MARKER.decode("ascii"):
            if pos + 8 > end_limit:
                return None
            media_index = struct.unpack_from("<I", data, pos)[0]
            attach_type_tag = struct.unpack_from("<I", data, pos + 4)[0]
            properties[key] = {"media_index": media_index, "type_tag": attach_type_tag}
            pos += 8
        else:
            value = _read_len_prefixed_ascii(data, pos)
            if value is None:
                break
            text, pos = value
            properties[key] = text
            if key == STICKY_NOTE_RECT_KEY.decode("ascii"):
                bbox = _parse_attachment_bbox(text, width, height)

        if pos + 4 > end_limit:
            break

    if media_index is None:
        return None

    kind = "sticky_note" if any(key.startswith("skn_") for key in keys) else "attachment"
    return {
        "kind": kind,
        "media_index": media_index,
        "type_tag": attach_type_tag,
        "bbox": bbox,
        "keys": keys,
        "properties": properties,
        "bag_off": bag_off,
        "off": marker_off,
        "end": pos,
    }


def scan_attachment_placements(data: bytes, width: int, height: int) -> list[dict]:
    """Find page-level attachment property bags outside the declared object tree.

    Confirmed today for sticky-note placements. Audio remains only a document-level attachment plus
    note.note metadata in the current corpus, so lack of an audio placement here is expected.
    """
    placements: list[dict] = []
    off = 0
    while True:
        i = data.find(STICKY_NOTE_MARKER, off)
        if i < 0:
            break
        off = i + 1
        placement = _scan_attachment_property_bag(data, i, width, height)
        if placement is not None:
            placements.append(placement)
    return placements


def scan_sticky_notes(data: bytes, width: int, height: int) -> list[dict]:
    """Find sticky-note (file-attachment) placements: `{media_index, bbox, off}`.

    Whole-page marker scan (not object-tree based) — see STICKY_NOTE_MARKER's comment for why:
    the layer's own declared object_count excludes these, so the normal tree walk never reaches
    them (same situation as markerless arrows, see scan_arrows)."""
    notes: list[dict] = []
    for placement in scan_attachment_placements(data, width, height):
        if placement["kind"] != "sticky_note" or placement["bbox"] is None:
            continue
        notes.append({
            "media_index": placement["media_index"],
            "bbox": placement["bbox"],
            "off": placement["off"],
        })
    return notes


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

    # `outline_ops` keeps the raw (tag, points) segments alongside the flattened
    # `points` polyline — the renderer can then draw a true Bezier for shapes whose
    # path has a real CubicBezierTo segment (heart, freeform_smooth) instead of a
    # fixed-resolution sampled approximation, while every existing `points` consumer
    # (closed-test, bbox, the shapes.rs Rust parity fixture) is untouched.
    outline_ops = None
    if type_code in DEGENERATE_OUTLINE_TYPES:
        points = _read_vertex_list(data, marker, width, height)
    else:
        segments = decode_outline(data, marker + SHAPE_OUTLINE_OFFSET, width, height)
        points = flatten_outline(segments)
        if len(points) < 3:  # not a usable outline — try the vertex list
            points = _read_vertex_list(data, marker, width, height)
        else:
            outline_ops = segments
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
        "outline_ops": outline_ops,
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


def _shape_payload_geometry_role(shape: dict, geometry: dict | None) -> str | None:
    if not geometry:
        return None
    if shape.get("type") == "arrow":
        return "shaft_endpoints"
    type_code = shape.get("type_code")
    if type_code in SHAPE_PAYLOAD_GEOMETRY_ROLES:
        return SHAPE_PAYLOAD_GEOMETRY_ROLES[type_code]
    return "unknown"


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
                shape["payload_geometry"] = obj.get("payload_geometry")
                shape["payload_geometry_role"] = _shape_payload_geometry_role(shape, obj.get("payload_geometry"))
                shapes.append(shape)
                found_marker_shape = True
            if found_marker_shape:
                continue
            arrow = _parse_arrow_object(data, obj["blob_off"], obj["end"], width, height)
            if arrow is not None:
                arrow["object_idx"] = obj["idx"]
                arrow["object_off"] = obj["off"]
                arrow["payload_geometry"] = obj.get("payload_geometry")
                arrow["payload_geometry_role"] = _shape_payload_geometry_role(arrow, obj.get("payload_geometry"))
                shapes.append(arrow)
    return shapes
