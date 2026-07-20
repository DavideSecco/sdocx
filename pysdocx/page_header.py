"""Structural (sequential) parser for the `.page` header's field-flags region.

Mirrors `pysdocx/note_doc.py`'s approach for `note.note`: unlike the rest of
`pysdocx/page.py` (which locates the layer/object tree, background color, and
templates by marker/signature scanning), this module parses the page HEADER
— bytes `0 .. page_end_offset` (aka `base`, where the layer/object tree
starts) — as one sequential structure:

    [u32 page_end_offset]      (relative to header start == absolute, base==0)
    [u32 flex_offset]
    [property_flags: u8 n_bytes + n-byte little-endian bitfield]  (bit 0 = is_text_only)
    [field_flags:    u8 n_bytes + n-byte little-endian bitfield]
    [u32 orientation][u32 width][u32 height][u32 offset_x][u32 offset_y]
    [short-utf16 uuid][i64 modified_time_us][u32 format_version]
    [u32 min_format_version]
    then flex fields gated by field_flags bits (in bit order), starting
    exactly at flex_offset:
      0 drawn_rect          1 tags                2 template_uri
      3 background_image_id 4 background_image_mode
      5 background_colour   6 background_width     7 background_rotation
      8 pdf_data_items      9 template_type         10 canvas_cache_map
      11 imported_data_height  12 theme
      15 recognised_data_modified_time  16 stroke_recognition_data
      18 custom_objects
    then the layer/object tree at page_end_offset (see `pysdocx/page.py`).

The positional gate is strong: the field-flags region must consume exactly
`page_end_offset - flex_offset` bytes, landing exactly where
`pysdocx.page.parse_page_tree` starts reading. Validated with zero
counterexamples on the full local corpus (226/226 pages,
`spec/tools/validate_page_header.py`).

This also explains three things `pysdocx/page.py` previously found by
signature/heuristic scan, all now redundant with a direct field read
(agreement confirmed corpus-wide before this module was written):
`page_background_color` (== `background_colour`, 226/226), the "Basic"
template id (== `template_type`, id-for-id on every case both mechanisms
detect), and `page_custom_template_uri` (== `template_uri`, and cleaner: the
heuristic occasionally over-reads one leading UTF-16 code unit). It also finds
data the heuristics missed entirely: multi-entry `pdf_data_items` on
pageless/tiled PDF imports (`samples/cs61bl_su22`, 20 tiles, one per page
depending on width) and `custom_objects`' `skn_bg_color` field (sticky-note
background color, never extracted before).

Field names cross-referenced from squ1dd13/sdocx2pdf (MIT) — `sdocx/src/page.rs`,
`sdocx/src/page/header.rs` — used as independent evidence and re-validated
field-by-field on the local corpus before adoption here, following the same
process as `pysdocx/note_doc.py` (see `docs/format/xref-sdocx2pdf.md`).
"""
from __future__ import annotations

import struct

FIELD_NAMES = {
    0: "drawn_rect", 1: "tags", 2: "template_uri", 3: "background_image_id",
    4: "background_image_mode", 5: "background_colour", 6: "background_width",
    7: "background_rotation", 8: "pdf_data_items", 9: "template_type",
    10: "canvas_cache_map", 11: "imported_data_height", 12: "theme",
    15: "recognised_data_modified_time", 16: "stroke_recognition_data",
    18: "custom_objects",
}
HANDLED_FIELD_BITS = frozenset(FIELD_NAMES)

BACKGROUND_IMAGE_MODE_NAMES = {0: "centre", 1: "stretch", 2: "fit", 3: "tile"}

