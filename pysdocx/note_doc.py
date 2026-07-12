"""Structural (sequential) parser for the whole `note.note` member.

Unlike `pysdocx.note`, which locates rich text / tables / tail records by
marker scanning, this module parses `note.note` as one sequential structure:

    [u32 flex_offset]
    [property_flags: u8 n_bytes + n-byte little-endian bitfield]
    [field_flags:    u8 n_bytes + n-byte little-endian bitfield]
    [u32 format_version][short-utf16 id][u32 file_revision]
    [i64 created_time_us][i64 modified_time_us]              (epoch MICROseconds)
    [u32 width][u32 height][u32 page_h_padding][u32 page_v_padding]
    [u32 min_format_version]
    [u32 title_size][title Text blob]
    [u32 body_size][body Text blob]
    <gap to flex_offset: 0 or 8 bytes on the corpus; when 8, a u32 pair
     (width, round(width*sqrt(2))) — a default-page-size candidate, Unknown>
    then flex fields gated by field_flags bits (in bit order):
      0 app_name  1 app_version  2 author_info  3 latitude_longitude
      6 template_uri  7 last_edited_page_index
      9 last_edited_page_image_id + last_edited_page_time
      10 string_registry  11 body_text_font_size_delta
      12 compatible_last_pen_info  13 voice_data  14 attached_files
      15 last_pen_info  16 server_check_point  17 fixed_font
      18 fixed_text_direction  19 fixed_background_theme
      20 text_summarisation  21 stroke_group_size  22 app_custom_data
    [32-byte sha256 over everything before it]

The positional gate is strong: the parse must consume bytes
`0 .. len(note)-32` exactly (the trailing 32 bytes are the already-validated
`sha256(note.note[:-32])`), so every intermediate boundary must be correct for
the parse to land on the hash by construction. Validated with zero
counterexamples on the full corpus (`spec/tools/analyze_note_doc.py`).

The title/body blobs are Text objects (a Shape-wrapped object; the wrapper is
not modeled). Inside them, `text_core::Common` frames hold the actual rich
text: `[u32 frame_size(excl)][u32 char_count][utf16 text][u32 span_count ×
span][u32 paragraph_count × paragraph][4×f32 margins][u8 gravity][u16
section_count × (u32,u32)][inline objects if format_version >= 2035]`.
Span records are `[u16 size>=16][u32 span_type][u32 start][u32 end][u32
interval_type][size-16 extra]` — these are exactly the TLV `18 00 <tag> 00`
(size 0x18) and `14 00 14 00` (strikethrough, size 0x14) families that
`pysdocx.note` scans for. Paragraph records are `[u16 size>=12][u32
paragraph_type][u32 start][u32 end][size-12 extra]` — the `14 00 <tag> 00`
(size 0x14) and `1c 00 05 00` (bullet, size 0x1c) families. Table cells are
nested Common frames inside the body frame's inline table object (type 22).

Field names cross-referenced from squ1dd13/sdocx2pdf (MIT) — `note_doc.rs`,
`text_core.rs` — used as independent evidence and re-validated field-by-field
on the local corpus before adoption here.
"""
from __future__ import annotations

import struct

HASH_SIZE = 32
SPAN_BASE_SIZE = 16  # u32 span_type + u32 start + u32 end + u32 interval_type
PARAGRAPH_BASE_SIZE = 12  # u32 paragraph_type + u32 start + u32 end
# Inline objects appear in Common frames only from this format version on
# (sdocx2pdf gate; corpus versions are 4000/5400, both above it).
INLINE_OBJECTS_MIN_FORMAT = 2035

FIELD_NAMES = {
    0: "app_name", 1: "app_version", 2: "author_info", 3: "latitude_longitude",
    6: "template_uri", 7: "last_edited_page_index",
    9: "last_edited_page_image_and_time", 10: "string_registry",
    11: "body_text_font_size_delta", 12: "compatible_last_pen_info",
    13: "voice_data", 14: "attached_files", 15: "last_pen_info",
    16: "server_check_point", 17: "fixed_font", 18: "fixed_text_direction",
    19: "fixed_background_theme", 20: "text_summarisation",
    21: "stroke_group_size", 22: "app_custom_data",
}
HANDLED_FIELD_BITS = frozenset(FIELD_NAMES)

SPAN_TYPE_NAMES = {
    0: "none", 1: "foreground_color", 3: "font_size", 4: "font_name",
    5: "bold", 6: "italic", 7: "underline", 9: "hypertext",
    15: "composing_background_color", 16: "composing", 17: "background_color",
    18: "composing_tag", 19: "timestamp", 20: "strikethrough",
    21: "suggestion", 22: "spell_correction", 23: "formula",
}
# 2..6 named by sdocx2pdf; 8/9/10 are pysdocx-observed on the corpus
# (space-before/space-after floats and the heading/body style).
PARAGRAPH_TYPE_NAMES = {
    2: "indent_level", 3: "align", 4: "line_spacing", 5: "bullet",
    6: "parsing_state", 8: "space_before", 9: "space_after", 10: "style",
}


class NoteDocParseError(Exception):
    """The byte stream violates the sequential note_doc structure."""


