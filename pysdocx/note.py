"""Parse typed ("keyboard") rich text from a document's note.note file.

Samsung Notes stores typed text at the container level in `note.note`, NOT in the per-page
`.page` files (page 5 of the benchmark has zero stroke/element records — its text lives here).
The text is one UTF-16LE field prefixed by a `[u32][u32 char_count]` header, and its styling is
a list of TLV run markers `18 00 <tag> 00 | pad | u32 start | u32 end | u32 value | u32 enabled`
whose start/end index into that text field. Confirmed on the benchmark (note.note): bold=tag
0x05 over "Grassetto", italic=0x06 over "corsivo", underline=0x07 over "sottolineato", and color
= tag 0x01 whose per-run `value`/`enabled` u32 is an 0xAARRGGBB color ("testorosso"→0xFFFF3636
red, body default→dark gray). This mirrors the per-page TLV logic in crates/sdocx/src/page.rs
(tlv_color / collect_style_runs), applied to note.note instead of a page record.

Highlight ("evidenziato") is tag 0x11 in the same `18 00`-prefixed family — same shape as color,
its `enabled` u32 is the highlight's 0xAARRGGBB. Confirmed on
samples/OnlyTextTypeWritten_260701_180427.sdocx: tag 0x11 start=95 end=133 enabled=0xffff3636 red
over "evidendenziato di rosso il background".

Strikethrough ("cancellato") is a DIFFERENT marker family: prefix `14 00 14 00` (not `18 00`),
otherwise the same `pad | u32 start | u32 end | u32 value | u32 enabled` shape. Confirmed on the
same sample: `14 00 14 00 | 00 00 | start=84 end=95 | value=1 enabled=1` exactly covers
"cancellato\\n" (the only struck-through line), with enabled=0 on the following disabled run
(95-171). This was found by an exhaustive scan of the file for any `pad==0` TLV-shaped record
whose start/end are valid text offsets, grouped by (kind, tag) — `(0x14, 0x14)` was the only
family besides the known `(0x18, tag)` bold/italic/underline/color/font/highlight ones.

Paragraph metadata is stored separately from character runs and indexes paragraph numbers, NOT
character offsets. Samsung uses `14 00 <tag> 00` records for alignment, indent, line spacing and
heading/body level, plus a wider `1c 00 05 00` record for numbered/bulleted/todo prefixes and the
todo checked state. Confirmed on samples/OnlyTextTypeWritten_260701_180427.sdocx: kind 4=numbered,
kind 8=bullet, kind 2=todo; tag 0x03=alignment, tag 0x02=indent, tag 0x0a=heading/body style.
"""

import hashlib
import re
import struct

STYLE_MARKER_PREFIX = b"\x18\x00"
BOLD_TAG = 0x05
ITALIC_TAG = 0x06
UNDERLINE_TAG = 0x07
COLOR_TAG = 0x01
FONT_TAG = 0x03
HIGHLIGHT_TAG = 0x11

# Strikethrough uses its own marker family: prefix `14 00 14 00` instead of `18 00 <tag> 00`.
STRIKETHROUGH_MARKER = b"\x14\x00\x14\x00"
PARAGRAPH_MARKER_PREFIX = b"\x14\x00"
LIST_MARKER = b"\x1c\x00\x05\x00\x00\x00"

# A run marker is: 18 00 <tag_lo> <tag_hi> | 00 00 | u32 start | u32 end | u32 value | u32 enabled
RUN_START_OFF = 6
RUN_END_OFF = 10
RUN_VALUE_OFF = 14
RUN_ENABLED_OFF = 18
RUN_MARKER_LEN = 22
LIST_MARKER_LEN = 30

PARAGRAPH_INDENT_TAG = 0x02
PARAGRAPH_ALIGN_TAG = 0x03
PARAGRAPH_LINE_SPACING_TAG = 0x04
# Paragraph space-before / space-after (float, in the `value` field — note line-spacing puts its
# float in `enabled` instead). Present only on styled paragraphs (body1/heading*); this is what
# makes headings breathe in Samsung Notes and was previously ignored, so headings rendered ~2.2x
# too tight vs the ground truth.
PARAGRAPH_SPACE_BEFORE_TAG = 0x08
PARAGRAPH_SPACE_AFTER_TAG = 0x09
PARAGRAPH_STYLE_TAG = 0x0A
ALIGNMENTS = {0: "left", 1: "right", 2: "center"}
PARAGRAPH_STYLES = {0: "heading1", 1: "heading2", 2: "heading3", 3: "body1"}
LIST_TYPES = {2: "todo", 4: "numbered", 8: "bullet"}

MIN_TEXT_FIELD_CHARS = 16
# The typed-text field is preceded by a u32 char-count header; the count matches the field length
# exactly or is off by one (a trailing terminator). Everything else that decodes as a long printable
# UTF-16LE run — chiefly the pen-preload resource path read at the wrong byte alignment — lacks a
# matching header, so validating it rejects those false positives without inspecting the text itself
# (works regardless of the body language, including CJK).
TEXT_FIELD_LEN_TOLERANCE = 2


# 0xFFFC (object replacement char) anchors inline objects inside the text and must be kept as
# part of the field, or it splits the run and throws off the style-run indices.
def _is_printable_unit(unit: int) -> bool:
    return unit == 0x0A or unit == 0xFFFC or 0x20 <= unit <= 0xD7FF


# Leading characters that are field padding, not body text (newlines + object anchors).
_LEADING_PAD = "\n￼"