# sdocx2pdf's TemplateType enum (their page.rs). ids 1-9/11 are cross-checked id-for-id
# against our own hand-labeled TEMPLATE_NAMES in pysdocx/page.py (samples/AlltypeofPageBasic,
# zero counterexamples). ids 10/12-16 are sdocx2pdf-only names, not yet grounded against a
# hand-labeled sample of our own: treat those five as Marker naming, not Decoded, until we
# capture one (id 12 "custom" does co-occur with our "image" custom-picker template on every
# corpus case, which is a plausible but unconfirmed match — see docs/format/container/page/README.md).
TEMPLATE_TYPE_NAMES = {
    0: "none", 1: "narrow_line", 2: "medium_line", 3: "wide_line",
    4: "narrow_grid", 5: "medium_grid", 6: "wide_grid",
    7: "narrow_dot", 8: "medium_dot", 9: "wide_dot",
    10: "todo", 11: "oxford_paper", 12: "custom", 13: "weekly",
    14: "monthly", 15: "manuscript", 16: "pdf",
}

# sdocx2pdf's CustomObjectType (their page/header.rs). Only id 1 is named; anything else parses
# the same way (uuid + attached_files + custom_data + rect) but is semantically unknown.
CUSTOM_OBJECT_TYPE_NAMES = {1: "sticky_note"}

# CanvasCacheEntry is only decoded when the app's serialized entry size matches what we expect
# (49 bytes: u32 key + 45-byte entry); a mismatched size means a future app version changed the
# struct, so entries are skipped raw rather than misread.
CANVAS_CACHE_ENTRY_SIZE = 49
CANVAS_CACHE_ENTRY_BODY_SIZE = 45  # CANVAS_CACHE_ENTRY_SIZE - 4-byte key


class PageHeaderParseError(Exception):
    """The byte stream violates the sequential page-header structure."""


class _Cur:
    """Bounds-checked little-endian cursor over a bytes window."""

    __slots__ = ("data", "pos", "end")

    def __init__(self, data: bytes, pos: int = 0, end: int | None = None):
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end

    def _need(self, n: int) -> None:
        if self.pos + n > self.end:
            raise PageHeaderParseError(
                f"need {n} bytes at {self.pos}, window ends at {self.end}")

    def bytes_(self, n: int) -> bytes:
        self._need(n)
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int:
        return self.bytes_(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.bytes_(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.bytes_(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.bytes_(4))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self.bytes_(8))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self.bytes_(8))[0]

    def short_utf16(self) -> str:
        n = self.u16()
        return self.bytes_(2 * n).decode("utf-16-le")

    def short_utf8(self) -> str:
        """`[u16 byte_count][utf-8 bytes]` — used for object uuids in this region."""
        n = self.u16()
        return self.bytes_(n).decode("utf-8")

    def long_utf8(self) -> str:
        """`[u32 byte_count][utf-8 bytes]` — used for custom-object map keys/values."""
        n = self.u32()
        return self.bytes_(n).decode("utf-8")

    def bitfield(self) -> tuple[int, int]:
        """`[u8 n_bytes][n-byte little-endian bits]`; returns (bits, n_bytes)."""
        n = self.u8()
        if n > 4:
            raise PageHeaderParseError(f"bitfield size {n} > 4 at {self.pos - 1}")
        return int.from_bytes(self.bytes_(n), "little"), n

    def rect_f64(self) -> tuple[float, float, float, float]:
        return (self.f64(), self.f64(), self.f64(), self.f64())

    def rect_i32(self) -> tuple[int, int, int, int]:
        return (self.i32(), self.i32(), self.i32(), self.i32())

    def sub(self, size: int) -> "_Cur":
        """A sub-window of `size` bytes starting at the current position."""
        self._need(size)
        child = _Cur(self.data, self.pos, self.pos + size)
        self.pos += size
        return child

    @property
    def remaining(self) -> int:
        return self.end - self.pos


def _parse_pdf_data_items(cur: _Cur, format_version: int) -> list[dict]:
    """`bit 8`: embedded-PDF page placements (`sdocx2pdf::page::header::PdfPage`).

    `[u16 count]` then per entry `[u32 file_id][u32 page_index][rect]`, where
    `rect` is 4×f64 if `format_version < 2034` else 4×i32 (both observed
    variants agree with `pysdocx.page.page_pdf_template`'s media/page indices
    on every corpus page where both mechanisms fire; see module docstring).
    """
    count = cur.u16()
    items = []
    for _ in range(count):
        file_id = cur.u32()
        page_index = cur.u32()
        rect = cur.rect_f64() if format_version < 2034 else cur.rect_i32()
        items.append({"file_id": file_id, "page_index": page_index, "rect": rect})
    return items