class _Cur:
    """Bounds-checked little-endian cursor over a bytes window."""

    __slots__ = ("data", "pos", "end")

    def __init__(self, data: bytes, pos: int = 0, end: int | None = None):
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end

    def _need(self, n: int) -> None:
        if self.pos + n > self.end:
            raise NoteDocParseError(
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

    def f32(self) -> float:
        return struct.unpack("<f", self.bytes_(4))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self.bytes_(8))[0]

    def short_utf16(self) -> str:
        n = self.u16()
        return self.bytes_(2 * n).decode("utf-16-le")

    def long_utf16(self) -> str:
        n = self.u32()
        return self.bytes_(2 * n).decode("utf-16-le")

    def bitfield(self) -> tuple[int, int]:
        """`[u8 n_bytes][n-byte little-endian bits]`; returns (bits, n_bytes)."""
        n = self.u8()
        if n > 4:
            raise NoteDocParseError(f"bitfield size {n} > 4 at {self.pos - 1}")
        return int.from_bytes(self.bytes_(n), "little"), n

    def sub(self, size: int) -> "_Cur":
        """A sub-window of `size` bytes starting at the current position."""
        self._need(size)
        child = _Cur(self.data, self.pos, self.pos + size)
        self.pos += size
        return child

    @property
    def remaining(self) -> int:
        return self.end - self.pos


def _ensure_eof(cur: _Cur, what: str) -> None:
    if cur.remaining != 0:
        raise NoteDocParseError(f"{what}: {cur.remaining} bytes left in window")


def _parse_pen_info_simple(cur: _Cur) -> dict:
    """Un-prefixed pen record (field bit 12, `compatible_last_pen_info`)."""
    return {
        "name": cur.short_utf16(),
        "size": cur.f32(),
        "color": cur.bytes_(4).hex(),
        "is_curvable": cur.u32(),
        "advanced_settings": cur.short_utf16(),
        "is_eraser_enabled": cur.u32(),
        "size_level": cur.u32(),
        "particle_density": cur.u32(),
        "ui_color_hsv": [cur.f32(), cur.f32(), cur.f32()],
        "ui_color_info": cur.u32(),
    }


def _parse_pen_info_full(cur: _Cur) -> dict:
    """Inclusive-length-prefixed pen record (field bit 15, `last_pen_info`)."""
    frame_size = cur.u32()
    if frame_size < 4:
        raise NoteDocParseError(f"pen_info inclusive frame size {frame_size} < 4")
    win = cur.sub(frame_size - 4)
    out = {
        "name": win.short_utf16(),
        "size": win.f32(),
        "color": win.bytes_(4).hex(),
        "is_curvable": win.u32(),
        "advanced_settings": win.short_utf16(),
        "is_eraser_enabled": win.u32(),
        "size_level": win.u32(),
        "particle_density": win.u32(),
        "particle_size": win.f32(),
        "is_fixed_width": win.u32(),
        "ui_color_hsv": [win.f32(), win.f32(), win.f32()],
        "ui_color_info": win.u32(),
    }
    # Late-addition trailing fields, present only when bytes remain (added
    # between mobile-app versions 4.4.33.5 and 4.4.41.9 per sdocx2pdf).
    out["is_fixed_opacity"] = win.u32() if win.remaining >= 4 else None
    out["is_auto_size_enabled"] = win.u32() if win.remaining >= 4 else None
    out["fit_ratio"] = win.f32() if win.remaining >= 4 else None
    _ensure_eof(win, "pen_info_full")
    return out


def _parse_voice_recording(cur: _Cur) -> dict:
    """Exclusive-length-prefixed voice record; `file_id` indexes mediaInfo.dat."""
    size = cur.u32()
    win = cur.sub(size)
    out = {
        "file_id": win.u32(),
        "name": win.short_utf16(),
        "duration_str": win.short_utf16(),
        "created_time_us": win.i64(),
        "events": [],
    }
    event_count = win.u32()
    if event_count > 100_000:
        raise NoteDocParseError(f"voice event count {event_count} implausible")
    for _ in range(event_count):
        # action: 0 none, 1 start, 2 pause, 3 resume, 4 stop (sdocx2pdf names).
        out["events"].append({"action": win.u32(), "time_us": win.i64()})
    out["precise_duration_ms"] = win.i64()
    _ensure_eof(win, "voice_recording")
    return out


def _parse_string_registry(cur: _Cur) -> dict:
    size = cur.u32()
    win = cur.sub(size)
    strings: dict[int, str] = {}
    if size:
        count = win.u16()
        for _ in range(count):
            key = win.u32()
            strings[key] = win.short_utf16()
        _ensure_eof(win, "string_registry")
    return {"byte_size": size, "strings": strings}


