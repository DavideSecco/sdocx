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
PARAGRAPH_STYLE_TAG = 0x0A
ALIGNMENTS = {0: "left", 1: "right", 2: "center"}
PARAGRAPH_STYLES = {0: "heading1", 1: "heading2", 2: "heading3", 3: "body1"}
LIST_TYPES = {2: "todo", 4: "numbered", 8: "bullet"}

MIN_TEXT_FIELD_CHARS = 16


# 0xFFFC (object replacement char) anchors inline objects inside the text and must be kept as
# part of the field, or it splits the run and throws off the style-run indices.
def _is_printable_unit(unit: int) -> bool:
    return unit == 0x0A or unit == 0xFFFC or 0x20 <= unit <= 0xD7FF


# Leading characters that are field padding, not body text (newlines + object anchors).
_LEADING_PAD = "\n￼"


def _find_text_field(data: bytes) -> tuple[int, str] | None:
    """Return `(start_byte, text)` of the longest printable UTF-16LE run (the typed-text field).

    The run markers index characters from the start of this field (which begins with the
    header-inserted leading newlines), so the field start is char index 0 for the run offsets.
    """
    best_start = best_len = 0
    i = 0
    n = len(data)
    while i + 2 <= n:
        if _is_printable_unit(struct.unpack_from("<H", data, i)[0]):
            j = i
            while j + 2 <= n and _is_printable_unit(struct.unpack_from("<H", data, j)[0]):
                j += 2
            if (j - i) // 2 > best_len:
                best_start, best_len = i, (j - i) // 2
            i = j + 2
        else:
            i += 2
    if best_len < MIN_TEXT_FIELD_CHARS:
        return None
    text = data[best_start : best_start + best_len * 2].decode("utf-16-le", errors="replace")
    return best_start, text


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
            "list": None,
        }
        for _ in range(paragraph_count)
    ]

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
    # Unlike `18 00 <tag> 00`, the 4-byte `14 00 14 00` prefix is short enough to collide with
    # unrelated binary data elsewhere in the TLV block (confirmed on the benchmark note.note: a
    # stray hit with enabled=30465/1998523392 — clearly not a boolean flag). Real strikethrough
    # runs mirror bold/italic/underline: a clean enabled∈{0,1} "on" run immediately followed by an
    # "off" run whose start equals the "on" run's end (e.g. (84,95,enabled=1),(95,171,enabled=0)
    # on the confirmed sample) — require that exact pairing to reject isolated collisions.
    strike_starts = {s for s, _e, _v, en in strike_runs if en in (0, 1)}
    for start, end, _value, enabled in strike_runs:
        if enabled == 1 and end in strike_starts:
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


# Table cells also live in note.note (not the page). Each cell is preceded by a 10-byte marker:
# `06 00 <u16 kind> 00 00 <u32 char_count>`, immediately after which its UTF-16LE text begins.
# The cell's bottom-left corner in page coords is the f64 pair at `marker - 16` (x) and
# `marker - 8` (y). Confirmed on benchmark page 73920cee's kind 0x95 cells ("Cell1,1"...)
# and on Associationpages...'s kind 0x8d sparse table ("c11", "c13", "c21"...).
TABLE_CELL_PREFIX = b"\x06\x00"
TABLE_CELL_KINDS = frozenset({0x8D, 0x95, 0xCD})
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
        kind = struct.unpack_from("<H", note_bytes, off + 2)[0]
        char_count = struct.unpack_from("<I", note_bytes, off + 6)[0]
        if kind not in TABLE_CELL_KINDS or not (1 <= char_count <= 512):
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