def _parse_canvas_cache_map(cur: _Cur) -> dict:
    """`bit 10`: `[u32 entry_count][u16 entry_size]` then, iff `entry_size == 49`,
    `entry_count` × `[u32 key][45-byte CanvasCacheEntry]`; otherwise the entries
    are skipped raw (a size mismatch means a newer app struct we don't model)."""
    count = cur.u32()
    entry_size = cur.u16()
    entries = []
    if entry_size == CANVAS_CACHE_ENTRY_SIZE:
        for _ in range(count):
            key = cur.u32()
            body = cur.bytes_(CANVAS_CACHE_ENTRY_BODY_SIZE)
            entries.append({
                "key": key,
                "file_id": struct.unpack_from("<I", body, 0)[0],
                "width": struct.unpack_from("<I", body, 4)[0],
                "height": struct.unpack_from("<I", body, 8)[0],
                "is_dark_mode": body[12] == 1,
                "background_colour": body[13:17].hex(),
                "version": list(struct.unpack_from("<3I", body, 17)),
                "cache_version": struct.unpack_from("<I", body, 29)[0],
                "property": struct.unpack_from("<I", body, 33)[0],
                "locale_list_id": struct.unpack_from("<I", body, 37)[0],
                "system_font_path_hash": struct.unpack_from("<I", body, 41)[0],
            })
    else:
        cur.bytes_(count * entry_size)
    return {"entry_count": count, "entry_size": entry_size, "entries": entries}


def _parse_custom_object(cur: _Cur) -> dict:
    """One `custom_objects` (bit 18) entry: `[u32 object_type][u32 size]<size bytes>`.

    Payload (`sdocx2pdf::page::header::CustomPageObject`): `[u32 reserved==0]
    [property_flags bitfield, expected empty][field_flags bitfield, expected
    empty][short-utf8 uuid][attached_files map<long-utf8 key -> u32 file_id>]
    [custom_data map<long-utf8 key -> long-utf8 value>][rect: 4×f64]`.

    Only `object_type == 1` ("sticky_note") is seen on the corpus. Its
    `custom_data` carries `skn_bg_color` (a signed-int Android ARGB color, as
    a decimal string) and `skn_collapse_rect` (a `"x0,y0,x1,y1"` page-coordinate
    string) — both new, never previously extracted (the marker-scan
    equivalent, `pysdocx.page.scan_attachment_placements`, already surfaced
    `skn_collapse_rect`, but not `skn_bg_color`). NOTE: this entry's own outer
    `rect` field and `custom_data["skn_collapse_rect"]` are two DIFFERENT
    bounding boxes on every observed case — which one is the actual on-page
    icon placement is not yet resolved (needs a targeted ground-truth sample
    with a visible, unambiguous sticky-note icon; see docs/format/unknowns.md).

    Unknown: sdocx2pdf's schema ends at `rect` (`reader.ensure_eof()`), but
    every sticky-note object on our corpus (3/3) carries exactly 8 more
    trailing bytes after it, decoding as two `u32`s both equal to `5303` —
    constant across two unrelated notes/three objects, so plausibly a
    version/build tag added by a newer Samsung Notes build than sdocx2pdf's
    author observed, not a per-object value. Captured as `trailing_raw`
    (never dropped) rather than asserted-empty, so this stays a hard parse
    error only if the byte count itself is ever unexpected.
    """
    object_type = cur.u32()
    size = cur.u32()
    body = cur.sub(size)

    reserved = body.u32()
    property_flags, _ = body.bitfield()
    field_flags, _ = body.bitfield()
    uuid = body.short_utf8()

    attached_count = body.u32()
    attached_files = {}
    for _ in range(attached_count):
        key = body.long_utf8()
        attached_files[key] = body.u32()

    custom_count = body.u32()
    custom_data = {}
    for _ in range(custom_count):
        key = body.long_utf8()
        custom_data[key] = body.long_utf8()

    rect = body.rect_f64()
    trailing_raw = body.bytes_(body.remaining)

    return {
        "object_type": object_type,
        "object_type_name": CUSTOM_OBJECT_TYPE_NAMES.get(object_type),
        "reserved": reserved,
        "property_flags": property_flags,
        "field_flags": field_flags,
        "uuid": uuid,
        "attached_files": attached_files,
        "custom_data": custom_data,
        "rect": rect,
        "trailing_raw": trailing_raw.hex(),
    }