def parse_common_frame(blob: bytes, off: int, format_version: int) -> dict:
    """Parse one `text_core::Common` exclusive frame at `off` inside `blob`.

    Raises NoteDocParseError if the bytes at `off` are not a complete,
    exactly-sized Common frame.
    """
    cur = _Cur(blob, off)
    frame_size = cur.u32()
    if frame_size < 4 or off + 4 + frame_size > len(blob):
        raise NoteDocParseError(f"common frame size {frame_size} out of range at {off}")
    win = cur.sub(frame_size)

    char_count = win.u32()
    if char_count > win.remaining // 2:
        raise NoteDocParseError(f"common text char count {char_count} too large")
    text = win.bytes_(2 * char_count).decode("utf-16-le")

    span_count = win.u32()
    if span_count > win.remaining // (2 + SPAN_BASE_SIZE) + 1:
        raise NoteDocParseError(f"span count {span_count} too large")
    spans = []
    for _ in range(span_count):
        size = win.u16()
        if size < SPAN_BASE_SIZE:
            raise NoteDocParseError(f"span record size {size} < {SPAN_BASE_SIZE}")
        spans.append({
            "record_size": size,
            "span_type": win.u32(),
            "start": win.u32(),
            "end": win.u32(),
            "interval_type": win.u32(),
            "extra": win.bytes_(size - SPAN_BASE_SIZE).hex(),
        })

    paragraph_count = win.u32()
    if paragraph_count > win.remaining // (2 + PARAGRAPH_BASE_SIZE) + 1:
        raise NoteDocParseError(f"paragraph count {paragraph_count} too large")
    paragraphs = []
    for _ in range(paragraph_count):
        size = win.u16()
        if size < PARAGRAPH_BASE_SIZE:
            raise NoteDocParseError(f"paragraph record size {size} < {PARAGRAPH_BASE_SIZE}")
        paragraphs.append({
            "record_size": size,
            "paragraph_type": win.u32(),
            "start": win.u32(),
            "end": win.u32(),
            "extra": win.bytes_(size - PARAGRAPH_BASE_SIZE).hex(),
        })

    margins = [win.f32(), win.f32(), win.f32(), win.f32()]
    gravity = win.u8()
    if gravity > 2:  # 0 top, 1 centre, 2 bottom
        raise NoteDocParseError(f"gravity {gravity} not in 0..2")

    section_count = win.u16()
    if section_count > win.remaining // 8:
        raise NoteDocParseError(f"section count {section_count} too large")
    # Semantics Unknown: (start, length)-looking pairs over the text; the last
    # pair often has length 0, empty-text notes carry ((0xffffffff, 1), (0, 0)).
    sections = [(win.u32(), win.u32()) for _ in range(section_count)]

    inline = None
    if format_version >= INLINE_OBJECTS_MIN_FORMAT:
        inline_present = win.u32()
        inline_zero = win.u32()
        inline = {"present": inline_present, "zero_field": inline_zero, "objects": []}
        if inline_present:
            obj_count = win.u32()
            if obj_count > 4096:
                raise NoteDocParseError(f"inline object count {obj_count} implausible")
            for _ in range(obj_count):
                obj_frame = win.u32()
                obj_win = win.sub(obj_frame)
                obj_size = obj_win.u32()
                obj_type = obj_win.u32()
                # The object body consumes exactly obj_size bytes (the type-22
                # table body parses with parse_table_object), then a u32 char
                # position (the U+FFFC anchor index in the frame text), then 8
                # trailing bytes of Unknown semantics (observed (3,2) on
                # tables, (0,0) on images).
                body_off = obj_win.pos
                obj_win.bytes_(obj_size)
                position = obj_win.u32()
                tail = obj_win.bytes_(obj_win.remaining).hex()
                inline["objects"].append({
                    "frame_size": obj_frame,
                    "obj_size": obj_size,
                    "object_type": obj_type,
                    "position": position,
                    "tail_hex": tail,
                    "body_off": body_off,  # offset into `blob`
                })
    _ensure_eof(win, "common frame")

    return {
        "off": off,
        "frame_size": frame_size,
        "char_count": char_count,
        "text": text,
        "spans": spans,
        "paragraphs": paragraphs,
        "margins": margins,
        "gravity": gravity,
        "sections": sections,
        "inline": inline,
    }


def parse_web_inline_object(blob: bytes, off: int, size: int) -> dict:
    """Parse a type-13 Web inline-object body.

    The object is an ObjectBase inclusive frame followed by a type-13
    inclusive frame.  The latter uses the standard variable-length property
    and field bitfields; field bits 0..6 are the Web fields known from
    sdocx2pdf.  The current Samsung 5400 sample additionally sets bit 7 and
    stores one exclusive length-prefixed opaque value, retained without a
    speculative name.
    """
    cur = _Cur(blob, off, off + size)
    base_size = cur.u32()
    if base_size < 4 or off + base_size > cur.end:
        raise NoteDocParseError(f"web ObjectBase size {base_size} out of range")
    base_raw = cur.bytes_(base_size - 4)

    frame_off = cur.pos
    frame_size = cur.u32()
    if frame_size < 15 or frame_off + frame_size != cur.end:
        raise NoteDocParseError(f"web frame size {frame_size} does not consume object")
    win = _Cur(blob, cur.pos, frame_off + frame_size)
    object_type = win.u16()
    if object_type != 13:
        raise NoteDocParseError(f"web object type {object_type} != 13")
    flex_offset = win.u32()

    def bitfield() -> tuple[int, int]:
        n = win.u8()
        if n > 4:
            raise NoteDocParseError(f"web bitfield length {n} > 4")
        raw = win.bytes_(n)
        return int.from_bytes(raw, "little"), n

    property_flags, property_flags_size = bitfield()
    field_flags, field_flags_size = bitfield()
    expected_flex = win.pos - frame_off
    if flex_offset != expected_flex:
        raise NoteDocParseError(
            f"web flex offset {flex_offset} != parsed header {expected_flex}")
    if property_flags:
        raise NoteDocParseError(f"unhandled web property flags 0x{property_flags:x}")

    out = {
        "object_base_size": base_size,
        "object_base_raw": base_raw.hex(),
        "frame_size": frame_size,
        "object_type": object_type,
        "flex_offset": flex_offset,
        "property_flags": property_flags,
        "property_flags_size": property_flags_size,
        "field_flags": field_flags,
        "field_flags_size": field_flags_size,
    }
    if field_flags & 1:
        out["attached_html_file_id"] = win.u32()
    if field_flags & 2:
        out["thumbnail_file_id"] = win.u32()
    if field_flags & 4:
        out["body"] = win.short_utf16()
    if field_flags & 8:
        out["title"] = win.short_utf16()
    if field_flags & 16:
        out["uri"] = win.short_utf16()
    out["image_type_id"] = win.u32()
    if field_flags & 32:
        out["version"] = win.u32()
    if field_flags & 64:
        out["view_type"] = win.u32()
    if field_flags & 128:
        opaque_size = win.u32()
        out["field_7_opaque"] = win.bytes_(opaque_size).hex()
    unhandled = field_flags & ~0xff
    if unhandled:
        raise NoteDocParseError(f"unhandled web field flags 0x{unhandled:x}")
    _ensure_eof(win, "web inline object")
    return out