def _find_text_field(data: bytes) -> tuple[int, str] | None:
    """Return `(start_byte, text)` of the typed-text field, or None if the note carries no text.

    The field is the longest printable UTF-16LE run whose u32 char-count header (immediately before
    it) matches its length. Requiring the header rejects the false positive that would otherwise win
    on note-only-drawing files: the pen-preload resource string (`com.samsung...InkPen2`), which is
    itself UTF-16LE but gets picked up one byte off, turning its ASCII into a long CJK run. The run
    markers index characters from the field start (which begins with the header-inserted leading
    newlines), so the field start is char index 0 for the run offsets.
    """
    candidates: list[tuple[int, int]] = []
    i = 0
    n = len(data)
    while i + 2 <= n:
        if _is_printable_unit(struct.unpack_from("<H", data, i)[0]):
            j = i
            while j + 2 <= n and _is_printable_unit(struct.unpack_from("<H", data, j)[0]):
                j += 2
            length = (j - i) // 2
            if length >= MIN_TEXT_FIELD_CHARS:
                candidates.append((i, length))
            i = j + 2
        else:
            i += 2
    candidates.sort(key=lambda c: -c[1])
    for start, length in candidates:
        if start < 4:
            continue
        declared = struct.unpack_from("<I", data, start - 4)[0]
        if abs(declared - length) <= TEXT_FIELD_LEN_TOLERANCE:
            # The header char count is authoritative: the printable run can spill one char past it
            # onto the next field's bytes (e.g. a trailing u32 whose low byte decodes as '('), so
            # decode `declared`, not the raw run length.
            text_len = min(length, declared)
            text = data[start : start + text_len * 2].decode("utf-16-le", errors="replace")
            return start, text
    return None


def _marker_runs(data: bytes, marker: bytes, text_len: int) -> list[tuple[int, int, int, int]]:
    """All `(start, end, value, enabled)` TLV records right after `marker`, within the text."""
    runs = []
    off = data.find(marker)
    while off != -1:
        if off + RUN_MARKER_LEN <= len(data):
            start = struct.unpack_from("<I", data, off + RUN_START_OFF)[0]
            end = struct.unpack_from("<I", data, off + RUN_END_OFF)[0]
            value = struct.unpack_from("<I", data, off + RUN_VALUE_OFF)[0]
            enabled = struct.unpack_from("<I", data, off + RUN_ENABLED_OFF)[0]
            if start < end <= text_len:
                runs.append((start, end, value, enabled))
        off = data.find(marker, off + 1)
    return runs


def _style_runs(data: bytes, tag: int, text_len: int) -> list[tuple[int, int, int, int]]:
    """All `(start, end, value, enabled)` run markers for `tag` whose range is within the text."""
    marker = STYLE_MARKER_PREFIX + bytes([tag & 0xFF, tag >> 8])
    return _marker_runs(data, marker, text_len)


def _paragraph_metadata(note_bytes: bytes, paragraph_count: int) -> list[dict]:
    """Decode paragraph-level records indexed by paragraph number, not character offset.

    After the character-style TLV block, Samsung emits another TLV-like family whose start/end
    ranges index `text.split("\\n")` paragraph numbers. These are `14 00 <tag> 00 | pad | u32
    start | u32 end | u32 value | u32 enabled`; they carry alignment, indent and heading/body
    levels. List/todo prefixes use a wider sibling record:
    `1c 00 05 00 00 00 | u32 start | u32 end | u32 kind | u32 value | u32 reserved | u32 enabled`.
    Confirmed on OnlyTextTypeWritten_260701_180427: kind 4=numbered with value 1/2/3, kind
    8=bullet, kind 2=todo with value 0/1 unchecked/checked.
    """
    paragraphs = [
        {
            "alignment": "left",
            "indent": 0,
            "style": None,
            "line_spacing": None,
            "space_before": 0.0,
            "space_after": 0.0,
            "list": None,
        }
        for _ in range(paragraph_count)
    ]

    def apply_space_float(tag_value: int, key: str, start: int, end: int) -> None:
        space = struct.unpack("<f", struct.pack("<I", tag_value))[0]
        if space == space and 0.0 <= space <= 200.0:  # finite, plausible
            apply_span(start, end, lambda p, space=space: p.update({key: space}))

    def apply_span(start: int, end: int, update) -> None:
        if not (0 <= start < end <= paragraph_count):
            return
        for i in range(start, end):
            update(paragraphs[i])

    off = note_bytes.find(PARAGRAPH_MARKER_PREFIX)
    while off != -1:
        if off + RUN_MARKER_LEN <= len(note_bytes) and note_bytes[off + 4 : off + 6] == b"\x00\x00":
            tag = struct.unpack_from("<H", note_bytes, off + 2)[0]
            start = struct.unpack_from("<I", note_bytes, off + RUN_START_OFF)[0]
            end = struct.unpack_from("<I", note_bytes, off + RUN_END_OFF)[0]
            value = struct.unpack_from("<I", note_bytes, off + RUN_VALUE_OFF)[0]
            enabled = struct.unpack_from("<I", note_bytes, off + RUN_ENABLED_OFF)[0]
            if tag == PARAGRAPH_INDENT_TAG and enabled:
                apply_span(start, end, lambda p, value=value: p.update(indent=value))
            elif tag == PARAGRAPH_ALIGN_TAG and value in ALIGNMENTS:
                apply_span(start, end, lambda p, value=value: p.update(alignment=ALIGNMENTS[value]))
            elif tag == PARAGRAPH_LINE_SPACING_TAG:
                spacing = struct.unpack("<f", struct.pack("<I", enabled))[0]
                if spacing == spacing and 0.5 <= spacing <= 4.0:
                    apply_span(start, end, lambda p, spacing=spacing: p.update(line_spacing=spacing))
            elif tag == PARAGRAPH_SPACE_BEFORE_TAG:
                apply_space_float(value, "space_before", start, end)
            elif tag == PARAGRAPH_SPACE_AFTER_TAG:
                apply_space_float(value, "space_after", start, end)
            elif tag == PARAGRAPH_STYLE_TAG and value in PARAGRAPH_STYLES:
                apply_span(start, end, lambda p, value=value: p.update(style=PARAGRAPH_STYLES[value]))
        off = note_bytes.find(PARAGRAPH_MARKER_PREFIX, off + 1)

    off = note_bytes.find(LIST_MARKER)
    while off != -1:
        if off + LIST_MARKER_LEN <= len(note_bytes):
            start, end, kind, value, _reserved, enabled = struct.unpack_from("<IIIIII", note_bytes, off + 6)
            list_type = LIST_TYPES.get(kind)
            if list_type is not None and enabled:
                def update(p, list_type=list_type, value=value):
                    item = {"type": list_type}
                    if list_type == "numbered":
                        item["number"] = value
                    elif list_type == "todo":
                        item["checked"] = bool(value)
                    p["list"] = item

                apply_span(start, end, update)
        off = note_bytes.find(LIST_MARKER, off + 1)

    return paragraphs


