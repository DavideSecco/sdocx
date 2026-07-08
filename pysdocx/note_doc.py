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
                # The object body consumes exactly obj_size bytes (its inner
                # schema — e.g. the type-22 table — is not modeled here), then
                # a u32 char position (the U+FFFC anchor index in the frame
                # text), then 8 trailing bytes of Unknown semantics (observed
                # (3,2) on tables, (0,0) on images).
                obj_win.bytes_(obj_size)
                position = obj_win.u32()
                tail = obj_win.bytes_(obj_win.remaining).hex()
                inline["objects"].append({
                    "frame_size": obj_frame,
                    "obj_size": obj_size,
                    "object_type": obj_type,
                    "position": position,
                    "tail_hex": tail,
                    "body_off": None,  # filled by find_common_frames callers if needed
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