def find_common_frames(blob: bytes, format_version: int) -> list[dict]:
    """All offsets in `blob` where a complete Common frame parses cleanly.

    The Text/Shape wrapper around the frame is not modeled, so frames are
    located by exhaustive offset scan; the frame's own exact-size constraint
    makes false positives rare. On the corpus this finds exactly the main
    title/body frame plus one nested frame per table cell.
    """
    frames = []
    for off in range(0, max(0, len(blob) - 8)):
        try:
            frames.append(parse_common_frame(blob, off, format_version))
        except (NoteDocParseError, UnicodeDecodeError, struct.error):
            continue
    return frames


# --- type-22 table inline object ------------------------------------------
#
# The body of a type-22 inline object (a table) is itself a sequential
# structure of sized sub-records. Two size conventions coexist: header-style
# records ("self-sized") whose u32 size counts from the size field's own
# offset, and chain records (rows/cells/paths/border blocks) whose u32 size
# counts the bytes *after* the field. Recurring tokens:
#
#   T5     = 01 00 02 00 00            (serialization preamble, Marker)
#   PRE9   = u32 0 + T5
#   TOKEN15= 0f 00 00 00 02 00 00 00 00 00 + T5   (record terminator, Marker)
#
# Object layout (validated byte-exact, zero counterexamples, on every type-22
# object in the corpus — see spec/tools/analyze_note_doc.py):
#
#   wrap      [self-sized] uuid, ts1_us, ts2_us, page-coords bbox, table_index
#   midpoints [self-sized] the 4 edge midpoints of the table rect (text coords)
#   outline   [self-sized] path of the table rect (text coords)
#   content   [self-sized] col widths, n_rows, the row chain, then the style
#             tail (page bbox again, outer-frame border block, per-column
#             width-constraint arrays, max table width, grid-line border
#             block, theme default-fill ARGB)
#   row       [chain] f32 height, u32 row_index, u32 n_cols, the cell chain
#   cell      [chain] u32 col_index, page-coords bbox, then an inner group:
#             wrap (cell uuid, bbox again) + midpoints + outline; the cell's
#             outline record *also* carries the cell's Common frame right
#             after the path, then TOKEN15 closes the cell.
#
# The legacy marker scan's "cell record" `[f64 x][f64 y][u16 6]` is explained
# exactly: (x, y) is the *last path point* (bottom-left corner) of the cell's
# outline, `06` is the path close opcode, `00` a pad byte, and the "kind" that
# follows is the cell frame's own frame_size.

_T5 = bytes.fromhex("0100020000")
_PRE9 = b"\x00\x00\x00\x00" + _T5
_TOKEN15 = bytes.fromhex("0f0000000200000000000100020000")
TABLE_OBJECT_TYPE = 22


def _table_err(what: str, cur: _Cur) -> NoteDocParseError:
    return NoteDocParseError(f"table object: {what} at {cur.pos}")


def _expect(cur: _Cur, cond: bool, what: str) -> None:
    if not cond:
        raise _table_err(what, cur)


def _rect(cur: _Cur) -> tuple[float, float, float, float]:
    return (cur.f64(), cur.f64(), cur.f64(), cur.f64())