def parse_typed_text(note_bytes: bytes) -> dict | None:
    """Extract the typed rich text from `note.note`.

    Returns a dict with the body text and per-run styles mapped to body-text coordinates:
    `{text, runs: [{start, end, style}], colors: [{start, end, color}],
    highlights: [{start, end, color}], font_size, paragraphs}`, where `style` is one of
    "bold"/"italic"/"underline"/"strikethrough". `paragraphs` is aligned with
    `text.split("\\n")` and carries list/alignment/indent/style metadata. `text` has the header's
    leading newlines stripped; run/color/highlight offsets are relative to it. Returns None if no
    text field found.
    """
    field = _find_text_field(note_bytes)
    if field is None:
        return None
    _, raw = field
    raw_len = len(raw)

    lead = len(raw) - len(raw.lstrip(_LEADING_PAD))
    body = raw[lead:]
    paragraph_lead = raw[:lead].count("\n")
    paragraphs = _paragraph_metadata(note_bytes, len(raw.split("\n")))[paragraph_lead:]

    def rebase(start: int, end: int) -> tuple[int, int] | None:
        s, e = start - lead, end - lead
        if e <= 0 or s >= len(body):
            return None
        return max(s, 0), min(e, len(body))

    runs: list[dict] = []
    for tag, key in ((BOLD_TAG, "bold"), (ITALIC_TAG, "italic"), (UNDERLINE_TAG, "underline")):
        for start, end, _value, enabled in _style_runs(note_bytes, tag, raw_len):
            if enabled:  # explicit "on" run; Samsung emits a matching "off" run we can ignore
                rb = rebase(start, end)
                if rb:
                    runs.append({"start": rb[0], "end": rb[1], "style": key})
    strike_runs = _marker_runs(note_bytes, STRIKETHROUGH_MARKER, raw_len)
    # Type 20 stores its boolean in payload byte 0.  The upper three bytes are
    # residue and need not be zero (AllSamsung carries 0x00007701 / 0x771f0c00,
    # whose low bytes are the expected on/off pair).  The short marker can also
    # collide elsewhere, so retain the structural pairing guard: the following
    # type-20 record must begin exactly where the active one ends.
    strike_starts = {s for s, _e, _v, en in strike_runs if en & 0xFF in (0, 1)}
    for start, end, _value, enabled in strike_runs:
        if enabled & 0xFF == 1 and end in strike_starts:
            rb = rebase(start, end)
            if rb:
                runs.append({"start": rb[0], "end": rb[1], "style": "strikethrough"})

    colors: list[dict] = []
    for start, end, value, enabled in _style_runs(note_bytes, COLOR_TAG, raw_len):
        argb = enabled  # for the color tag the trailing u32 is the 0xAARRGGBB color
        r, g, b = (argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF
        rb = rebase(start, end)
        if rb is not None and (argb >> 24) == 0xFF:
            colors.append({"start": rb[0], "end": rb[1], "color": (r, g, b)})

    highlights: list[dict] = []
    for start, end, value, enabled in _style_runs(note_bytes, HIGHLIGHT_TAG, raw_len):
        argb = enabled  # same shape as color: trailing u32 is the highlight's 0xAARRGGBB
        r, g, b = (argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF
        rb = rebase(start, end)
        if rb is not None and (argb >> 24) == 0xFF:
            highlights.append({"start": rb[0], "end": rb[1], "color": (r, g, b)})

    font_size = None
    font_sizes: list[dict] = []
    font_runs = _style_runs(note_bytes, FONT_TAG, raw_len)
    if font_runs:
        for start, end, _value, enabled in font_runs:
            raw_f = struct.pack("<I", enabled)
            candidate = struct.unpack("<f", raw_f)[0]
            rb = rebase(start, end)
            if rb is not None and candidate == candidate and 4.0 <= candidate <= 200.0:
                font_sizes.append({"start": rb[0], "end": rb[1], "font_size": candidate})
                if font_size is None:
                    font_size = candidate

    return {
        "text": body,
        "runs": runs,
        "colors": colors,
        "highlights": highlights,
        "font_size": font_size,
        "font_sizes": font_sizes,
        "paragraphs": paragraphs,
    }


# Table cells also live in note.note (not the page). Each cell is preceded by a
# 10-byte marker `06 00` + the cell's Common frame header `[u32 frame_size]
# [u32 char_count]`, immediately after which its UTF-16LE text begins. The
# cell's bottom-left corner in page coords is the f64 pair at `marker - 16` (x)
# and `marker - 8` (y). (The structural parser `note_doc.note_doc_tables` is the
# authoritative decoder; this marker scan is the render/legacy path.)
#
# A cell is accepted by validating its frame header structurally: the
# `frame_size` must be a plausible sub-64KB size that leaves room for the text.
# An earlier version allowlisted the low byte of `frame_size` (0x8d/0x95/0xcd),
# but that low byte tracks the frame's exact size and so varies with per-cell
# styling and even between plain corpora — the 4x3 styled family (frame sizes
# 137..239) is a counterexample. See docs/format/container/note-note/tables.md.
TABLE_CELL_PREFIX = b"\x06\x00"
TABLE_CELL_MAX_FRAME = 0xFFFF
TABLE_CELL_MARKER_LEN = 10
TABLE_ANCHOR_X_BACK = 16
TABLE_ANCHOR_Y_BACK = 8

# Each cell's rich-text style follows immediately after its own text, as its OWN small run of
# the exact same TLV markers used by parse_typed_text (`18 00 <tag> 00 | pad | u32 start |
# u32 end | u32 value | u32 enabled`) — just scoped locally: start=0, end=char_count (the cell's
# own text length), not offsets into the document-wide typed-text field. Confirmed on
# Associationpages...'s table: cell "c12ingrassettoepiccolo" (22 chars) is immediately followed
# by a color run (default), a font run (enabled=4.0 as f32 — "piccolo"/small), and a bold run
# (tag 0x5, enabled=1 — "grassetto"/bold); its sibling cells (plain text, no styling) only carry
# the color+font runs, no bold run. The window below (200 bytes) comfortably covers all of a
# cell's runs without reaching into the next cell's (observed span for a 3-run cell: ~100 bytes).
CELL_STYLE_WINDOW = 200
VOICE_LABEL_RE = re.compile(r"^(?:Voice|Voce) \d+$")
VOICE_DURATION_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
PRELOAD_PATH_MARKER = "com.samsung.android.sdk.pen.pen.preload."
TAIL_SENTINEL = b"\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00"
TAIL_HASH_DISTINCT_MIN = 20
TAIL_HASH_MAX_ZERO_BYTES = 4


def _read_i32(data: bytes, offset: int) -> int | None:
    if offset + 4 > len(data):
        return None
    return struct.unpack_from("<i", data, offset)[0]


def _read_i64(data: bytes, offset: int) -> int | None:
    if offset + 8 > len(data):
        return None
    return struct.unpack_from("<q", data, offset)[0]


def _read_short_utf16(data: bytes, offset: int) -> tuple[str, int] | None:
    if offset + 2 > len(data):
        return None
    char_len = struct.unpack_from("<h", data, offset)[0]
    offset += 2
    if char_len < 0:
        return None
    end = offset + char_len * 2
    if end > len(data):
        return None
    return data[offset:end].decode("utf-16-le", errors="replace"), end


def _extract_title_from_blob(data: bytes) -> str:
    """Extract the title text from the note-level title object blob.

    The outer note metadata is structurally decoded, but the inner title-object schema is still
    only partially understood. In all current samples the actual title appears as
    `u32 char_len + UTF-16LE text` somewhere inside that blob.
    """
    if len(data) < 12:
        return ""
    for i in range(0, max(0, len(data) - 10)):
        char_len = struct.unpack_from("<i", data, i)[0]
        if not (1 <= char_len <= 200):
            continue
        start = i + 4
        end = start + char_len * 2
        if end > len(data):
            continue
        text = data[start:end].decode("utf-16-le", errors="replace")
        if text and all(ch == "\n" or 0x20 <= ord(ch) <= 0xD7FF for ch in text):
            return text
    return ""


def _read_u16_len_prefixed_utf16(data: bytes, offset: int) -> tuple[str, int] | None:
    if offset + 2 > len(data):
        return None
    char_len = struct.unpack_from("<H", data, offset)[0]
    if not (1 <= char_len <= 128):
        return None
    start = offset + 2
    end = start + char_len * 2
    if end > len(data):
        return None
    return data[start:end].decode("utf-16-le", errors="replace"), end


def _u32_pairs_as_u64(values: list[int]) -> list[int]:
    """Expose raw u32 tails as little-endian u64 pairs for RE diagnostics."""
    return [values[i] | (values[i + 1] << 32) for i in range(0, len(values) - 1, 2)]


def _duration_to_ms(text: str) -> int | None:
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError:
        return None
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def _scan_voice_clip_metadata(note_bytes: bytes) -> list[dict]:
    """Infer voice-clip descriptors from adjacent length-prefixed UTF-16 strings."""
    clips: list[dict] = []
    off = 0
    while off + 8 <= len(note_bytes):
        first = _read_u16_len_prefixed_utf16(note_bytes, off)
        if first is None:
            off += 2
            continue
        label, after_label = first
        if not VOICE_LABEL_RE.fullmatch(label):
            off += 2
            continue
        second = _read_u16_len_prefixed_utf16(note_bytes, after_label)
        if second is None:
            off += 2
            continue
        duration, after_duration = second
        if VOICE_DURATION_RE.fullmatch(duration):
            clips.append({
                "label": label,
                "duration": duration,
                "label_off": off,
                "duration_off": after_label,
                "end": after_duration,
            })
            off = after_duration
        else:
            off += 2
    return clips


def _scan_preload_param_hint(note_bytes: bytes, path_field_start: int) -> str | None:
    """Return the nearest digit/semicolon parameter string before a preload path field."""
    best = None
    search_start = max(0, path_field_start - 64)
    for off in range(search_start, path_field_start, 2):
        parsed = _read_u16_len_prefixed_utf16(note_bytes, off)
        if parsed is None:
            continue
        candidate, end = parsed
        if not candidate or not any(ch.isdigit() for ch in candidate):
            continue
        if not all(ch.isdigit() or ch == ";" for ch in candidate):
            continue
        if end <= path_field_start and note_bytes[end:path_field_start].strip(b"\x00") == b"":
            best = (end, candidate)
    return best[1] if best else None


def _scan_pen_preload_paths(note_bytes: bytes, start: int) -> list[dict]:
    """Pen-preload resource paths repeatedly appear in note.note tail blocks.

    The path itself is a length-prefixed UTF-16 field. The surrounding record schema is still
    partial, but the path and the nearby digit/semicolon parameter hint are stable tail markers.
    """
    records: list[dict] = []
    marker = PRELOAD_PATH_MARKER.encode("utf-16-le")
    off = start
    while True:
        hit = note_bytes.find(marker, off)
        if hit < 0:
            break
        off = hit + 2
        field_start = hit - 2
        parsed = _read_u16_len_prefixed_utf16(note_bytes, field_start)
        if parsed is None:
            continue
        text, text_end = parsed
        if not text.startswith(PRELOAD_PATH_MARKER):
            continue
        param_hint = _scan_preload_param_hint(note_bytes, field_start)
        records.append({
            "kind": "pen_preload_path",
            "off": field_start,
            "end": text_end,
            "path": text,
            "param_hint": param_hint,
        })
    return records


def _decode_pen_preload_prelude(blob: bytes) -> dict | None:
    """Decode the small config block immediately before a preload path, when present.

    Most preload path fields are preceded by a compact record shaped like
    `u32... | u16 char_len | UTF-16LE digit/semicolon params | trailing u32...`. The surrounding
    schema is still incomplete, so this returns raw prefix/trailing integers plus the parsed
    parameter string instead of assigning stronger semantics.
    """
    best = None
    for off in range(0, min(len(blob), 16) + 1, 2):
        if off + 2 > len(blob):
            continue
        char_len = struct.unpack_from("<H", blob, off)[0]
        text_start = off + 2
        text_end = text_start + char_len * 2
        if not (1 <= char_len <= 24) or text_end > len(blob):
            continue
        try:
            param = blob[text_start:text_end].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        if not param or not any(ch.isdigit() for ch in param):
            continue
        if not all(ch.isdigit() or ch == ";" for ch in param):
            continue
        prefix_u32 = [
            struct.unpack_from("<I", blob, pos)[0]
            for pos in range(0, off, 4)
            if pos + 4 <= off
        ]
        trailing_u32 = [
            struct.unpack_from("<I", blob, pos)[0]
            for pos in range(text_end, len(blob), 4)
            if pos + 4 <= len(blob)
        ]
        best = {
            "param": param,
            "param_off": off,
            "prefix_u32": prefix_u32,
            "trailing_u32": trailing_u32,
            "raw_hex": blob.hex(),
        }
    return best


def _decode_pen_style_tail(blob: bytes) -> dict | None:
    """Decode a recurring pen-style tail block after the final preload path.

    Current evidence: these blocks start with an f32-like pen width, an ARGB color, and `u32(1)`,
    followed by small raw fields and fixed-looking markers. Only the stable leading fields are
    named; the rest stays raw.
    """
    if len(blob) not in (50, 62, 66) or len(blob) < 24:
        return None
    width = struct.unpack_from("<f", blob, 0)[0]
    argb = struct.unpack_from("<I", blob, 4)[0]
    enabled = struct.unpack_from("<I", blob, 8)[0]
    if not (0.0 <= width <= 40.0 and (argb >> 24) == 0xFF and enabled == 1):
        return None
    param = None
    param_end = 12
    if len(blob) >= 18:
        char_len = struct.unpack_from("<H", blob, 12)[0]
        text_start = 14
        text_end = text_start + char_len * 2
        if 1 <= char_len <= 24 and text_end <= len(blob):
            try:
                candidate = blob[text_start:text_end].decode("utf-16-le")
            except UnicodeDecodeError:
                candidate = ""
            if candidate and any(ch.isdigit() for ch in candidate) and all(
                ch.isdigit() or ch == ";" for ch in candidate
            ):
                param = candidate
                param_end = text_end
    return {
        "width": width,
        "argb": f"0x{argb:08x}",
        "enabled": enabled,
        "param": param,
        "raw_u32": [
            struct.unpack_from("<I", blob, pos)[0]
            for pos in range(param_end, len(blob), 4)
            if pos + 4 <= len(blob)
        ],
        "raw_hex": blob.hex(),
    }


def _tail_hash_blocks(note_bytes: bytes, start: int) -> list[dict]:
    """Opaque 32-byte hash-like tail blocks seen in the current v5400 family."""
    records: list[dict] = []
    off = start
    end = len(note_bytes)
    while off + 40 <= end:
        a = struct.unpack_from("<I", note_bytes, off)[0]
        b = struct.unpack_from("<I", note_bytes, off + 4)[0]
        blob = note_bytes[off + 8 : off + 40]
        if (
            a <= 4
            and b <= 4
            and (a or b)
            and len(set(blob)) >= TAIL_HASH_DISTINCT_MIN
            and blob.count(0) <= TAIL_HASH_MAX_ZERO_BYTES
        ):
            records.append({
                "kind": "tail_hash_block",
                "off": off,
                "end": off + 40,
                "prefix_u32": [a, b],
                "hash32": blob.hex(),
            })
            off += 40
        else:
            off += 2
    return records


def _tail_gaps(records: list[dict], start: int, end: int) -> list[tuple[int, int, dict | None, dict | None]]:
    """Return unclassified gaps as `(start, end, previous_record, next_record)`."""
    gaps = []
    prev = None
    cursor = start
    for record in sorted(records, key=lambda r: (r["off"], r["end"], r["kind"])):
        if cursor < record["off"]:
            gaps.append((cursor, record["off"], prev, record))
        if record["end"] > cursor:
            cursor = record["end"]
            prev = record
    if cursor < end:
        gaps.append((cursor, end, prev, None))
    return gaps


def _scan_tail_gap_records(note_bytes: bytes, start: int, records: list[dict]) -> list[dict]:
    """Classify small tail gaps adjacent to already-known records.

    These records intentionally keep conservative names (`*_raw`, `raw_u32`) where semantics are
    not settled. The purpose is structural coverage: keep recurring, bounded tail blocks visible
    instead of treating them as anonymous bytes.
    """
    extra: list[dict] = []
    for gap_start, gap_end, prev_record, next_record in _tail_gaps(records, start, len(note_bytes)):
        blob = note_bytes[gap_start:gap_end]
        prev_kind = (prev_record or {}).get("kind")
        next_kind = (next_record or {}).get("kind")

        style = _decode_pen_style_tail(blob)
        if style is not None:
            extra.append({"kind": "pen_style_tail", "off": gap_start, "end": gap_end, **style})
            continue

        if prev_kind == "voice_clip":
            raw_u32 = [
                struct.unpack_from("<I", blob, pos)[0]
                for pos in range(0, len(blob), 4)
                if pos + 4 <= len(blob)
            ]
            extra.append({
                "kind": "voice_clip_post",
                "off": gap_start,
                "end": gap_end,
                "raw_u32": raw_u32,
                "raw_u64_pairs": _u32_pairs_as_u64(raw_u32),
                "raw_hex": blob.hex(),
            })
            continue

        if next_kind == "pen_preload_path":
            prelude = _decode_pen_preload_prelude(blob)
            if prelude is not None:
                extra.append({"kind": "pen_preload_prelude", "off": gap_start, "end": gap_end, **prelude})
            elif len(blob) <= 24:
                extra.append({
                    "kind": "pen_preload_prelude_raw",
                    "off": gap_start,
                    "end": gap_end,
                    "raw_u32": [
                        struct.unpack_from("<I", blob, pos)[0]
                        for pos in range(0, len(blob), 4)
                        if pos + 4 <= len(blob)
                    ],
                    "raw_hex": blob.hex(),
                })
            continue

        if next_kind == "voice_clip" and len(blob) == 16:
            raw_u32 = list(struct.unpack_from("<4I", blob, 0))
            extra.append({
                "kind": "voice_clip_header",
                "off": gap_start,
                "end": gap_end,
                "raw_u32": raw_u32,
                "media_index_candidate": raw_u32[3] if raw_u32[:2] == [0, 1] else None,
            })
            continue

        if prev_kind == "tail_hash_block" and len(blob) == 4:
            extra.append({
                "kind": "tail_post_hash_u32",
                "off": gap_start,
                "end": gap_end,
                "value": struct.unpack_from("<I", blob, 0)[0],
            })
    return extra


def scan_note_tail_records(note_bytes: bytes, offset_to_data: int) -> list[dict]:
    """Conservative classification of note.note tail records after the top-level metadata."""
    if not (0 <= offset_to_data < len(note_bytes)):
        return []

    tail = note_bytes[offset_to_data:]
    records: list[dict] = []
    cursor = offset_to_data
    if tail.startswith(TAIL_SENTINEL):
        records.append({
            "kind": "tail_sentinel",
            "off": offset_to_data,
            "end": offset_to_data + len(TAIL_SENTINEL),
            "signature": TAIL_SENTINEL.hex(),
        })
        cursor += len(TAIL_SENTINEL)

    for clip in _scan_voice_clip_metadata(note_bytes[cursor:]):
        clip_off = cursor + clip["label_off"]
        clip_end = cursor + clip["end"]
        post_u32 = []
        post_start = clip_end
        for i in range(0, 24, 4):
            if post_start + i + 4 > len(note_bytes):
                break
            post_u32.append(struct.unpack_from("<I", note_bytes, post_start + i)[0])
        records.append({
            "kind": "voice_clip",
            "off": clip_off,
            "end": clip_end,
            "label": clip["label"],
            "duration": clip["duration"],
            "duration_ms_display": _duration_to_ms(clip["duration"]),
            "post_u32": post_u32,
            "post_u64_pairs": _u32_pairs_as_u64(post_u32),
        })

    records.extend(_scan_pen_preload_paths(note_bytes, cursor))
    records.extend(_tail_hash_blocks(note_bytes, cursor))
    records.extend(_scan_tail_gap_records(note_bytes, cursor, records))
    records.sort(key=lambda r: (r["off"], r["end"], r["kind"]))
    for idx, record in enumerate(records):
        if record.get("kind") != "voice_clip":
            continue
        prev_record = records[idx - 1] if idx > 0 else {}
        next_record = records[idx + 1] if idx + 1 < len(records) else {}
        if prev_record.get("kind") == "voice_clip_header":
            record["media_index_candidate"] = prev_record.get("media_index_candidate")
            record["header_u32"] = prev_record.get("raw_u32", [])
        if next_record.get("kind") == "voice_clip_post":
            raw_u32 = next_record.get("raw_u32", [])
            if raw_u32:
                record["actual_duration_ms_candidate"] = (
                    raw_u32[-3]
                    if len(raw_u32) >= 3 and raw_u32[-2] == 0 and raw_u32[-1] < 1000
                    else raw_u32[-1]
                )
            if len(raw_u32) >= 8 and raw_u32[6] == 4:
                record["media_time_candidate"] = raw_u32[7] | (raw_u32[8] << 32) if len(raw_u32) > 8 else None
    deduped: list[dict] = []
    seen = set()
    for record in records:
        key = (record["kind"], record["off"], record["end"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def annotate_note_tail_with_page_id_info(note_meta: dict | None, page_id_info: bytes | None) -> dict | None:
    """Attach pageIdInfo-derived relations to parsed note tail records.

    Current corpus result:
    - `[2, 2] + hash32` blocks match the first 32 bytes of `pageIdInfo.dat` exactly.
    - `[0, 2] + hash32` blocks store `u32(2)` plus the first 28 bytes of that same pageIdInfo head.
    """
    if note_meta is None or page_id_info is None:
        return note_meta
    if len(page_id_info) < 32:
        return note_meta

    page_id_head = page_id_info[:32]
    annotated = dict(note_meta)
    records = []
    for record in note_meta.get("tail_records", ()):
        rec = dict(record)
        if rec.get("kind") == "tail_hash_block":
            blob = bytes.fromhex(rec["hash32"])
            exact = blob == page_id_head
            shifted = (
                len(blob) == 32
                and blob[:4] == struct.pack("<I", 2)
                and blob[4:] == page_id_head[:28]
            )
            rec["page_id_info_relation"] = {
                "matches_page_id_head_exact": exact,
                "matches_page_id_head_shifted_with_u32_2": shifted,
            }
        records.append(rec)
    annotated["tail_records"] = records
    return annotated


def parse_note_metadata(note_bytes: bytes) -> dict | None:
    """Parse note.note's top-level metadata block plus conservative extra metadata."""
    if len(note_bytes) < 64:
        return None

    try:
        pos = 0
        offset_to_data = _read_i32(note_bytes, pos)
        pos += 4
        pos += 1
        flags = _read_i32(note_bytes, pos)
        pos += 4
        pos += 1
        meta_flags = _read_i32(note_bytes, pos)
        pos += 4
        format_version = _read_i32(note_bytes, pos)
        pos += 4
        note_id_result = _read_short_utf16(note_bytes, pos)
        if note_id_result is None:
            return None
        note_id, pos = note_id_result
        file_revision = _read_i32(note_bytes, pos)
        pos += 4
        created_time = _read_i64(note_bytes, pos)
        pos += 8
        modified_time = _read_i64(note_bytes, pos)
        pos += 8
        width = _read_i32(note_bytes, pos)
        pos += 4
        height = _read_i32(note_bytes, pos)
        pos += 4
        page_h_padding = _read_i32(note_bytes, pos)
        pos += 4
        page_v_padding = _read_i32(note_bytes, pos)
        pos += 4
        min_format_version = _read_i32(note_bytes, pos)
        pos += 4
        title_size = _read_i32(note_bytes, pos)
        pos += 4

        title = ""
        title_off = pos
        if title_size is not None and 0 < title_size <= len(note_bytes) - pos:
            title = _extract_title_from_blob(note_bytes[pos : pos + title_size])

        trailing_hash = note_bytes[-32:] if len(note_bytes) >= 32 else b""
        calculated_trailing_hash = hashlib.sha256(note_bytes[:-32]).digest() if len(note_bytes) >= 32 else b""
        tail_records = scan_note_tail_records(note_bytes, offset_to_data)
        return {
            "offset_to_data": offset_to_data,
            "flags": flags,
            "meta_flags": meta_flags,
            "format_version": format_version,
            "note_id": note_id,
            "file_revision": file_revision,
            "created_time": created_time,
            "modified_time": modified_time,
            "width": width,
            "height": height,
            "page_h_padding": page_h_padding,
            "page_v_padding": page_v_padding,
            "min_format_version": min_format_version,
            "title_size": title_size,
            "title_off": title_off,
            "title": title,
            "trailing_hash": trailing_hash.hex(),
            "trailing_hash_algorithm": "sha256(note.note[:-32])",
            "trailing_hash_matches_sha256_prefix": calculated_trailing_hash == trailing_hash,
            "voice_clips": _scan_voice_clip_metadata(note_bytes),
            "tail_records": tail_records,
        }
    except (IndexError, struct.error, UnicodeDecodeError):
        return None


def _cell_style(note_bytes: bytes, cell_end: int, char_count: int) -> dict:
    """Read one cell's style runs from the TLV block right after its text.

    Returns `{bold, italic, underline, color, font_size}` (color/font_size None if not an
    explicit non-default run). Only runs matching this cell exactly (start=0, end=char_count)
    are accepted, so a run window overrunning into the next cell can't be mistaken for this one's.
    """
    window = note_bytes[cell_end : cell_end + CELL_STYLE_WINDOW]
    style = {"bold": False, "italic": False, "underline": False, "color": None, "font_size": None}
    for tag, key in ((BOLD_TAG, "bold"), (ITALIC_TAG, "italic"), (UNDERLINE_TAG, "underline")):
        marker = STYLE_MARKER_PREFIX + bytes([tag & 0xFF, tag >> 8])
        i = window.find(marker)
        if i >= 0 and i + RUN_MARKER_LEN <= len(window):
            start = struct.unpack_from("<I", window, i + RUN_START_OFF)[0]
            end = struct.unpack_from("<I", window, i + RUN_END_OFF)[0]
            enabled = struct.unpack_from("<I", window, i + RUN_ENABLED_OFF)[0]
            if start == 0 and end == char_count and enabled:
                style[key] = True

    color_marker = STYLE_MARKER_PREFIX + bytes([COLOR_TAG, 0])
    i = window.find(color_marker)
    if i >= 0 and i + RUN_MARKER_LEN <= len(window):
        start = struct.unpack_from("<I", window, i + RUN_START_OFF)[0]
        end = struct.unpack_from("<I", window, i + RUN_END_OFF)[0]
        argb = struct.unpack_from("<I", window, i + RUN_ENABLED_OFF)[0]
        if start == 0 and end == char_count and (argb >> 24) == 0xFF:
            # Always set, including the body-default gray — mirrors parse_typed_text's `colors`
            # list, which likewise includes default-colored runs; the renderer decides what to
            # treat as "no explicit color" (its own contrast-fallback logic).
            style["color"] = ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF)

    font_marker = STYLE_MARKER_PREFIX + bytes([FONT_TAG, 0])
    i = window.find(font_marker)
    if i >= 0 and i + RUN_MARKER_LEN <= len(window):
        start = struct.unpack_from("<I", window, i + RUN_START_OFF)[0]
        end = struct.unpack_from("<I", window, i + RUN_END_OFF)[0]
        raw = struct.pack("<I", struct.unpack_from("<I", window, i + RUN_ENABLED_OFF)[0])
        candidate = struct.unpack("<f", raw)[0]
        if start == 0 and end == char_count and candidate == candidate and 4.0 <= candidate <= 200.0:
            style["font_size"] = candidate

    return style


def _cluster(values: list[float], tol: float = 8.0) -> list[float]:
    """Collapse near-equal coordinates (grid lines) into single averaged values."""
    clusters: list[list[float]] = []
    for v in sorted(values):
        if clusters and v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [sum(c) / len(c) for c in clusters]


def parse_tables(note_bytes: bytes) -> list[dict]:
    """Extract tables from `note.note`.

    Returns a list of `{rows, cols, bbox, x_edges, y_edges, cells}` where each cell is
    `{row, col, text, anchor, bold, italic, underline, color, font_size}` (anchor = bottom-left
    corner in page coords; style fields from `_cell_style`, each cell's own local TLV run block).
    Cells are read in document (row-major) order; the grid is reconstructed by clustering the
    cell anchors into column/row lines (Samsung tables use equal-sized cells). Returns [] if no
    table cells found.
    """
    cells = []
    off = note_bytes.find(TABLE_CELL_PREFIX)
    while off != -1:
        if off + TABLE_CELL_MARKER_LEN > len(note_bytes):
            break
        frame_size = struct.unpack_from("<I", note_bytes, off + 2)[0]
        char_count = struct.unpack_from("<I", note_bytes, off + 6)[0]
        # Frame header must be structurally plausible: a sub-64KB frame that
        # leaves room for its own char_count field + the UTF-16 text.
        if (not (16 <= frame_size <= TABLE_CELL_MAX_FRAME)
                or not (1 <= char_count <= 512)
                or frame_size < 4 + 2 * char_count):
            off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)
            continue

        text_start = off + TABLE_CELL_MARKER_LEN
        text_end = text_start + char_count * 2
        if text_end > len(note_bytes):
            off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)
            continue
        end = text_start
        units = []
        while end + 2 <= text_end:
            unit = struct.unpack_from("<H", note_bytes, end)[0]
            if not (0x20 <= unit <= 0xD7FF):
                break
            units.append(unit)
            end += 2
        if not units:
            off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)
            continue

        anchor = None
        if off - TABLE_ANCHOR_X_BACK >= 0:
            x = struct.unpack_from("<d", note_bytes, off - TABLE_ANCHOR_X_BACK)[0]
            y = struct.unpack_from("<d", note_bytes, off - TABLE_ANCHOR_Y_BACK)[0]
            if 0 <= x <= 3000 and 0 <= y <= 4000:
                anchor = (x, y)
        if anchor is not None:
            cell = {"text": "".join(chr(u) for u in units), "anchor": anchor}
            cell.update(_cell_style(note_bytes, text_end, char_count))
            cells.append(cell)
        off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)

    anchored = [c for c in cells if c["anchor"] is not None]
    if not anchored:
        return []

    xs = _cluster([c["anchor"][0] for c in anchored])
    ys = _cluster([c["anchor"][1] for c in anchored])
    cols, rows = len(xs), len(ys)
    if cols < 1 or rows < 1:
        # Grid didn't reconstruct cleanly — return the cells with their raw anchors only.
        return [{"rows": rows, "cols": cols, "bbox": None, "x_edges": xs, "y_edges": ys, "cells": cells}]

    col_w = (xs[-1] - xs[0]) / (cols - 1) if cols > 1 else 0.0
    row_h = (ys[-1] - ys[0]) / (rows - 1) if rows > 1 else 0.0
    # Anchors are bottom-left corners: xs[0] is the table's left edge; the row anchors are bottoms,
    # so the table top is one row-height above the first row's anchor.
    x_edges = [xs[0] + i * col_w for i in range(cols + 1)]
    y_edges = [ys[0] - row_h + i * row_h for i in range(rows + 1)]
    for cell in cells:
        x, y = cell["anchor"]
        cell["col"] = min(range(cols), key=lambda i: abs(xs[i] - x))
        cell["row"] = min(range(rows), key=lambda i: abs(ys[i] - y))
    return [
        {
            "rows": rows,
            "cols": cols,
            "bbox": (x_edges[0], y_edges[0], x_edges[-1], y_edges[-1]),
            "x_edges": x_edges,
            "y_edges": y_edges,
            "cells": cells,
        }
    ]