def parse_page_header(data: bytes) -> dict:
    """Parse a `.page` member's header sequentially; raises `PageHeaderParseError`.

    Returns every decoded field plus `header_end_off` (should equal
    `page_end_offset`/`base`, i.e. where the layer/object tree starts) and
    `reaches_page_end` (whether the field-flags region consumed exactly the
    declared span).
    """
    cur = _Cur(data)
    out: dict = {}

    out["page_end_offset"] = cur.u32()
    out["flex_offset"] = cur.u32()
    out["property_flags"], out["property_flags_bytes"] = cur.bitfield()
    out["field_flags"], out["field_flags_bytes"] = cur.bitfield()
    out["orientation"] = cur.u32()
    out["width"] = cur.u32()
    out["height"] = cur.u32()
    out["offset_x"] = cur.u32()
    out["offset_y"] = cur.u32()
    out["uuid"] = cur.short_utf16()
    out["modified_time_us"] = cur.i64()
    out["format_version"] = cur.u32()
    out["min_format_version"] = cur.u32()

    if cur.pos != out["flex_offset"]:
        raise PageHeaderParseError(
            f"fixed header ends at {cur.pos}, flex_offset says {out['flex_offset']}")

    bits = out["field_flags"]
    unhandled = [b for b in range(32) if bits >> b & 1 and b not in HANDLED_FIELD_BITS]
    out["unhandled_field_bits"] = unhandled
    if unhandled:
        raise PageHeaderParseError(f"unhandled field flag bits {unhandled}")

    def present(bit: int) -> bool:
        return bool(bits >> bit & 1)

    fields: dict = {}
    if present(0):
        fields["drawn_rect"] = cur.rect_f64()
    if present(1):
        fields["tags"] = [cur.short_utf16() for _ in range(cur.u16())]
    if present(2):
        fields["template_uri"] = cur.short_utf16()
    if present(3):
        fields["background_image_id"] = cur.i32()
    if present(4):
        mode = cur.u32()
        fields["background_image_mode"] = mode
        fields["background_image_mode_name"] = BACKGROUND_IMAGE_MODE_NAMES.get(mode)
    if present(5):
        fields["background_colour"] = cur.bytes_(4).hex()  # BGRA, alpha == 0xFF
    if present(6):
        fields["background_width"] = cur.u32()
    if present(7):
        fields["background_rotation"] = cur.u32()
    if present(8):
        fields["pdf_data_items"] = _parse_pdf_data_items(cur, out["format_version"])
    if present(9):
        template_type = cur.u32()
        fields["template_type"] = template_type
        fields["template_type_name"] = TEMPLATE_TYPE_NAMES.get(template_type)
    if present(10):
        fields["canvas_cache_map"] = _parse_canvas_cache_map(cur)
    if present(11):
        fields["imported_data_height"] = cur.u32()
    if present(12):
        fields["theme"] = cur.u32()  # sdocx2pdf: "this gets skipped by the libs"
    if present(15):
        fields["recognised_data_modified_time_us"] = cur.i64()
    if present(16):
        count = cur.u32()
        fields["stroke_recognition_data"] = [cur.bytes_(cur.u32()) for _ in range(count)]
    if present(18):
        count = cur.u32()
        fields["custom_objects"] = [_parse_custom_object(cur) for _ in range(count)]

    out["fields"] = fields
    out["header_end_off"] = cur.pos
    out["reaches_page_end"] = cur.pos == out["page_end_offset"]
    return out