def _parse_table_wrap(cur: _Cur, table_level: bool) -> dict:
    """The self-sized wrapper record heading the table and each cell."""
    start = cur.pos
    size = cur.u32()
    _expect(cur, cur.u16() == 0, "wrap pad")
    _expect(cur, cur.u32() == 105, "wrap tag != 105")
    head = cur.bytes_(8).hex()  # u8 + u16 + 5 bytes, semantics Unknown
    version = cur.u32()  # 5400 on tables, 4000 on cells (corpus)
    _expect(cur, cur.u16() == 36, "wrap uuid length != 36")
    uuid = cur.bytes_(36).decode("ascii")
    ts1_us = cur.i64()  # epoch us on the table wrap, 0 on cell wraps
    bbox = _rect(cur)  # page coordinates
    _expect(cur, cur.bytes_(5) == b"\0" * 5, "wrap zeros5")
    out = {"size": size, "head_hex": head, "version": version, "uuid": uuid,
           "ts1_us": ts1_us, "bbox": bbox}
    if table_level:
        out["ts2_us"] = cur.i64()  # epoch us, <= ts1_us on the corpus
    out["page_width"] = cur.u32()  # 1600 on the corpus == note width
    _expect(cur, cur.u32() == 0, "wrap trailing zero")
    if table_level:
        _expect(cur, cur.u8() == 3, "wrap b3 != 3")
        # The 0-based index of the PAGE this table is anchored to — note.note's
        # otherwise-missing table->page reference. (Named rows_minus_1, then
        # table_index; both were coincidences of the old corpus. Proof: the
        # single-table Allsamsungnotes note carries 3 and its table is on page 4;
        # geometry-edited tables sharing a page share the value; it equals the
        # stacked-Y multiplier `page_index * page_height`.) See
        # `table_index_is_page_index`. The field keeps the `table_index` name in
        # the decode layer; the render/placement layer treats it as page index.
        out["table_index"] = cur.u32()
    _expect(cur, cur.pos == start + size, "wrap size mismatch")
    return out


def _parse_table_midpoints(cur: _Cur, cell_level: bool) -> dict:
    """Self-sized record: the 4 edge midpoints of a rect in text coords.

    Cell-level instances carry two extra sub-records of Unknown semantics
    (a 19-byte record whose payload holds a u32 255, and a 16-byte tail
    starting with u32 12).
    """
    start = cur.pos
    size = cur.u32()
    _expect(cur, cur.u16() == 6, "midpoints tag != 6")
    base = cur.u32()  # 0 at table level, 91 at cell level (Unknown semantics)
    _expect(cur, base == (91 if cell_level else 0), "midpoints base")
    _expect(cur, cur.u16() == 1, "midpoints one")
    flags = cur.u16()  # 1 at table level, 0x0c01 at cell level (Unknown)
    npts = cur.u32()
    _expect(cur, npts == 4, "midpoints count != 4")
    pts = [(cur.f64(), cur.f64()) for _ in range(npts)]
    _expect(cur, cur.u32() == 4, "midpoints four")
    _expect(cur, cur.bytes_(5) == b"\0" * 5, "midpoints zeros5")
    out = {"size": size, "flags": flags, "points": pts}
    if cell_level:
        _expect(cur, cur.u32() == 19, "cell rec19 size")
        _expect(cur, cur.bytes_(5) == _T5, "cell rec19 T5")
        out["rec19_hex"] = cur.bytes_(14).hex()  # holds a u32 255 (Unknown)
        tail16 = cur.bytes_(16)
        _expect(cur, tail16 == bytes.fromhex("0c000000") + b"\0" * 12,
                "cell midpoints tail16")
    _expect(cur, cur.pos == start + size, "midpoints size mismatch")
    return out


def _parse_table_path(cur: _Cur) -> list[tuple[float, float]]:
    """Chain-sized path record: u32 n_ops, then opcodes.

    Opcodes: 1 = moveto (f64 x, f64 y), 2 = lineto (f64 x, f64 y),
    6 = closepath (no point). Corpus paths are all closed rectangles.
    """
    size = cur.u32()
    end = cur.pos + size
    n_ops = cur.u32()
    _expect(cur, n_ops <= 4096, "path op count implausible")
    pts = []
    for i in range(n_ops):
        op = cur.u8()
        if op == 6:
            continue
        _expect(cur, op in (1, 2), f"path opcode {op}")
        _expect(cur, (op == 1) == (i == 0), "path moveto position")
        pts.append((cur.f64(), cur.f64()))
    _expect(cur, cur.pos == end, "path size mismatch")
    return pts


def _parse_table_outline(cur: _Cur, cell_level: bool,
                         format_version: int) -> dict:
    """Self-sized outline record: flags, a rect, and the outline path.

    At cell level the record additionally embeds the cell's Common frame
    right after the path (plus a 2-byte 00 02 trailer).
    """
    start = cur.pos
    size = cur.u32()
    _expect(cur, cur.u16() == 7, "outline tag != 7")
    base = cur.u32()  # 0 at table level, 135 at cell level (Unknown semantics)
    _expect(cur, base == (135 if cell_level else 0), "outline base")
    flags = cur.bytes_(7).hex()
    _expect(cur, cur.u32() == 4, "outline four")
    pad_a = cur.bytes_(2).hex()
    rect = _rect(cur)  # (0,0,0,0) on the corpus
    pad_b = cur.bytes_(2).hex()
    pts = _parse_table_path(cur)
    _expect(cur, cur.u8() == 0, "outline pad")
    out = {"size": size, "flags_hex": flags, "rect": rect, "points": pts,
           "pads_hex": pad_a + pad_b}
    if cell_level:
        frame = parse_common_frame(cur.data, cur.pos, format_version)
        cur.pos += 4 + frame["frame_size"]
        _expect(cur, cur.bytes_(2) == b"\x00\x02", "outline frame trailer")
        out["frame"] = frame
    _expect(cur, cur.pos == start + size, "outline size mismatch")
    return out


def _parse_table_borders(cur: _Cur) -> list[dict]:
    """Chain-sized block of 4 border entries: ARGB + (width, radius_x, radius_y).

    Decoded against the Tabella4x3Regolarev2 border family (2026-07-11):
    entries 0/2 are the vertical edges/lines and 1/3 the horizontal ones
    (the two members of each pair have never differed, so left-vs-right and
    top-vs-bottom stay unresolved). A disabled border is fully zeroed
    (argb 00000000, width 0). The two radii are the rounded-corner radii:
    26.0 on the default table frame, 0 on "sharp 90°" frames and on grid
    lines. The first block in the style tail is the table's outer frame,
    the second the inner grid lines.
    """
    size = cur.u32()
    end = cur.pos + size
    _expect(cur, cur.u32() == 0, "borders zero")
    _expect(cur, cur.bytes_(5) == _T5, "borders T5")
    items = [{"argb": cur.u32(), "width": cur.f32(),
              "radius_x": cur.f32(), "radius_y": cur.f32()}
             for _ in range(4)]
    _expect(cur, cur.pos == end, "borders size mismatch")
    return items


def parse_table_object(blob: bytes, off: int, size: int,
                       format_version: int) -> dict:
    """Parse one type-22 table inline object body at `blob[off:off+size]`.

    Raises NoteDocParseError unless the whole body parses byte-exactly.
    """
    cur = _Cur(blob, off, off + size)
    wrap = _parse_table_wrap(cur, table_level=True)
    midpoints = _parse_table_midpoints(cur, cell_level=False)
    outline = _parse_table_outline(cur, cell_level=False,
                                   format_version=format_version)

    content_start = cur.pos
    content_size = cur.u32()
    _expect(cur, content_start + content_size == off + size,
            "content size does not land on object end")
    _expect(cur, cur.u16() == TABLE_OBJECT_TYPE, "content tag != 22")
    _expect(cur, cur.u16() == 15, "content u16 != 15")
    _expect(cur, cur.u16() == 0, "content pad")
    content_head = cur.bytes_(3).hex()  # 01 04 02 on the corpus (Unknown)
    content_u16 = cur.u16()  # 7612 on the corpus (Unknown)
    n_cols = cur.u32()
    _expect(cur, 1 <= n_cols <= 64, "column count implausible")
    col_widths = [cur.f32() for _ in range(n_cols)]
    n_rows = cur.u32()
    _expect(cur, 1 <= n_rows <= 4096, "row count implausible")

    rows = []
    for r in range(n_rows):
        row_size = cur.u32()
        row_end = cur.pos + row_size
        _expect(cur, cur.bytes_(9) == _PRE9, "row preamble")
        height = cur.f32()
        _expect(cur, cur.u32() == r, "row index")
        _expect(cur, cur.u32() == n_cols, "row column count")
        cells = []
        for k in range(n_cols):
            cell_size = cur.u32()
            cell_end = cur.pos + cell_size
            # Cell preamble is `00000000` + a 5-byte `01 <styled> 02 00 00`
            # marker. The 2nd marker byte is 0 on a default cell and 1 on a
            # cell carrying explicit styling (background fill / bold / size /
            # colour / strikethrough), which then shows up as extra spans in
            # the nested Common frame.
            _expect(cur, cur.u32() == 0, "cell preamble zeros")
            _expect(cur, cur.u8() == 1, "cell preamble m0")
            cell_styled = cur.u8()
            _expect(cur, cell_styled in (0, 1), "cell preamble styled flag")
            _expect(cur, cur.bytes_(3) == b"\x02\x00\x00", "cell preamble m2")
            _expect(cur, cur.u32() == k, "cell column index")
            _expect(cur, cur.u32() == 1, "cell one_a")
            _expect(cur, cur.u32() == 1, "cell one_b")
            # Explicit cell background fill as a little-endian 0xAARRGGBB u32.
            # 0 == no fill (the theme default). A manually set cell background
            # ("sfondo" colour) is stored here; the "evidenzia riga/colonna"
            # header highlight instead leaves this 0 and marks the cell via a
            # header-style span set (see the span-type notes below).
            cell_fill_argb = cur.u32()
            bbox = _rect(cur)  # page coordinates
            _expect(cur, cur.u8() == 1, "cell b1")
            inner_size = cur.u32()
            _expect(cur, cur.pos + inner_size == cell_end, "cell inner size")
            cwrap = _parse_table_wrap(cur, table_level=False)
            _expect(cur, cwrap["ts1_us"] == 0, "cell wrap timestamp")
            _expect(cur, cwrap["bbox"] == bbox, "cell wrap bbox mismatch")
            cmid = _parse_table_midpoints(cur, cell_level=True)
            coutline = _parse_table_outline(cur, cell_level=True,
                                            format_version=format_version)
            _expect(cur, cur.bytes_(15) == _TOKEN15, "cell terminator")
            _expect(cur, cur.pos == cell_end, "cell size mismatch")
            cells.append({
                "col": k, "bbox": bbox, "uuid": cwrap["uuid"],
                "version": cwrap["version"], "styled": cell_styled,
                "fill_argb": cell_fill_argb,
                "midpoints": cmid["points"], "outline": coutline["points"],
                "frame": coutline["frame"],
            })
        _expect(cur, cur.pos == row_end, "row size mismatch")
        rows.append({"height": height, "cells": cells})

    tail_bbox = _rect(cur)  # page coordinates
    _expect(cur, tail_bbox == wrap["bbox"], "tail bbox != table bbox")
    # Style tail, decoded against the v2 border family: outer frame border
    # block, per-column width-constraint arrays (291.2 = 1456/5 = min width
    # with the app's 5-column cap, 1456 = max/table width — Marker, values
    # never varied), the max-table-width scalar, the inner grid-line border
    # block, and the theme's default header-fill ARGB.
    outer_borders = _parse_table_borders(cur)
    _expect(cur, cur.u32() == n_cols, "col width min count")
    col_width_min = [cur.f32() for _ in range(n_cols)]
    _expect(cur, cur.u32() == n_cols, "col width max count")
    col_width_max = [cur.f32() for _ in range(n_cols)]
    table_width_max = cur.f32()  # 1456.0 == note width - 2*72 margins
    grid_borders = _parse_table_borders(cur)
    theme_fill_argb = cur.u32()  # 0xffeeebe7: default header/highlight beige
    _ensure_eof(cur, "table object")

    return {
        "uuid": wrap["uuid"], "version": wrap["version"],
        "table_index": wrap["table_index"],
        "ts1_us": wrap["ts1_us"], "ts2_us": wrap["ts2_us"],
        "bbox": wrap["bbox"], "page_width": wrap["page_width"],
        "text_midpoints": midpoints["points"],
        "text_outline": outline["points"],
        "content_head_hex": content_head, "content_u16": content_u16,
        "n_rows": n_rows, "n_cols": n_cols,
        "col_widths": col_widths, "rows": rows,
        "outer_borders": outer_borders, "grid_borders": grid_borders,
        "col_width_min": col_width_min, "col_width_max": col_width_max,
        "table_width_max": table_width_max,
        "theme_fill_argb": theme_fill_argb,
    }


def note_doc_tables(note: bytes, doc: dict) -> list[dict]:
    """Parse every type-22 table object in the note's body frame."""
    frames = note_doc_common_frames(note, doc)
    body = frames["body"]
    if body is None or not body.get("inline"):
        return []
    blob = note[doc["body_off"] : doc["body_off"] + doc["body_size"]]
    tables = []
    for obj in body["inline"]["objects"]:
        if obj["object_type"] != TABLE_OBJECT_TYPE:
            continue
        tables.append(parse_table_object(
            blob, obj["body_off"], obj["obj_size"], doc["format_version"]))
    return tables


def table_index_is_page_index(table: dict) -> int:
    """The 0-based host-page index of a structural table (its `table_index`).

    note.note stores tables document-level with no explicit page reference; the
    wrap `table_index` field IS that reference (see docs tables.md). Thin named
    accessor so render/placement code reads the intent, not the legacy name.
    """
    return table["table_index"]


def note_table_grid(table: dict) -> tuple[list[float], list[float]]:
    """Page-local column/row grid-line coords `(x_edges, y_edges)`.

    Derived from the wrap bbox top-left plus the `col_widths` / per-row heights
    (both sum to the bbox W/H). Page-local for every table — unlike the cell
    bboxes, whose Y is document-stacked on geometry-edited tables.
    """
    x0, y0 = table["bbox"][0], table["bbox"][1]
    x_edges = [x0]
    for w in table["col_widths"]:
        x_edges.append(x_edges[-1] + w)
    y_edges = [y0]
    for row in table["rows"]:
        y_edges.append(y_edges[-1] + row["height"])
    return x_edges, y_edges


def table_cell_style(cell: dict) -> dict:
    """Whole-cell character style resolved from the cell's Common-frame spans.

    A whole-cell run spans `start == 0, end == len(text)`. Maps the `text_core`
    span types: 5 bold / 6 italic / 7 underline / 20 strikethrough (bool value),
    1 foreground_color (ARGB), 3 font_size (f32). Returns render-ready fields;
    `color` is `(r, g, b)` when opaque else None, `font_size` a float or None.
    Every corpus cell carries a default font_size (15.0) and color (ff252525).
    """
    text_len = len(cell["frame"]["text"])
    out = {"bold": False, "italic": False, "underline": False,
           "strikethrough": False, "color": None, "font_size": None}
    for span in cell["frame"]["spans"]:
        if span["start"] != 0 or span["end"] != text_len:
            continue
        raw = bytes.fromhex(span["extra"])
        if len(raw) < 4:
            continue
        value = int.from_bytes(raw[:4], "little")
        st = span["span_type"]
        if st == 5:
            out["bold"] = value != 0
        elif st == 6:
            out["italic"] = value != 0
        elif st == 7:
            out["underline"] = value != 0
        elif st == 20:
            out["strikethrough"] = value != 0
        elif st == 1:
            if value >> 24 == 0xFF:
                out["color"] = ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        elif st == 3:
            out["font_size"] = struct.unpack("<f", raw[:4])[0]
    return out


def parse_note_doc(note: bytes) -> dict:
    """Parse the whole `note.note` sequentially; raises NoteDocParseError.

    The returned dict carries every decoded field plus `landed_on_hash`
    (whether the parse consumed exactly `len(note) - 32` bytes) and the
    title/body blob boundaries for callers that want the Common frames.
    """
    cur = _Cur(note)
    out: dict = {}

    out["flex_offset"] = cur.u32()
    out["property_flags"], out["property_flags_bytes"] = cur.bitfield()
    out["field_flags"], out["field_flags_bytes"] = cur.bitfield()
    out["format_version"] = cur.u32()
    out["id"] = cur.short_utf16()
    out["file_revision"] = cur.u32()
    out["created_time_us"] = cur.i64()
    out["modified_time_us"] = cur.i64()
    out["width"] = cur.u32()
    out["height"] = cur.u32()
    out["page_h_padding"] = cur.u32()
    out["page_v_padding"] = cur.u32()
    out["min_format_version"] = cur.u32()

    out["title_size"] = cur.u32()
    out["title_off"] = cur.pos
    cur.bytes_(out["title_size"])

    out["body_size"] = cur.u32()
    out["body_off"] = cur.pos
    cur.bytes_(out["body_size"])

    gap = out["flex_offset"] - cur.pos
    out["gap_size"] = gap
    out["gap_hex"] = None
    out["gap_u32_pair"] = None
    if gap < 0:
        raise NoteDocParseError(f"overran flex_offset by {-gap} bytes")
    if gap:
        gap_bytes = cur.bytes_(gap)
        out["gap_hex"] = gap_bytes.hex()
        if gap == 8:
            out["gap_u32_pair"] = list(struct.unpack("<II", gap_bytes))

    bits = out["field_flags"]
    unhandled = [b for b in range(32) if bits >> b & 1 and b not in HANDLED_FIELD_BITS]
    out["unhandled_field_bits"] = unhandled
    if unhandled:
        raise NoteDocParseError(f"unhandled field flag bits {unhandled}")

    def present(bit: int) -> bool:
        return bool(bits >> bit & 1)

    fields: dict = {}
    if present(0):
        fields["app_name"] = cur.short_utf16()
    if present(1):
        fields["app_version"] = {
            "major": cur.u32(), "minor": cur.u32(), "patch_name": cur.short_utf16(),
        }
    if present(2):
        fields["author_info"] = {
            "strings": [cur.short_utf16(), cur.short_utf16(), cur.short_utf16()],
            "image_id": cur.u32(),
        }
    if present(3):
        fields["latitude_longitude"] = [cur.f64(), cur.f64()]
    if present(6):
        fields["template_uri"] = cur.short_utf16()
    if present(7):
        fields["last_edited_page_index"] = cur.u32()
    if present(9):
        fields["last_edited_page_image_id"] = cur.i32()
        fields["last_edited_page_time_us"] = cur.i64()
    if present(10):
        fields["string_registry"] = _parse_string_registry(cur)
    if present(11):
        fields["body_text_font_size_delta"] = cur.i32()
    if present(12):
        fields["compatible_last_pen_info"] = _parse_pen_info_simple(cur)
    if present(13):
        count = cur.u32()
        if count > 10_000:
            raise NoteDocParseError(f"voice recording count {count} implausible")
        fields["voice_data"] = [_parse_voice_recording(cur) for _ in range(count)]
    if present(14):
        count = cur.u16()
        fields["attached_files"] = [
            {"name": cur.short_utf16(), "file_id": cur.u32()} for _ in range(count)
        ]
    if present(15):
        fields["last_pen_info"] = _parse_pen_info_full(cur)
    if present(16):
        fields["server_check_point"] = cur.i64()
    if present(17):
        fields["fixed_font"] = cur.short_utf16()
    if present(18):
        fields["fixed_text_direction"] = cur.u32()  # 0 ltr, 1 rtl, 2 default
    if present(19):
        fields["fixed_background_theme"] = cur.u32()  # 0 light, 1 dark, 2 default
    if present(20):
        fields["text_summarisation"] = cur.short_utf16()
    if present(21):
        fields["stroke_group_size"] = cur.u32()
    if present(22):
        fields["app_custom_data"] = cur.long_utf16()
    out["fields"] = fields

    out["consumed_end"] = cur.pos
    out["hash_boundary"] = len(note) - HASH_SIZE
    out["landed_on_hash"] = cur.pos == len(note) - HASH_SIZE
    return out


def note_doc_common_frames(note: bytes, doc: dict) -> dict:
    """Locate the Common frames of a parsed note: title, body, table cells.

    Returns `{title: frame|None, body: frame|None, cells: [frames]}`. The body
    frame is the largest frame in the body blob; every other body-blob frame
    is a table cell nested in the body frame's inline table object.
    """
    fmt = doc["format_version"]
    title_blob = note[doc["title_off"] : doc["title_off"] + doc["title_size"]]
    body_blob = note[doc["body_off"] : doc["body_off"] + doc["body_size"]]
    title_frames = find_common_frames(title_blob, fmt)
    body_frames = find_common_frames(body_blob, fmt)
    title = max(title_frames, key=lambda f: f["frame_size"]) if title_frames else None
    body = max(body_frames, key=lambda f: f["frame_size"]) if body_frames else None
    cells = [f for f in body_frames if body is not None and f["off"] != body["off"]]
    return {"title": title, "body": body, "cells": cells}
